"""ERA AI Agent — FastAPI web server (deployed on Azure, called by the .NET app)."""

import asyncio
import json as json_module
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from fastapi import BackgroundTasks, FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.responses import Response, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy.orm import Session

from era_agent.config import ANTHROPIC_API_KEY, FIRM_SIGNUP_CODE
from era_agent.ingestion.pdf import extract_text as pdf_extract
from era_agent.ingestion.docx import extract_text as docx_extract
from era_agent.pipelines.analysis import analyze_document as run_analysis
from era_agent.pipelines.drafting import draft_contract as run_drafting
from era_agent.pipelines.invoicing import draft_invoice as run_invoicing
from era_agent.pipelines.offers import generate_custom_offer as run_offer
from era_agent.pipelines.general_description import (
    generate_general_description as run_general_description,
)
from era_agent.export.libreoffice import pptx_to_pdf
from era_agent.chat_settings import load_instructions, save_instructions
from era_agent.content import store as content_store
from era_agent.content.schema import Project
from era_agent.client import get_client
from era_agent.config import MODEL

# Adaptive learning system: DB, auth, profiles, chat
from era_agent.db.database import get_db, init_db
from era_agent.db.models import User, Conversation, Message, AuditLog
from era_agent.auth.security import hash_password, verify_password, create_access_token
from era_agent.auth.deps import get_current_user
from era_agent.profiles.service import get_or_create_profile, update_profile
from era_agent.profiles.analyzer import analyse_preferences
from era_agent.pipelines.chat import run_chat
from era_agent.db.models import PendingSuggestion

app = FastAPI(title="ERA AI Agent — Python API", version="2.0.0")


logger = logging.getLogger(__name__)

CONVERSATION_MAX_DAYS = 30


async def _cleanup_old_conversations() -> None:
    """Delete conversations (and their messages/audit rows via cascade) that
    have not been updated in more than CONVERSATION_MAX_DAYS days.
    Runs immediately on startup, then repeats every 24 hours."""
    while True:
        try:
            from era_agent.db.database import SessionLocal
            db = SessionLocal()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=CONVERSATION_MAX_DAYS)
                deleted = (
                    db.query(Conversation)
                    .filter(Conversation.updated_at < cutoff)
                    .delete(synchronize_session=False)
                )
                db.commit()
                if deleted:
                    logger.info("Pruned %d conversation(s) older than %d days.", deleted, CONVERSATION_MAX_DAYS)
            finally:
                db.close()
        except Exception:
            logger.exception("Conversation cleanup failed.")
        await asyncio.sleep(24 * 60 * 60)


@app.on_event("startup")
def _startup_create_tables():
    # Create any missing tables on boot (idempotent). Works on SQLite + Postgres.
    init_db()


@app.on_event("startup")
async def _startup_schedule_cleanup():
    asyncio.create_task(_cleanup_old_conversations())

# ── Auth ─────────────────────────────────────────────────────────────────────
# The .NET app sends x-era-api-key on every request.
# Set ERA_API_KEY as an environment variable on both App Services.
# If the env var is empty (local dev without auth), all requests are allowed.
ERA_API_KEY = os.getenv("ERA_API_KEY", "")
_api_key_header = APIKeyHeader(name="x-era-api-key", auto_error=False)

async def verify_key(key: str = Depends(_api_key_header)):
    if ERA_API_KEY and key != ERA_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key.")
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/health")
def health():
    """Liveness check — called by Azure and the .NET app on startup."""
    return {
        "status": "ok",
        "anthropic_key_configured": bool(ANTHROPIC_API_KEY),
    }


@app.post("/analyze", dependencies=[Depends(verify_key)])
async def analyze_document(file: UploadFile = File(...)):
    """
    Accept a PDF or DOCX and stream real progress events followed by the result:
      data: {"status": "..."}   — emitted before each real step
      data: {"result": {...}}   — final structured analysis
      data: {"error": "..."}    — on failure
      data: [DONE]
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".pdf", ".docx"):
        raise HTTPException(
            status_code=400,
            detail="Format neacceptat. Încărcați un fișier PDF sau DOCX.",
        )

    # Read file bytes eagerly so the generator doesn't hold an open upload stream
    file_bytes = await file.read()

    def event_stream():
        # ── Step 1: text extraction ───────────────────────────────────
        yield f"data: {json_module.dumps({'status': 'Se extrage textul din document...'})}\n\n"

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            text = pdf_extract(tmp_path) if ext == ".pdf" else docx_extract(tmp_path)
        finally:
            os.unlink(tmp_path)

        if not text.strip():
            yield f"data: {json_module.dumps({'error': 'Nu s-a putut extrage text din document.'})}\n\n"
            yield "data: [DONE]\n\n"
            return

        # ── Step 2: Claude analysis ───────────────────────────────────
        yield f"data: {json_module.dumps({'status': 'Se analizează documentul'})}\n\n"

        try:
            result = run_analysis(text)
            yield f"data: {json_module.dumps({'result': result})}\n\n"
        except Exception as e:
            yield f"data: {json_module.dumps({'error': str(e)})}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class DraftContractRequest(BaseModel):
    client_name: str
    client_type: str = "SRL"
    client_idno: str = ""
    client_address: str = ""
    client_rep: str = ""
    client_rep_role: str = "Administrator"
    scope: str
    services: str = ""
    fees: str = ""
    duration: str = ""
    contract_number: str = ""


class DraftInvoiceRequest(BaseModel):
    date: str
    company_name: str
    legal_address: str = ""
    client_iban: str = ""
    reg_no: str = ""
    vat_no: str = ""
    invoice_number: str = ""
    contract_ref: str = ""
    service_description: str = ""
    legal_fee: str = "0"
    currency: str = "EUR"
    expenses_text: str = ""
    partner_name: str = "Oleg Efrim"
    partner_title: str = "Partner"
    partner_email: str = "oleg.efrim@era.md"


class GenerateOfferRequest(BaseModel):
    client_name: str
    date: str
    addressee_salutation: str
    addressee_block: str = ""
    intro_text: str = ""          # context (composed) or literal paragraphs
    compose_intro: bool = True    # let Claude compose the letter from the context
    fee_text: str = ""
    signatory_name: str = "Oleg EFRIM"
    signatory_title: str = "Managing Partner"
    lang: str = "ro"              # "ro" | "en"
    reformat_fees: bool = True
    format: str = "pptx"          # "pptx" | "pdf"


class GenerateGeneralDescriptionRequest(BaseModel):
    addressee_block: str
    addressee_salutation: str
    date: str = ""
    intro_context: str = ""        # optional matter context for the opening paragraph
    compose_intro: bool = True     # let Claude compose the opening paragraph
    signatory_name: str = "Oleg EFRIM"
    signatory_title: str = "Managing Partner"
    hourly_rate: str = ""          # blank -> template default (EUR 250)
    lang: str = "ro"               # "ro" | "en"
    format: str = "pptx"           # "pptx" | "pdf"


class ProjectsPayload(BaseModel):
    projects: list[dict]


class TranslateRequest(BaseModel):
    text: str
    target: str = "ro"        # "ro" | "en"


class ChatInstructions(BaseModel):
    instructions: str = ""


# ── Adaptive learning request models ──────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""
    invite_code: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None


class ConversationCreateRequest(BaseModel):
    title: str = ""


class ConversationRenameRequest(BaseModel):
    title: str


class ProfileUpdateRequest(BaseModel):
    preferred_tone: str | None = None
    preferred_language: str | None = None
    response_length: str | None = None
    custom_instructions: str | None = None


class SuggestionActionRequest(BaseModel):
    action: str          # "accept" or "dismiss"
    value: object = None  # edited value from the user (for accept)


class MemoryRequest(BaseModel):
    text: str


@app.get("/chat-instructions", dependencies=[Depends(verify_key)])
async def get_chat_instructions():
    """Return the user's saved standing chat instructions."""
    return {"instructions": load_instructions()}


@app.put("/chat-instructions", dependencies=[Depends(verify_key)])
async def put_chat_instructions(body: ChatInstructions):
    """Persist the user's standing chat instructions."""
    saved = save_instructions(body.instructions)
    return {"instructions": saved}


@app.get("/projects", dependencies=[Depends(verify_key)])
async def get_projects():
    """Return the full track-record store (categories + projects)."""
    return content_store.load_db()


@app.put("/projects", dependencies=[Depends(verify_key)])
async def put_projects(body: ProjectsPayload):
    """Replace the whole project list (dashboard bulk save). Each project is
    normalised through the schema (assigns ids/timestamps, validates category)."""
    try:
        normalised = [Project.from_dict(p).to_dict() for p in body.projects]
        saved = content_store.replace_projects(normalised)
        return saved
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Date invalide: {str(e)}")


@app.post("/translate", dependencies=[Depends(verify_key)])
async def translate(body: TranslateRequest):
    """Translate a single field EN<->RO for the dashboard's translate button."""
    text = (body.text or "").strip()
    if not text:
        return {"translation": ""}
    target_name = "Romanian" if body.target == "ro" else "English"
    system = (
        "You are a professional legal translator for the Moldovan law firm "
        f"Efrim, Roșca & Asociații. Translate the text into {target_name}, in a "
        "formal legal register with correct diacritics. Keep personal names, the "
        "firm name, company/brand names, emails, phone numbers, law/decision "
        "numbers, dates and monetary amounts unchanged; translate public "
        "institutions to their official name in the target language. Return ONLY "
        "the translation, with no quotes or extra text."
    )
    try:
        resp = get_client().messages.create(
            model=MODEL, max_tokens=2048, system=system,
            messages=[{"role": "user", "content": text}],
        )
        out = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        return {"translation": out}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la traducere: {str(e)}")


@app.post("/generate-custom-offer", dependencies=[Depends(verify_key)])
async def generate_custom_offer_endpoint(req: GenerateOfferRequest):
    """Fill ERA's Custom Offer deck and return a PPTX (or PDF via LibreOffice)."""
    try:
        pptx_bytes = run_offer(
            client_name=req.client_name,
            date=req.date,
            addressee_salutation=req.addressee_salutation,
            addressee_block=req.addressee_block,
            intro_text=req.intro_text,
            compose_intro=req.compose_intro,
            fee_text=req.fee_text,
            signatory_name=req.signatory_name,
            signatory_title=req.signatory_title,
            lang=req.lang,
            reformat_fees=req.reformat_fees,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la generarea ofertei: {str(e)}")

    safe_name = req.client_name.replace(" ", "_").replace("/", "_")[:30] or "Oferta"

    if req.format == "pdf":
        try:
            pdf_bytes = pptx_to_pdf(pptx_bytes)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Eroare la conversia în PDF: {str(e)}")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="Oferta_{safe_name}.pdf"'},
        )

    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": f'attachment; filename="Oferta_{safe_name}.pptx"'},
    )


@app.post("/generate-general-description", dependencies=[Depends(verify_key)])
async def generate_general_description_endpoint(req: GenerateGeneralDescriptionRequest):
    """Fill ERA's General Description deck and return a PPTX (or PDF via LibreOffice)."""
    try:
        pptx_bytes = run_general_description(
            addressee_block=req.addressee_block,
            addressee_salutation=req.addressee_salutation,
            date=req.date,
            intro_context=req.intro_context,
            compose_intro=req.compose_intro,
            signatory_name=req.signatory_name,
            signatory_title=req.signatory_title,
            hourly_rate=req.hourly_rate,
            lang=req.lang,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la generarea prezentării: {str(e)}")

    if req.format == "pdf":
        try:
            pdf_bytes = pptx_to_pdf(pptx_bytes)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Eroare la conversia în PDF: {str(e)}")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="Prezentare_ERA.pdf"'},
        )

    return Response(
        content=pptx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={"Content-Disposition": 'attachment; filename="Prezentare_ERA.pptx"'},
    )


@app.post("/draft-invoice", dependencies=[Depends(verify_key)])
async def draft_invoice_endpoint(req: DraftInvoiceRequest):
    """Fill ERA's invoice template and return a DOCX."""
    try:
        docx_bytes = run_invoicing(
            date=req.date,
            company_name=req.company_name,
            legal_address=req.legal_address,
            client_iban=req.client_iban,
            reg_no=req.reg_no,
            vat_no=req.vat_no,
            invoice_number=req.invoice_number,
            contract_ref=req.contract_ref,
            service_description=req.service_description,
            legal_fee=req.legal_fee,
            currency=req.currency,
            expenses_text=req.expenses_text,
            partner_name=req.partner_name,
            partner_title=req.partner_title,
            partner_email=req.partner_email,
        )
        safe_name = req.company_name.replace(" ", "_").replace("/", "_")[:30]
        filename = f"Invoice_{safe_name}.docx"
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la redactarea facturii: {str(e)}")


@app.post("/draft-contract", dependencies=[Depends(verify_key)])
async def draft_contract_endpoint(req: DraftContractRequest):
    """
    Fill ERA's contract template with client-specific data and return a DOCX.
    """
    try:
        docx_bytes = run_drafting(
            client_name=req.client_name,
            client_type=req.client_type,
            client_idno=req.client_idno,
            client_address=req.client_address,
            client_rep=req.client_rep,
            client_rep_role=req.client_rep_role,
            scope=req.scope,
            services=req.services,
            fees=req.fees,
            duration=req.duration,
            contract_number=req.contract_number,
        )
        safe_name = req.client_name.replace(" ", "_").replace("/", "_")[:30]
        filename = f"Contract_{safe_name}.docx"
        return Response(
            content=docx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la redactarea contractului: {str(e)}")


# ══════════════════════════════════════════════════════════════════════════════
# Adaptive learning system: auth, chat, conversations, profile, account
#
# Two auth schemes coexist:
#   - /auth/*  require x-era-api-key (proves the caller is our .NET frontend);
#     register additionally requires the firm invite code.
#   - All user-facing endpoints below require the JWT (Authorization: Bearer),
#     resolved by get_current_user. user_id always comes from the verified token.
# ══════════════════════════════════════════════════════════════════════════════


def _profile_dict(profile) -> dict:
    return {
        "preferred_tone": profile.preferred_tone,
        "preferred_language": profile.preferred_language,
        "response_length": profile.response_length,
        "frequent_topics": profile.frequent_topics or [],
        "custom_instructions": profile.custom_instructions or "",
        "interaction_count": profile.interaction_count or 0,
        "last_updated": profile.last_updated.isoformat() if profile.last_updated else None,
    }


def _conversation_dict(conv, include_messages: bool = False) -> dict:
    data = {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }
    if include_messages:
        data["messages"] = [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in conv.messages
        ]
    return data


# ── Auth ───────────────────────────────────────────────────────────────────────

@app.post("/auth/register", dependencies=[Depends(verify_key)])
async def auth_register(body: RegisterRequest, db: Session = Depends(get_db)):
    """Self-registration gated by the firm invite code. Closed to outsiders."""
    if FIRM_SIGNUP_CODE and body.invite_code != FIRM_SIGNUP_CODE:
        raise HTTPException(status_code=403, detail="Cod de invitație invalid.")

    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Adresă de e-mail invalidă.")
    if not body.password or len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Parola trebuie să aibă cel puțin 8 caractere.")

    existing = db.query(User).filter(User.email == email).one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Există deja un cont cu acest e-mail.")

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        display_name=(body.display_name or "").strip(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Create the default profile up front.
    get_or_create_profile(db, user.id)

    token = create_access_token(user.id)
    return {"access_token": token, "display_name": user.display_name, "email": user.email}


@app.post("/auth/login", dependencies=[Depends(verify_key)])
async def auth_login(body: LoginRequest, db: Session = Depends(get_db)):
    email = (body.email or "").strip().lower()
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-mail sau parolă incorecte.")
    token = create_access_token(user.id)
    return {"access_token": token, "display_name": user.display_name, "email": user.email}


# ── Chat ─────────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(
    body: ChatRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Single server-side chat turn. Loads the profile, injects it, persists
    messages, writes the audit snapshot. Returns {reply, conversation_id, title}."""
    try:
        result = run_chat(db, user, body.message, body.conversation_id)
    except PermissionError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Eroare la generarea răspunsului: {str(e)}")

    # Every 10 turns, run preference analysis in the background.
    profile = get_or_create_profile(db, user.id)
    if profile.interaction_count > 0 and profile.interaction_count % 5 == 0:
        background_tasks.add_task(analyse_preferences, user.id)

    return result


# ── Conversations (ownership-scoped) ──────────────────────────────────────────

@app.get("/conversations")
async def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    convs = (
        db.query(Conversation)
        .filter(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return {"conversations": [_conversation_dict(c) for c in convs]}


@app.post("/conversations")
async def create_conversation(
    body: ConversationCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = Conversation(user_id=user.id, title=(body.title or "").strip() or "Conversație nouă")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return _conversation_dict(conv)


@app.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversația nu există.")
    return _conversation_dict(conv, include_messages=True)


@app.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: int,
    body: ConversationRenameRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversația nu există.")
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Titlu gol.")
    conv.title = title[:255]
    db.commit()
    db.refresh(conv)
    return _conversation_dict(conv)


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Conversația nu există.")
    db.delete(conv)
    db.commit()
    return {"deleted": conversation_id}


# ── Profile ──────────────────────────────────────────────────────────────────

@app.get("/profile")
async def get_profile(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = get_or_create_profile(db, user.id)
    return {
        "email": user.email,
        "display_name": user.display_name,
        **_profile_dict(profile),
    }


@app.put("/profile")
async def put_profile(
    body: ProfileUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = update_profile(
        db, user.id,
        preferred_tone=body.preferred_tone,
        preferred_language=body.preferred_language,
        response_length=body.response_length,
        custom_instructions=body.custom_instructions,
    )
    return {
        "email": user.email,
        "display_name": user.display_name,
        **_profile_dict(profile),
    }


# ── Account (GDPR) ────────────────────────────────────────────────────────────

@app.delete("/account")
async def delete_account(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GDPR wipe: delete the user and all of their data. Cascade removes the
    profile, conversations, messages, and audit rows."""
    # Audit rows reference user_id directly (no relationship cascade), wipe first.
    db.query(AuditLog).filter(AuditLog.user_id == user.id).delete(synchronize_session=False)
    db.delete(user)  # cascades to profile, conversations, messages, pending_suggestions
    db.commit()
    return {"deleted": True}


# ── /memory command ───────────────────────────────────────────────────────────

@app.post("/memory")
async def save_memory(
    body: MemoryRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pass user's free-form text through Claude to extract compact rules,
    then append those rules to their custom_instructions."""
    raw = body.text.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Textul nu poate fi gol.")

    extraction_prompt = (
        "The user wants to save personal preferences or rules for an AI legal assistant. "
        "Read their note and extract ONLY the concrete, actionable rules it implies. "
        "Return them as a short bulleted list (one rule per line, starting with '- '). "
        "Be concise — each rule should be one sentence. "
        "Do NOT add anything else, no introduction, no explanation.\n\n"
        f"User's note:\n{raw}"
    )
    try:
        client = get_client()
        resp = client.messages.create(
            model=MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": extraction_prompt}],
        )
        extracted = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
    except Exception:
        logger.exception("Memory extraction failed")
        raise HTTPException(status_code=500, detail="Eroare la procesarea memoriei.")

    from era_agent.profiles.service import sanitize_text
    extracted = sanitize_text(extracted, max_len=600)
    if not extracted:
        raise HTTPException(status_code=400, detail="Nu s-au putut extrage reguli din text.")

    profile = get_or_create_profile(db, user.id)
    existing = (profile.custom_instructions or "").strip()
    combined = (existing + "\n" + extracted).strip() if existing else extracted
    if len(combined) > 2000:
        combined = combined[:2000].rstrip() + "..."
    profile.custom_instructions = combined
    db.commit()
    return {"saved": True, "rules": extracted}


# ── Suggestions (Phase 2) ──────────────────────────────────────────────────────

def _suggestion_dict(s: PendingSuggestion) -> dict:
    return {
        "id": s.id,
        "field": s.field,
        "suggested_value": s.suggested_value,
        "rationale": s.rationale,
        "status": s.status,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@app.get("/suggestions")
async def list_suggestions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return pending suggestions for the current user, newest first."""
    rows = (
        db.query(PendingSuggestion)
        .filter(PendingSuggestion.user_id == user.id, PendingSuggestion.status == "pending")
        .order_by(PendingSuggestion.created_at.desc())
        .all()
    )
    return [_suggestion_dict(s) for s in rows]


@app.patch("/suggestions/{suggestion_id}")
async def act_on_suggestion(
    suggestion_id: int,
    body: SuggestionActionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept or dismiss a suggestion. On accept, the (possibly edited) value is
    written directly to the user's profile."""
    s = db.get(PendingSuggestion, suggestion_id)
    if s is None or s.user_id != user.id:
        raise HTTPException(status_code=404, detail="Sugestia nu există.")
    if body.action not in ("accept", "dismiss"):
        raise HTTPException(status_code=400, detail="action trebuie să fie 'accept' sau 'dismiss'.")

    if body.action == "accept":
        value = body.value if body.value is not None else s.suggested_value
        kwargs: dict = {}
        if s.field == "preferred_tone":
            kwargs["preferred_tone"] = value
        elif s.field == "response_length":
            kwargs["response_length"] = value
        elif s.field == "frequent_topics":
            if isinstance(value, str):
                value = [t.strip() for t in value.split(",") if t.strip()]
            kwargs["frequent_topics"] = value
        elif s.field in ("response_structure", "citation_preference"):
            # Append free-text instruction to custom_instructions.
            from era_agent.profiles.service import sanitize_text
            rule = sanitize_text(str(value).strip(), max_len=300)
            if rule:
                profile = get_or_create_profile(db, user.id)
                existing = (profile.custom_instructions or "").strip()
                combined = (existing + "\n" + rule).strip() if existing else rule
                if len(combined) > 2000:
                    combined = combined[:2000].rstrip() + "..."
                profile.custom_instructions = combined
                db.flush()
        if kwargs:
            update_profile(db, user.id, **kwargs)
        s.status = "accepted"
    else:
        s.status = "dismissed"

    db.commit()
    db.refresh(s)
    return _suggestion_dict(s)
