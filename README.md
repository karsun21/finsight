# FinSight

Personal finance RAG assistant. Ingests statement exports from five financial
institutions (DCU, Capital One, Vanguard, Fidelity NetBenefits, Morgan Stanley),
normalizes them into one schema, and answers natural-language questions about net
worth, spending, and investments.

Design plan: `FinSight-Design-Plan.md`.
Data source validation (read this before writing a parser): [`docs/DATA-SOURCES.md`](docs/DATA-SOURCES.md).

## Status

Scaffold. What works end to end today:

| Piece | State |
|---|---|
| Postgres + pgvector via Docker Compose | ✅ |
| Schema (`institutions`, `transactions`, `holdings`, `ingestion_log`) | ✅ |
| Ingestion pipeline: scan → parse → dedup → classify → embed → insert | ✅ |
| Capital One CSV parser | ✅ with tests |
| DCU / Vanguard / Fidelity / Morgan Stanley parsers | 🚧 stubs with format notes |
| REST endpoints (`/transactions`, `/holdings`, `/net-worth`, `/allocation`, `/ingestion-log`) | ✅ |
| RAG chat (`/chat`) with aggregate-vs-semantic routing | ✅ untested against real data |
| Rule-based categorizer | ✅ (scikit-learn model is Phase 2) |
| Scheduled jobs, React frontend | ⬜ not started |

## Quick start

```bash
cp .env.example .env          # then set ANTHROPIC_API_KEY
docker compose up --build     # first build pulls torch — expect ~10 min and ~3 GB
curl localhost:8000/health
open http://localhost:8000/docs
```

Drop statement exports into `inbox/<institution>/` and trigger a run:

```bash
curl -X POST localhost:8000/ingest
curl localhost:8000/ingestion-log
```

Ask a question:

```bash
curl -X POST localhost:8000/chat -H 'content-type: application/json' \
  -d '{"question": "How much did I spend on dining last month?"}'
```

## Tests

```bash
cd backend && pip install -e '.[dev]' && pytest
```

The parser tests run on synthetic fixtures in `backend/tests/fixtures/` — no real
financial data is needed, or committed.

## Layout

```
backend/app/
  api/routes/       FastAPI endpoints
  ingestion/        pipeline, dedup, registry
  ingestion/parsers/  one module per institution
  classification/   rule-based categorizer
  rag/              embeddings, retrieval, query router, Claude call
db/init/            pgvector extension setup (runs once on first `up`)
inbox/              drop zone, one folder per institution — gitignored
docs/               data source validation
```

## How it fits together

Ingestion is **folder-driven**: dropping a file into `inbox/vanguard/` is what
declares its institution, so parser dispatch only has to detect the *format*.
`app/ingestion/registry.py` maps folder + extension to a parser class.

Dedup is what makes the CSV-recent / PDF-backfill strategy safe. The same
transaction arrives twice in two renderings, so `dedup.py` normalizes case,
whitespace, and trailing reference numbers before hashing
`(institution, date, amount, description)`. The hash has a unique constraint, so
re-dropping a statement is a no-op. `tests/test_dedup_and_routing.py` pins this.

Chat routes before it retrieves. "What's my net worth" needs *every* holding row,
and top-k vector search will answer it confidently and wrongly — so
`rag/router.py` sends aggregate-shaped questions to SQL rollups and only
lookup-shaped questions to pgvector. The LLM never does arithmetic; on the
aggregate path it only phrases numbers Postgres already computed.

## Environment notes

Checked on this machine, 2026-08-06 — three things need attention before the
corresponding phase:

- **Python is 3.10.9; the project targets 3.12.** The Docker image pins 3.12, so
  containers are fine. For local `pytest` and editor tooling, install 3.12
  (`brew install python@3.12`, or pyenv).
- **Node is v16.15.0.** Vite 5+ requires Node 18+, so the Phase 3 React frontend
  will not scaffold until Node is upgraded. Not blocking Phases 1–2.
- **Docker is 20.10.12 / Compose v2.2.3** (2021 vintage). `docker-compose.yml`
  sticks to `version: "3.8"` syntax for that reason. Upgrading Docker Desktop is
  worth doing but not required.

## Security

- `.env` is gitignored; `.gitignore` also blocks `*.pdf`, `*.csv`, `*.xlsx`,
  `*.qfx`, and everything under `inbox/`, so statements cannot be committed by
  accident. The one exception is `backend/tests/fixtures/`, which holds synthetic
  rows only.
- `inbox/` is mounted **read-only** into the API container — the pipeline reads
  your statements and never rewrites them.
- Use a dedicated Anthropic API key with a spend limit set in the console, not
  your Claude Pro login.
- Postgres binds to host port **5433** by default to avoid colliding with a local
  Postgres on 5432.

## Next steps

1. Export one month from DCU and Capital One; confirm the real CSV headers.
2. Implement `DCUCSVParser` against that export; `CapitalOneCSVParser` should
   already work — verify with `POST /ingest`.
3. Ask `/chat` a few real questions; tune `rag/router.py` where it misroutes.
4. Phase 2: Vanguard multi-section CSV, then the rest of the investment parsers.
