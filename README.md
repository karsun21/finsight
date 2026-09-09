# FinSight

[![tests](https://github.com/karsun21/finsight/actions/workflows/tests.yml/badge.svg)](https://github.com/karsun21/finsight/actions/workflows/tests.yml)

Personal finance RAG assistant. Ingests credit card statement exports,
normalizes them into one schema, and answers natural-language questions about
spending — running entirely on your own machine except for the one API call that
phrases the answer.

Net worth is modelled in the schema and served by `/net-worth` and `/allocation`,
but no holdings are entered yet, so both return zero. See Status.

Transaction ingestion is automated for **Capital One** CSV exports. Investment
balances are entered as hand-typed quarterly snapshots rather than parsed —
those export formats are the most
expensive to support and the balances move slowly enough that automation doesn't
pay for itself. Reasoning in
[`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md) §1.1.

How it all works, from scratch (start here): [`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md).

## Status

Running on real data — three months of credit card transactions ingested and
categorized end to end.

| Piece | State |
|---|---|
| Postgres + pgvector via Docker Compose | ✅ |
| Schema (`institutions`, `transactions`, `holdings`, `ingestion_log`) | ✅ |
| Ingestion pipeline: scan → parse → dedup → classify → embed → insert | ✅ on real data |
| Capital One CSV parser | ✅ with tests |
| Dedup — content-hash file skip, plus within-file identical charges | ✅ with tests |
| Rule-based categorizer, 18-bucket taxonomy | ✅ with tests |
| REST endpoints (`/transactions`, `/holdings`, `/net-worth`, `/allocation`, `/ingestion-log`) | ✅ |
| RAG chat (`/chat`) with aggregate-vs-semantic routing | ✅ both routes verified against real data |
| Chat UI at `/` — single HTML file served by the API | ✅ |
| Alembic migrations, applied on container start | ✅ |
| CI — migrations from empty, drift check, tests | ✅ |
| Manual holdings entry (the other half of net worth) | ⬜ not started |
| Parsers for other account types, all PDF parsers | ⬜ descoped, see §1.1 |
| Scheduled jobs, React dashboard | ⬜ not planned |

## Quick start

```bash
cp .env.example .env          # then set ANTHROPIC_API_KEY
docker compose up --build     # first build pulls torch — expect ~10 min and ~3 GB
curl localhost:8000/health
```

Then open **http://localhost:8000** for the chat UI, or
**http://localhost:8000/docs** for the interactive API reference FastAPI
generates from the route signatures.

Drop statement exports into `inbox/<institution>/` and trigger a run:

```bash
curl -sS -X POST localhost:8000/ingest
curl -sS localhost:8000/ingestion-log
```

Ask a question:

```bash
curl -sS -X POST localhost:8000/chat -H 'content-type: application/json' -d '{"question": "How much did I spend on dining?"}'
```

## Try it without any real data

`demo/` holds 50 synthetic transactions across three statement exports — invented
amounts and dates, real merchant brands so the categorization rules have something
to match.

```bash
cp demo/capital_one/demo_*.csv inbox/capital_one/
curl -sS -X POST localhost:8000/ingest
```

`files_seen: 3, files_ingested: 3, rows_ingested: 50`, and zero uncategorized
rows. What that data then shows — a real transcript, not an illustration:

**Aggregate route.** The number is computed in SQL; the model only phrases it.

> **How much did I spend on dining?** — `aggregate · 22 facts from SQL`
>
> You spent $143.75 on dining across 9 transactions.

**The partial-month guard.** Statement cycles run mid-month to mid-month, so the
first and last calendar months are fractions. A naive reading calls July a
collapse in spending; it is eleven days long.

> **How has my spending changed month to month?** — `aggregate · 22 facts from SQL`
>
> May was your biggest spending month at $981.54, dropping to $407.01 in June — a
> decrease of about $574.53.
>
> April ($344.35) and July ($133.02) can't be fairly compared since both are
> partial months in your data (April starts 04-11, July ends 07-11), so those
> totals don't reflect full-month spending.

**Semantic route, and an honest non-answer.** Two merchants in the demo data
contain the word "storage" — one is housing, one is a subscription.

> **What was that charge from the storage place?** — `semantic · top 20 rows by similarity`
>
> There are two "storage" charges in your data — which one did you mean?
>
> - **Public Storage**: $53.31 (most recent on June 25)
> - **Google One Storage**: $2.99 (most recent on June 21)

See [`demo/README.md`](demo/README.md) for what else the dataset is built to
demonstrate, and how to clear it again.

## Tests

Run them in the container — the host Python is not guaranteed to match:

```bash
docker compose exec api pip install pytest && docker compose exec api pytest -q
```

Tests run on synthetic fixtures in `backend/tests/fixtures/` — no real financial
data is needed, or committed. Where a test names a real merchant brand (because
that is what the pattern has to match), store numbers, cities, and reference
codes are genericized.

## Layout

```
backend/app/
  api/routes/       FastAPI endpoints
  ingestion/        pipeline, dedup, registry
  ingestion/parsers/  currently just Capital One; see docs/HOW-IT-WORKS.md §1.1
  classification/   rule-based categorizer — the taxonomy is the product
  rag/              embeddings, retrieval, query router, Claude call
  static/           the chat UI, one self-contained HTML file served at /
backend/alembic/    migrations — one file per schema change, in order
.github/workflows/  CI: migrations from empty, drift check, tests
db/init/            pgvector extension setup (runs once on first `up`)
inbox/              drop zone, one folder per institution — gitignored
demo/               50 synthetic transactions, safe to commit and to run
docs/               architecture, data source validation, project state
```

## How it fits together

Ingestion is **folder-driven**: dropping a file into `inbox/capital_one/` is what
declares its institution, so parser dispatch only has to detect the *format*.
`app/ingestion/registry.py` maps folder + extension to a parser class.

Dedup works at two levels, because both failures are real. **Files** are skipped
by a hash of their *contents*, not their name — Capital One names every export
`transactions.csv`, so a name-based check silently swallows every month after the
first. **Rows** are fingerprinted on normalized `(institution, date, amount,
description)`, with case, whitespace, and trailing reference numbers stripped, so
the overlapping windows of successive 90-day exports don't double-count. Two
genuinely identical charges on one day are kept distinct by an occurrence index
computed per file, which is what keeps re-ingestion idempotent.
`tests/test_dedup_and_routing.py` pins all of it.

Chat routes before it retrieves. "What's my net worth" needs *every* holding row,
and top-k vector search will answer it confidently and wrongly — so
`rag/router.py` sends aggregate-shaped questions to SQL rollups and only
lookup-shaped questions to pgvector. The LLM never does arithmetic; on the
aggregate path it only phrases numbers Postgres already computed.

## Requirements

Docker is the only hard requirement — the API image pins its own Python 3.12, so
whatever is on your host is irrelevant. `docker-compose.yml` deliberately sticks
to `version: "3.8"` syntax so it runs on Compose v2.2 and later.

The Phase 3 React frontend will need Node 18+ when it exists. Nothing else does.

Everything runs in containers, so the host toolchain does not matter beyond
Docker itself.

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

1. Tests for `aggregate_facts()`. Every test in the suite is pure-unit and there
   is no database fixture, which is how a monthly rollup that netted card
   payments into spending — and therefore reported a fall as a rise — survived
   from the day it was written.
2. Signal truncation on the semantic retrieval path, so the LLM can't sum 20 of
   30 relevant rows and sound certain about it.
3. Spend-by-category-per-month, which the model asks for unprompted whenever it
   is asked what drove a change.
4. Manual holdings entry, so net worth becomes a complete number.

Design decisions and the reasoning behind the scope are in
[`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md) §1.1 and §7.
