"""PDF text extraction — handles both text-based and scanned PDFs.

For normal PDFs:  text is extracted directly using PyPDF2 (fast).
For scanned PDFs: each page is rendered as an image and sent to Claude
                  vision, which reads the text visually (accurate, no
                  extra OCR software needed).
"""

import base64

import fitz  # PyMuPDF — renders PDF pages to images
from PyPDF2 import PdfReader

from era_agent.client import get_client
from era_agent.config import MODEL, MAX_TOKENS


def _is_scanned(file_path: str) -> bool:
    """Return True if the PDF contains no extractable text layer."""
    reader = PdfReader(file_path)
    for page in reader.pages:
        if (page.extract_text() or "").strip():
            return False
    return True


def _extract_text_layer(file_path: str) -> str:
    """Fast path: pull text directly from a text-based PDF."""
    reader = PdfReader(file_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()


def _extract_via_vision(file_path: str) -> str:
    """Slow path: render each page as an image and let Claude read it."""
    doc = fitz.open(file_path)
    client = get_client()
    all_text = []

    for page_num, page in enumerate(doc, start=1):
        # Render page at 150 DPI — good quality without oversized images
        matrix = fitz.Matrix(150 / 72, 150 / 72)
        pix = page.get_pixmap(matrix=matrix)
        img_b64 = base64.standard_b64encode(pix.tobytes("png")).decode()

        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Aceasta este pagina {page_num} dintr-un document juridic scanat. "
                            "Transcrie exact tot textul vizibil din imagine, păstrând structura "
                            "și formatarea originală. Nu adăuga comentarii sau explicații — "
                            "doar textul din document."
                        ),
                    },
                ],
            }],
        )
        all_text.append(response.content[0].text)

    doc.close()
    return "\n\n".join(all_text)


def extract_text(file_path: str) -> str:
    """
    Extract text from any PDF automatically:
    - Text-based PDF → extracted directly (instant)
    - Scanned PDF    → Claude reads each page as an image (accurate)
    """
    if _is_scanned(file_path):
        return _extract_via_vision(file_path)
    return _extract_text_layer(file_path)
