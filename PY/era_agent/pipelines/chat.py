"""Server-side chat pipeline.

This is the single place chat talks to Claude. It loads the user's profile,
injects it into the system prompt, persists both messages, writes an audit
snapshot of exactly what context was injected, and keeps the conversation
server-side and scoped to the authenticated user.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from era_agent.client import get_client, SYSTEM_PROMPT, WEB_SEARCH_TOOL
from era_agent.config import MODEL, MAX_TOKENS
from era_agent.db.models import Conversation, Message, AuditLog
from era_agent.profiles.service import get_or_create_profile, build_profile_block


def _title_from(message: str) -> str:
    line = " ".join((message or "").split())
    return (line[:48] + "...") if len(line) > 48 else (line or "Conversație nouă")


def run_chat(db: Session, user, message: str, conversation_id: int | None) -> dict:
    """Handle one chat turn. Returns {reply, conversation_id, title}."""
    message = (message or "").strip()
    if not message:
        raise ValueError("Mesaj gol.")

    # Resolve or create the conversation, enforcing ownership.
    if conversation_id is not None:
        conv = db.get(Conversation, conversation_id)
        if conv is None or conv.user_id != user.id:
            raise PermissionError("Conversația nu există.")
    else:
        conv = Conversation(user_id=user.id, title=_title_from(message))
        db.add(conv)
        db.flush()  # assign conv.id

    # Build the system prompt: base + injected profile block (includes user identity).
    profile = get_or_create_profile(db, user.id)
    profile_block = build_profile_block(
        profile,
        summaries=None,
        display_name=user.display_name or "",
        email=user.email or "",
    )
    system = SYSTEM_PROMPT + "\n\n" + profile_block

    # Prior turns from the DB plus the new user message.
    prior = [{"role": m.role, "content": m.content} for m in conv.messages]
    claude_messages = prior + [{"role": "user", "content": message}]

    # Call Claude with the web search tool (server-side, same as before).
    client = get_client()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=claude_messages,
        tools=[WEB_SEARCH_TOOL],
        extra_headers={"anthropic-beta": "web-search-2025-03-05"},
    )
    reply = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")

    # Persist both messages.
    db.add(Message(conversation_id=conv.id, user_id=user.id, role="user", content=message))
    assistant_msg = Message(
        conversation_id=conv.id, user_id=user.id, role="assistant", content=reply
    )
    db.add(assistant_msg)
    db.flush()  # assign assistant_msg.id

    # Audit: snapshot exactly what profile context was injected for this response.
    db.add(AuditLog(
        user_id=user.id,
        message_id=assistant_msg.id,
        injected_context=profile_block,
    ))

    profile.interaction_count = (profile.interaction_count or 0) + 1
    db.commit()

    return {"reply": reply, "conversation_id": conv.id, "title": conv.title}
