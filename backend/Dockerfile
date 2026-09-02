FROM python:3.12-slim

# camelot-py needs ghostscript for its table-extraction backend; pdfplumber does not.
# Keep this layer above the dependency install so it caches.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ghostscript \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY pyproject.toml ./
# The [dev] extras (pytest et al) are installed deliberately: this image is the
# only place tests run — the host has neither pytest nor a new enough Python —
# and `docker compose exec api pytest` is the documented command. Installing
# just `-e .` left pytest out of the image entirely, so the suite only ran in
# containers where someone had pip-installed it by hand, and vanished the moment
# a container was recreated. A production build would target a stage without them.
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
