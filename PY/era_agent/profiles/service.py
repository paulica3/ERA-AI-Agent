"""Profile read/write, free-text sanitization, diacritic folding, and the
resolver that renders the profile block injected into the chat system prompt.

The resolver (build_profile_block) is the single seam where a future
"shared firm profile" mode could swap in a firm-wide profile instead of the
per-user one, without touching the chat pipeline.
"""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy.orm import Session

from era_agent.db.models import UserProfile

# ── Allowed enum values (validated on write) ──────────────────────────────────
TONES = {"formal", "semi-formal", "casual"}
LANGUAGES = {"ro", "en", "ru"}
LENGTHS = {"concise", "detailed"}

_TONE_LABEL = {"formal": "formal", "semi-formal": "semi-formal", "casual": "casual"}
_LANG_LABEL = {"ro": "Romanian", "en": "English", "ru": "Russian"}
_LEN_LABEL = {"concise": "concise", "detailed": "detailed and thorough"}

_CUSTOM_INSTRUCTIONS_MAX = 2000

# Prompt-injection patterns stripped from free text before it enters a prompt.
# This is defense-in-depth, not a guarantee: inputs come from authenticated firm
# staff, and the profile block is placed in a clearly-delimited, non-instruction
# section of the system prompt.
_INJECTION_PATTERNS = [
    r"ignore\s+(?:[\w-]+\s+){0,5}?(?:instructions|prompts|rules)",
    r"disregard\s+(?:[\w-]+\s+){0,5}?(?:instructions|prompts|rules)",
    r"forget\s+(?:everything|all|previous|your instructions)",
    r"system\s+prompt",
    r"you\s+are\s+now",
    r"act\s+as\b",
    r"pretend\s+(?:to\s+be|you)",
    r"jailbreak",
    r"developer\s+mode",
    r"new\s+instructions",
    r"</?(?:system|assistant|user)>",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def fold_diacritics(text: str) -> str:
    """Strip Romanian (and other) diacritics for tolerant matching. Users often
    type Romanian without diacritics; comparisons must treat them the same."""
    if not text:
        return ""
    # Normalise specific Romanian comma-below letters first, then NFKD-fold.
    text = text.translate(str.maketrans({
        "ș": "s", "ş": "s", "Ș": "S", "Ş": "S",
        "ț": "t", "ţ": "t", "Ț": "T", "Ţ": "T",
        "ă": "a", "Ă": "A", "â": "a", "Â": "A", "î": "i", "Î": "I",
    }))
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def sanitize_text(text: str, max_len: int = _CUSTOM_INSTRUCTIONS_MAX) -> str:
    """Neutralise prompt-injection phrases and enforce a length cap on free text
    that will be injected into a prompt."""
    if not text:
        return ""
    cleaned = _INJECTION_RE.sub("[removed]", text)
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip() + "..."
    return cleaned


# ── Read / write ──────────────────────────────────────────────────────────────

def get_or_create_profile(db: Session, user_id: int) -> UserProfile:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).one_or_none()
    if profile is None:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def update_profile(db: Session, user_id: int, *,
                   preferred_tone: str | None = None,
                   preferred_language: str | None = None,
                   response_length: str | None = None,
                   custom_instructions: str | None = None,
                   frequent_topics: list[str] | None = None) -> UserProfile:
    profile = get_or_create_profile(db, user_id)
    if preferred_tone is not None and preferred_tone in TONES:
        profile.preferred_tone = preferred_tone
    if preferred_language is not None and preferred_language in LANGUAGES:
        profile.preferred_language = preferred_language
    if response_length is not None and response_length in LENGTHS:
        profile.response_length = response_length
    if custom_instructions is not None:
        profile.custom_instructions = sanitize_text(custom_instructions)
    if frequent_topics is not None:
        # Sanitize each topic label and cap the list to 12 entries.
        cleaned = [sanitize_text(t, max_len=60) for t in frequent_topics if t and t.strip()]
        profile.frequent_topics = cleaned[:12]
    db.commit()
    db.refresh(profile)
    return profile


# ── Resolver: the injected system-prompt block ────────────────────────────────

def build_profile_block(profile: UserProfile, summaries: list[str] | None = None) -> str:
    """Render the user-preferences section appended to the base system prompt.

    Everything here is clearly framed as preferences/context, never as
    overriding instructions. Free text is sanitized before it reaches this point.
    """
    tone = _TONE_LABEL.get(profile.preferred_tone, "formal")
    lang = _LANG_LABEL.get(profile.preferred_language, "Romanian")
    length = _LEN_LABEL.get(profile.response_length, "detailed and thorough")

    lines = [
        "## User preferences (apply these to your response style)",
        f"- Preferred tone: {tone}.",
        f"- Preferred response language: {lang} (still follow the language rules in the base prompt if the user writes in another language).",
        f"- Preferred response length: {length}.",
    ]
    if profile.frequent_topics:
        topics = ", ".join(str(t) for t in profile.frequent_topics[:8])
        lines.append(f"- Topics this user works with often: {topics}.")

    ci = sanitize_text(profile.custom_instructions or "")
    if ci:
        lines.append("")
        lines.append("## User custom instructions (preferences provided by the user)")
        lines.append(ci)

    if summaries:
        lines.append("")
        lines.append("## Context from earlier sessions (for continuity)")
        for s in summaries[:3]:
            s = sanitize_text(s, max_len=1500)
            if s:
                lines.append(f"- {s}")

    return "\n".join(lines)
