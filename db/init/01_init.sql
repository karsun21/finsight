-- Runs once, on first `docker compose up`, against an empty data volume.
-- Table DDL lives in SQLAlchemy (app/models.py) — this file only sets up what
-- the ORM cannot: the extension itself.

CREATE EXTENSION IF NOT EXISTS vector;
