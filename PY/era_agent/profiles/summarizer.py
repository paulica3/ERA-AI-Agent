"""Conversation summariser for Phase 3 cross-session memory.

Called by the background idle-detector loop and by the manual /end endpoint.
Opens its own DB session so it can be safely called from a background task.
"""

from __future__ import annotations

import logging

from era_agent.db.database import SessionLocal
from era_agent.db.models import Conversation, ConversationSummary, Message
from era_agent.client import get_client
from era_agent.config import MODEL

logger = logging.getLogger(__name__)

_MIN_USER_MESSAGES = 3

_PROMPT = """\
You are summarising a conversation between a user and ERA AI, a legal assistant \
for a law firm in Moldova. Write a concise summary in Romanian (2-4 sentences) \
covering: what the user asked about, any conclusions or decisions reached, and any \
important client, case, or legal context mentioned. Be factual and specific. \
Return only the summary text — no title, no bullet points, no extra commentary.

Conversation:
{transcript}
"""


def summarize_conversation(conversation_id: int) -> bool:
    """Summarise unsummarised messages in a conversation.

    Returns True if a summary was created, False if there was not enough content
    (fewer than 3 user messages since the last summary).
    Silently swallows all errors so background callers never crash.
    """
    db = SessionLocal()
    try:
        return _run(db, conversation_id)
    except Exception:
        logger.exception("summarize_conversation failed for conversation_id=%s", conversation_id)
        return False
    finally:
        db.close()


def _run(db, conversation_id: int) -> bool:
    conv = db.get(Conversation, conversation_id)
    if conv is None:
        return False

    # Find the last summary for this conversation to know where to start.
    last_summary = (
        db.query(ConversationSummary)
        .filter(ConversationSummary.conversation_id == conversation_id)
        .order_by(ConversationSummary.created_at.desc())
        .first()
    )

    # Load messages after the last covered message (or all if first summary).
    msg_query = db.query(Message).filter(Message.conversation_id == conversation_id)
    if last_summary and last_summary.last_message_id:
        last_msg = db.get(Message, last_summary.last_message_id)
        if last_msg:
            msg_query = msg_query.filter(Message.created_at > last_msg.created_at)

    messages = msg_query.order_by(Message.created_at).all()

    user_count = sum(1 for m in messages if m.role == "user")
    if user_count < _MIN_USER_MESSAGES:
        return False

    transcript = "\n".join(
        f"{'Utilizator' if m.role == 'user' else 'ERA AI'}: {m.content[:800]}"
        for m in messages
    )

    client = get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=400,
        messages=[{"role": "user", "content": _PROMPT.format(transcript=transcript)}],
    )
    summary_text = "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()

    if not summary_text:
        return False

    last_message_id = messages[-1].id if messages else None
    db.add(ConversationSummary(
        conversation_id=conversation_id,
        user_id=conv.user_id,
        summary_text=summary_text,
        last_message_id=last_message_id,
    ))
    db.commit()
    return True
