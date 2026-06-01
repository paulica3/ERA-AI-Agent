FROM python:3.12-slim

# LibreOffice (Impress) renders PPTX/DOCX → PDF. Fonts cover metric-compatible
# substitutes (Carlito≈Calibri, Liberation≈Arial/Times) plus broad Unicode so
# Romanian diacritics render correctly in exported PDFs.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-impress \
        libreoffice-writer \
        fonts-liberation \
        fonts-dejavu \
        fonts-crosextra-carlito \
        fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8080
EXPOSE 8080

# Two workers keeps memory in check alongside LibreOffice subprocesses.
CMD ["sh", "-c", "gunicorn -w 2 -k uvicorn.workers.UvicornWorker --timeout 180 --bind 0.0.0.0:${PORT:-8080} api:app"]
