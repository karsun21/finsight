# FinSight — Personal Finance RAG Assistant
### Design & Build Plan

**Owner:** Karthik Sundar
**Purpose:** Unified backend + RAG chatbot that ingests statements from 5 financial institutions (DCU, Capital One, Vanguard, Fidelity NetBenefits, Morgan Stanley StockPlan Connect), normalizes them into one schema, and answers natural-language questions about net worth, spending, and investments.

---

## 1. Goals

- Ingest PDF/CSV exports from 5 institutions (banking, credit, brokerage, 401k, ESPP)
- Normalize into two core schemas: **transactions** (banking/credit) and **holdings/positions** (investments)
- Auto-categorize transactions (subscriptions, dining, transfers, etc.)
- Embed everything for semantic retrieval (RAG)
- Expose a chat API to ask free-form questions ("net worth right now", "employer stock concentration", "dining spend this quarter vs last")
- Run entirely local/self-hosted, minimal recurring cost (~$2-5/month in LLM API calls, everything else free)

---

## 2. Data Sources & Ingestion Format

| Source | Account type | Export format | Notes |
|---|---|---|---|
| DCU | Checking/Savings | PDF eStatement | No native CSV — must parse PDF tables |
| Capital One | Credit card | CSV (native, 90-day limit) + PDF (7-yr archive) | Use CSV for recent, PDF for backfill |
| Vanguard | Brokerage | CSV (native, 18-month limit) + PDF | CSV for recent, PDF for backfill |
| Fidelity NetBenefits | 401k | CSV or PDF | CSV occasionally drops rows — prefer PDF as source of truth |
| Morgan Stanley StockPlan Connect | ESPP | CSV/Excel "Releases Report" + PDF | No holdings/gains export natively — check if migrated to E*TRADE (cleaner CSVs) |

**Ingestion model:** Manual monthly drop into a watched local folder (`/inbox`), organized by institution subfolder. A file-watcher or CLI command triggers the pipeline. Stretch goal (v2): email-forwarding ingestion (forward e-statements to a dedicated inbox, pull via Gmail API).

---

## 3. Architecture Overview

```
[Manual PDF/CSV drop into /inbox/{institution}/]
              │
      [Ingestion Service]
    (format detection → parser dispatch)
              │
      ┌───────┴────────┐
   CSV Parser       PDF Parser
  (pandas)      (pdfplumber/camelot)
      └───────┬────────┘
              │
      [Normalization Layer]
   (maps to unified schema, dedup by txn hash)
              │
      [Classification Service]
  (scikit-learn model, rule-based fallback)
              │
      [PostgreSQL + pgvector]
  (structured tables + embeddings in one DB)
              │
      ┌───────┴────────┐
  [FastAPI Backend]   [Scheduled Jobs]
  - REST API           - weekly summary
  - RAG chat endpoint   - anomaly detection
      │
  [React + TypeScript Frontend]
  - Dashboard (net worth, allocation, spend)
  - Chat interface
```

---

## 4. Tech Stack

**Backend**
- Python 3.12
- FastAPI (REST API + chat endpoint)
- Pydantic (schema validation)
- pandas / Polars (CSV parsing & transforms)
- pdfplumber + camelot-py (PDF table extraction)
- scikit-learn (transaction categorization model)
- sentence-transformers (local embeddings, free — e.g. `all-MiniLM-L6-v2`)
- SQLAlchemy (ORM)

**Database**
- PostgreSQL 16
- pgvector extension (stores embeddings alongside structured data — one DB, no separate vector store)

**LLM / RAG**
- Anthropic API (separate API key from Claude Pro subscription — billed per-token)
- Model routing: Haiku for classification/simple lookups, Sonnet for chat answer generation
- Prompt caching enabled for repeated system context (schema description, few-shot examples)

**Scheduling**
- APScheduler (simplest) or Celery + Redis (if you want to demo a real task queue)

**Frontend**
- React + TypeScript
- Recharts (net worth over time, spending by category, asset allocation charts)
- Simple chat UI component

**Infra**
- Docker Compose (Postgres + API + frontend, one command to spin up)
- Runs entirely on local machine — no cloud hosting required
- `.env` for API keys, never committed

**Security**
- Local encryption at rest for Postgres (or full-disk encryption)
- API keys in `.env`, excluded via `.gitignore`
- No real credentials stored anywhere — ingestion is file-based, not login-based

---

## 5. Database Schema (draft)

### `institutions`
| column | type |
|---|---|
| id | serial PK |
| name | text (DCU, Capital One, Vanguard, Fidelity, Morgan Stanley) |
| account_type | text (checking, credit, brokerage, 401k, espp) |

### `transactions`
| column | type |
|---|---|
| id | serial PK |
| institution_id | FK |
| txn_date | date |
| posted_date | date |
| description | text |
| amount | numeric |
| category | text (nullable until classified) |
| is_recurring | boolean |
| source_file | text (audit trail) |
| dedup_hash | text (unique — prevents double-ingestion) |
| embedding | vector(384) |

### `holdings`
| column | type |
|---|---|
| id | serial PK |
| institution_id | FK |
| as_of_date | date |
| ticker | text |
| asset_class | text |
| quantity | numeric |
| cost_basis | numeric |
| market_value | numeric |
| vested | boolean (for ESPP/401k) |
| embedding | vector(384) |

### `ingestion_log`
| column | type |
|---|---|
| id | serial PK |
| file_name | text |
| institution_id | FK |
| status | text (success/failed/partial) |
| rows_ingested | int |
| ingested_at | timestamp |

---

## 6. RAG Design

1. **Embed on ingestion**: every transaction/holding row gets a text representation (e.g. `"2026-03-04 | Capital One | dining | $42.10 | CHIPOTLE MEXICAN GRILL"`) → embedded via local sentence-transformers model → stored in `embedding` column
2. **Query time**: user question gets embedded the same way → pgvector cosine similarity search retrieves top-k relevant rows (k=15-30 depending on question type)
3. **Prompt construction**: retrieved rows + user question → sent to Claude API (Sonnet) with a system prompt instructing it to answer only from provided data and cite specific numbers
4. **For aggregate questions** ("what's my net worth") — bypass pure vector search, run a direct SQL aggregation instead, and optionally pass the result through the LLM just for natural-language phrasing. This avoids retrieval quality issues on questions that need *all* rows, not just similar ones. (Worth designing a simple query router: classify the question as "aggregate" vs "semantic lookup" before deciding SQL-only vs RAG.)

---

## 7. API Endpoints (draft)

| Method | Path | Purpose |
|---|---|---|
| POST | `/ingest` | Trigger ingestion of new files in `/inbox` |
| GET | `/transactions` | List/filter transactions |
| GET | `/holdings` | List/filter holdings |
| GET | `/net-worth` | Aggregate net worth over time |
| GET | `/allocation` | Asset allocation breakdown |
| POST | `/chat` | RAG chat endpoint — question in, answer out |
| GET | `/summary/weekly` | Latest agentic summary report |
| GET | `/ingestion-log` | Ingestion history/audit |

---

## 8. Build Order / Phases

**Phase 1 — MVP (banking + credit only)**
- Docker Compose setup (Postgres + pgvector)
- CSV/PDF parsers for DCU + Capital One
- Normalization + dedup logic
- Basic categorization (rule-based to start, scikit-learn later)
- FastAPI CRUD endpoints
- Simple RAG chat endpoint (Sonnet + local embeddings)

**Phase 2 — Add investments**
- Vanguard, Fidelity, Morgan Stanley parsers
- Holdings schema + ingestion
- Net worth / allocation aggregation endpoints
- Query router (aggregate vs semantic)

**Phase 3 — Frontend**
- React dashboard: net worth chart, spend-by-category, allocation pie chart
- Chat UI

---

## 9. Cost Estimate

| Component | Cost |
|---|---|
| Postgres, FastAPI, React, Docker | $0 |
| Local embeddings (sentence-transformers) | $0 |
| Classification (scikit-learn) | $0 |
| Claude API (chat + weekly summary) | ~$2-5/month, capped via console spend limit |
| Hosting | $0 (runs locally) |

---

## 10. Resume Framing (once built)

*"Built a full-stack personal finance platform normalizing transaction and investment data across 5 financial institutions into a unified schema; implemented a RAG-based natural-language query interface (PostgreSQL/pgvector, local embeddings, Claude API) with cost-optimized model routing."*

Hits: multi-source ETL, data modeling, RAG, ML classification, cost-conscious architecture — all in one coherent, explainable system.
