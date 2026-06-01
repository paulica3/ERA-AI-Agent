"""PPTX/DOCX → PDF conversion via headless LibreOffice.

LibreOffice is the only dependency that renders Office documents to PDF with high
fidelity without a Microsoft stack. It ships in the Python service's Docker image
(see PY/Dockerfile). Locally, conversion works only if LibreOffice is installed;
otherwise a clear RuntimeError is raised and callers can fall back to PPTX.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

# Candidate Windows install locations (used when soffice isn't on PATH).
_WINDOWS_CANDIDATES = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def _find_soffice() -> str:
    """Locate the LibreOffice executable, or raise a clear error."""
    for cmd in ("soffice", "libreoffice"):
        path = shutil.which(cmd)
        if path:
            return path
    for candidate in _WINDOWS_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise RuntimeError(
        "LibreOffice (soffice) not found. PDF export requires LibreOffice — "
        "it is installed in the Docker image; for local PDF export install it "
        "from https://www.libreoffice.org/."
    )


def convert_to_pdf(doc_bytes: bytes, suffix: str = ".pptx", timeout: int = 120) -> bytes:
    """Convert an Office document (given as bytes) to PDF bytes.

    Parameters
    ----------
    doc_bytes : the source document bytes (.pptx or .docx).
    suffix : the source file extension, e.g. ".pptx" or ".docx".
    timeout : seconds before the LibreOffice subprocess is killed.
    """
    soffice = _find_soffice()

    with tempfile.TemporaryDirectory() as work:
        src = Path(work) / f"document{suffix}"
        src.write_bytes(doc_bytes)

        # Use an isolated user profile so concurrent conversions don't clash.
        profile = Path(work) / "profile"
        env_arg = f"-env:UserInstallation={profile.as_uri()}"

        result = subprocess.run(
            [
                soffice,
                "--headless",
                "--norestore",
                "--nolockcheck",
                env_arg,
                "--convert-to",
                "pdf",
                "--outdir",
                str(work),
                str(src),
            ],
            capture_output=True,
            timeout=timeout,
        )
        out = src.with_suffix(".pdf")
        if not out.exists():
            raise RuntimeError(
                "LibreOffice failed to produce a PDF. "
                f"stdout={result.stdout.decode(errors='replace')[:500]} "
                f"stderr={result.stderr.decode(errors='replace')[:500]}"
            )
        return out.read_bytes()


def pptx_to_pdf(pptx_bytes: bytes, timeout: int = 120) -> bytes:
    """Convenience wrapper: convert PPTX bytes to PDF bytes."""
    return convert_to_pdf(pptx_bytes, suffix=".pptx", timeout=timeout)
