"""ERA AI Agent — FastAPI web server (deployed on Azure, called by the .NET app)."""

import os
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.responses import Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from era_agent.config import ANTHROPIC_API_KEY
from era_agent.ingestion.pdf import extract_text as pdf_extract
from era_agent.ingestion.docx import extract_text as docx_extract
from era_agent.pipelines.analysis import analyze_document as run_analysis
from era_agent.pipelines.drafting import draft_contract as run_drafting

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
    Accept a PDF or DOCX, extract its text, run two Claude pipelines
    (summary + clause extraction), and return structured results.
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".pdf", ".docx"):
        raise HTTPException(
            status_code=400,
            detail="Format neacceptat. Încărcați un fișier PDF sau DOCX.",
        )

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        text = pdf_extract(tmp_path) if ext == ".pdf" else docx_extract(tmp_path)

        if not text.strip():
            raise HTTPException(
                status_code=422,
                detail="Nu s-a putut extrage text din document.",
            )

        result = run_analysis(text)

        return {
            "filename": filename,
            "characters_extracted": len(text),
            "summary": result["summary"],
            "clauses": result["clauses"],
        }
    finally:
        os.unlink(tmp_path)


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
