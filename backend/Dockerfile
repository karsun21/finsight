FROM python:3.12-slim

# camelot-py needs ghostscript for its table-extraction backend; pdfplumber does not.
# Keep this layer above the dependency install so it caches.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ghostscript \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
