"""Background preference analyser for Phase 2.

Called after every 10 chat turns via FastAPI BackgroundTasks. Opens its own DB
session so the request session is already closed by the time this runs.

Loads the user's last 30 user-role messages, asks Claude to infer preference
suggestions, then stores any actionable ones in pending_suggestions (at most one
pending row per field at a time).
"""

from __future__ import annotations

import json
import logging

from era_agent.db.database import SessionLocal
from era_agent.db.models import Message, PendingSuggestion
from era_agent.profiles.service import (
    TONES, LENGTHS, get_or_create_profile,
)
from era_agent.client import get_client
from era_agent.config import MODEL

logger = logging.getLogger(__name__)

_ANALYSABLE_FIELDS = {
    "preferred_tone", "response_length", "frequent_topics",
    "response_structure", "citation_preference",
}

_PROMPT = """\
You are a silent preference-detection assistant. You will receive a list of recent \
messages that a user sent to a legal AI assistant. Analyse them and suggest updates \
to the user's preferences IF the evidence is clear (at least 3-4 consistent signals). \
Return ONLY a JSON object — no markdown, no explanation — with this exact schema:

{{
  "preferred_tone": {{"value": "<formal|semi-formal|casual>", "rationale": "<one sentence in Romanian, max 100 chars>"}} | null,
  "response_length": {{"value": "<concise|detailed>", "rationale": "<one sentence in Romanian, max 100 chars>"}} | null,
  "frequent_topics": {{"value": ["<topic 1>", ...], "rationale": "<one sentence in Romanian, max 100 chars>"}} | null,
  "response_structure": {{"value": "<one-sentence instruction in Romanian>", "rationale": "<one sentence in Romanian, max 100 chars>"}} | null,
  "citation_preference": {{"value": "<one-sentence instruction in Romanian>", "rationale": "<one sentence in Romanian, max 100 chars>"}} | null
}}

Rules:
- Return null for ANY field if there is not enough clear signal (fewer than 3-4 consistent indicators).
- preferred_tone: infer whether the user's writing style suggests formal, semi-formal, or casual responses.
- response_length: follow-up questions asking for more → "detailed"; user satisfied with short answers / asks to be brief → "concise".
- frequent_topics: extract up to 8 short domain/topic labels in Romanian (e.g. "drept civil", \
"contracte de muncă", "litigii fiscale") that appear repeatedly. Return null if fewer than 3 distinct topics.
- response_structure: if the user repeatedly asks for bullet points, numbered steps, structured sections, \
or plain prose — write a short instruction like "Structurează răspunsurile cu liste numerotate." \
or "Preferă răspunsuri în text continuu, fără liste." Return null if no clear preference.
- citation_preference: if the user frequently requests or reacts positively to citations of specific \
Moldovan law articles / legal acts, write a short instruction like \
"Citează articolele relevante din legislația Republicii Moldova când este posibil." Return null if unclear.
- DO NOT suggest a change for preferred_tone/response_length if the current value already matches the evidence.

Current profile values:
- preferred_tone: {tone}
- response_length: {length}
- frequent_topics: {topics}
- current custom instructions: {custom_instructions}

Recent user messages (newest first):
{messages}
"""


def analyse_preferences(user_id: int) -> None:
    """Run preference analysis in a background task. Silently ignores all errors."""
    db = SessionLocal()
    try:
        _run(db, user_id)
    except Exception:
        logger.exception("analyse_preferences failed for user_id=%s", user_id)
    finally:
        db.close()


def _run(db, user_id: int) -> None:
    msgs = (
        db.query(Message)
        .filter(Message.user_id == user_id, Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(30)
        .all()
    )
    if len(msgs) < 5:
        return

    profile = get_or_create_profile(db, user_id)
    topics_str = ", ".join(profile.frequent_topics or []) or "none"

    messages_block = "\n".join(
        f"{i + 1}. {m.content[:300]}" for i, m in enumerate(msgs)
    )

    prompt = _PROMPT.format(
        tone=profile.preferred_tone,
        length=profile.response_length,
        topics=topics_str,
        custom_instructions=(profile.custom_instructions or "none")[:300],
        messages=messages_block,
    )

    client = get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("analyser returned non-JSON: %s", raw[:200])
        return

    for field in _ANALYSABLE_FIELDS:
        entry = data.get(field)
        if not entry or not isinstance(entry, dict):
            continue

        value = entry.get("value")
        rationale = str(entry.get("rationale", ""))[:300]

        if not _validate(field, value):
            continue

        # Skip if a pending suggestion for this field already exists.
        existing = (
            db.query(PendingSuggestion)
            .filter(
                PendingSuggestion.user_id == user_id,
                PendingSuggestion.field == field,
                PendingSuggestion.status == "pending",
            )
            .first()
        )
        if existing:
            continue

        db.add(PendingSuggestion(
            user_id=user_id,
            field=field,
            suggested_value=value,
            rationale=rationale,
            status="pending",
        ))

    db.commit()


def _validate(field: str, value) -> bool:
    if field == "preferred_tone":
        return isinstance(value, str) and value in TONES
    if field == "response_length":
        return isinstance(value, str) and value in LENGTHS
    if field == "frequent_topics":
        return isinstance(value, list) and len(value) >= 1
    if field in ("response_structure", "citation_preference"):
        return isinstance(value, str) and len(value.strip()) >= 5
    return False
