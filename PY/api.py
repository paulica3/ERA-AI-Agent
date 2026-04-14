"""ERA AI Agent — FastAPI web server."""

import os
import tempfile
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from era_agent.config import ANTHROPIC_API_KEY
from era_agent.ingestion.pdf import extract_text as pdf_extract
from era_agent.ingestion.docx import extract_text as docx_extract
from era_agent.pipelines.analysis import summarize, extract_clauses

app = FastAPI(title="ERA AI Agent API", version="1.0.0")

# Allow the C# frontend to call this API from a different port/domain
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Simple check — is the server running and is the API key set?"""
    return {
        "status": "ok",
        "api_key_configured": bool(ANTHROPIC_API_KEY),
    }


@app.post("/analyze")
async def analyze_document(file: UploadFile = File(...)):
    """
    Upload a PDF or DOCX file and get back a structured legal analysis.
    Returns: summary, key points, and important clauses/risks.
    """
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()

    if ext not in (".pdf", ".docx"):
        raise HTTPException(
            status_code=400,
            detail="Format neacceptat. Încărcați un fișier PDF sau DOCX."
        )

    # Save the uploaded file to a temporary location on disk so we can read it
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Extract raw text from the file
        if ext == ".pdf":
            text = pdf_extract(tmp_path)
        else:
            text = docx_extract(tmp_path)

        if not text.strip():
            raise HTTPException(
                status_code=422,
                detail="Nu s-a putut extrage text din document."
            )

        # Send to Claude for analysis
        summary = summarize(text)
        clauses = extract_clauses(text)

        return {
            "filename": filename,
            "characters_extracted": len(text),
            "summary": summary,
            "clauses": clauses,
        }

    finally:
        # Always clean up the temp file, even if something went wrong
        os.unlink(tmp_path)
