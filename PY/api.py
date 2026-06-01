"""ERA AI Agent — FastAPI web server (deployed on Azure, called by the .NET app)."""

import json as json_module
import os
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.responses import Response, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from era_agent.config import ANTHROPIC_API_KEY
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

app = FastAPI(title="ERA AI Agent — Python API", version="2.0.0")

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


class ChatInstructions(BaseModel):
    instructions: str = ""


@app.get("/chat-instructions", dependencies=[Depends(verify_key)])
async def get_chat_instructions():
    """Return the user's saved standing chat instructions."""
    return {"instructions": load_instructions()}


@app.put("/chat-instructions", dependencies=[Depends(verify_key)])
async def put_chat_instructions(body: ChatInstructions):
    """Persist the user's standing chat instructions."""
    saved = save_instructions(body.instructions)
    return {"instructions": saved}


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
