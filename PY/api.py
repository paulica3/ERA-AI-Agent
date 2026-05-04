"""ERA AI Agent — FastAPI web server (deployed on Azure, called by the .NET app)."""

import os
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException, Depends
from fastapi.security import APIKeyHeader

from era_agent.config import ANTHROPIC_API_KEY
from era_agent.ingestion.pdf import extract_text as pdf_extract
from era_agent.ingestion.docx import extract_text as docx_extract
from era_agent.pipelines.analysis import analyze_document

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

        result = analyze_document(text)

        return {
            "filename": filename,
            "characters_extracted": len(text),
            "summary": result["summary"],
            "clauses": result["clauses"],
        }
    finally:
        os.unlink(tmp_path)
