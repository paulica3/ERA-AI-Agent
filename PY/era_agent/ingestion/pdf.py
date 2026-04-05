"""PDF text extraction using PyPDF2."""

from PyPDF2 import PdfReader


def extract_text(file_path: str) -> str:
    reader = PdfReader(file_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages).strip()
