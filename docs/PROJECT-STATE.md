# Project State — 2026-08-06

Handoff notes. Written at the end of the first working session, for whoever (or
whatever) picks this up next. Companion to `docs/HOW-IT-WORKS.md`, which explains
the architecture and the RAG concepts from scratch.

**Owner:** Karthik Sundar
**Repo:** `~/projects/finsight`, branch `master`, no remote
**Phase:** 1 (banking + credit). Scaffold verified end to end on synthetic data;
no real financial data ingested yet.

---

## 1. Scope decision made this session — read this first

The owner explicitly scoped this **down**. It is not meant to be a
fine-grained personal finance analytics platform. The target is:

- **Net worth** across the five institutions
- **Spending at coarse category granularity** — "dining", "travel", "shopping"
- Explicitly **not** fine-grained — no "coffee specifically" vs dining, no
  "subway fare" vs transport

**This decision removes work.** Do not reintroduce the following without being
asked:

| Previously planned | Status after this decision |
|---|---|
| scikit-learn categorizer (design plan Phase 2) | **Dropped.** ~15 regex rules are sufficient for coarse buckets. An ML model earns its place only at fine granularity. |
| Two-stage "semantic filter → SQL aggregate" retrieval | **Dropped.** This existed to answer "how much on coffee" when coffee isn't a category. At coarse granularity every spending question is a `GROUP BY category`, which the aggregate path already handles correctly over all rows. |
| PDF parsers (all five institutions) | **Deprioritized to optional.** They exist for historical backfill beyond the CSV windows. Coarse questions over recent data don't need them. See the Fidelity caveat in §5. |
| Investment in the semantic/vector path | **Demoted, not removed.** It works and it stays — it's genuinely useful for "what was that charge from X?" lookups. Just don't spend more effort tuning it. |

**What the decision makes *more* important:** the category taxonomy. See §4.

---

## 2. What is verified working

Every stage below has actually run, against the synthetic fixture, on this
machine:

- `docker compose up --build` — builds clean, ~6 GB image
- Postgres 16 + pgvector — `/health` returns `pgvector: true`
- Schema auto-creation at startup (`main.py:33`) and institution seeding (`main.py:35`)
- `pytest` — **12 passed** (run inside the container, see §6)
- `POST /ingest` — parsed 4 rows from the Capital One fixture, signs correct
  (debits negative, credits positive)
- **Dedup, both layers, confirmed separately:**
  - Filename-level skip (`pipeline.py:89`) — re-ingesting the same filename does nothing
  - Hash-level dedup (`dedup.py:19`) — a *renamed copy* of the same file parsed
    and reported `rows_duplicate: 4`, inserted nothing
- Local embeddings — model downloaded to the `hfcache` volume, 384-dim vectors stored
- `POST /chat` **semantic route** — vector search returned the right transaction,
  Claude answered correctly
- `POST /chat` **aggregate route** — SQL rollups, Claude correctly excluded the
  card payment from spending totals on its own

The database is currently **empty** — the synthetic rows were deleted after testing.

---

## 3. Bug found and fixed this session

**`rag/retrieval.py`, monthly rollup — 500 on every aggregate question.**

`func.to_char(Transaction.txn_date, "YYYY-MM")` was constructed three separate
times (SELECT, GROUP BY, ORDER BY). SQLAlchemy gives each construction its own
bind parameter, so Postgres saw three syntactically different expressions and
raised:

```
column "transactions.txn_date" must appear in the GROUP BY clause
```

Fixed by building the expression once and reusing the object, so all three render
with the same placeholder. Verified by calling `aggregate_facts()` directly.

---

## 4. Known open issues, in priority order

**1. Capital One's categories bypass the rule categorizer entirely.** *(now the
highest-value fix, given §1)*

`pipeline.py:118` reads `txn.category or categorize(txn.description)`. Capital One
supplies its own merchant category, so the `or` short-circuits and
`classification/rules.py` never runs for card transactions. Observed live:

| Merchant | Got | Should be |
|---|---|---|
| KROGER #421 | `merchandise` | `groceries` |
| NETFLIX.COM | `other services` | `subscriptions` |
| CHIPOTLE | `dining` | `dining` ✓ |

At coarse granularity, **category is the entire product** — every spending
question becomes a `GROUP BY category`. Issuer labels are the wrong vocabulary and
inconsistent across institutions. Suggested fix: run the rules **first**, fall
back to a small mapping of issuer categories onto the project taxonomy, then
`None`. Also add a `travel` bucket (airlines, hotels, Airbnb) — currently missing,
and it's explicitly one of the categories the owner named.

**2. `pipeline.py:89` skips files by filename only.**

Capital One names every export identically, so the second month's file is silently
skipped — `files_seen` increments and nothing else happens. **Current workaround:
date-stamp filenames on drop** (`capital_one_2026-07.csv`). Real fix: hash the file
contents into the check.

**3. `pipeline.py:101` doesn't dedup within a single file.**

Two identical charges on the same day (same merchant, same amount) produce the
same hash, both enter the insert batch, and the unique constraint on `dedup_hash`
rejects the whole commit → uncaught `IntegrityError` → 500 on `/ingest`. The
try/except at `pipeline.py:59` only wraps parsing, not persistence. Likely to
appear with 90 days of real card data.

**4. Semantic path truncates silently.** `retrieval.py` returns exactly
`retrieval_top_k` (20) rows with no signal that more matched. If 30 rows are
relevant, Claude sums 20 and states a confident wrong total. Cheap mitigation:
when the result length equals `k`, tell the LLM the list was truncated so it says
"at least $X across at least 20 purchases." **Lower priority after §1** — coarse
questions route to SQL, not to this path.

**5. `net-worth` excludes cash and says so.** `analytics.py:16` returns
`includes_cash: false`. Correct behavior, but net worth stays incomplete until
holdings parsers exist. Cash balances additionally need a running balance from the
DCU parser.

---

## 5. Next steps

**Immediate (blocked on the owner, not on code):**

1. **Export Capital One CSV** — desktop web only, ~90-day cap, pull month by
   month. Drop into `inbox/capital_one/` with a date-stamped name. The parser is
   written and tested; if the real header differs it raises
   `unexpected Capital One CSV layout` and prints the actual columns.
2. **Export one month from DCU Digital Banking**, then send the header row plus a
   couple of amount-scrubbed sample rows so `DCUCSVParser` can be written against
   the real format instead of a guess. ⚠️ Also confirm the export UI post-merger —
   DCU merged with First Tech on 2026-01-01 and `docs/DATA-SOURCES.md:46` flags
   this as the finding most likely to be stale.

**Then, for net worth** (the other half of the owner's stated goal):

3. Vanguard CSV — note the multi-section format gotcha in `parsers/vanguard.py`
4. Morgan Stanley — `.xlsx`, not CSV; two reports needed (Benefit History +
   Gains & Losses); confirm whether the account is on E\*TRADE or StockPlan Connect
5. Fidelity — ⚠️ **the one place a PDF may still be unavoidable.** The CSV is
   activity-only; 401(k) per-fund balances live in the quarterly PDF statement. If
   PDF parsing is being skipped, consider entering a holdings snapshot manually —
   a 401(k) balance changes slowly and hand-entering four rows a quarter may beat
   writing a PDF parser.

**Code fixes worth doing alongside:** issue #1 (categories) before real data goes
in, since re-categorizing later means re-ingesting. Issues #2 and #3 are small and
will bite during real Capital One ingestion.

---

## 6. Environment — machine-specific facts that cost time to rediscover

**Docker Desktop 4.4.2** (Dec 2021), engine 20.10.12, Compose v2.2.3.

⚠️ **This version's Preferences → Resources pane has no ADVANCED section**, so
there is no memory/CPU slider in the GUI. Resources are set by editing:

```
~/Library/Group Containers/group.com.docker/settings.json
```

Docker Desktop **must be fully quit** before editing (it overwrites the file on
exit). Changed this session: `memoryMiB` 2048 → **6144**, `swapMiB` 1024 → 2048.
Host has 16 GB. Backup of the original at `settings.json.bak-20260806`.

The 2 GB default was too small — `pip install torch` plus Postgres plus the loaded
embedding model would likely have OOM-killed the build (`exit code 137`).

**Port conflict:** another project's containers (`solovis-take-home-*`) occupy
**8000** and **5433** — the exact ports FinSight needs. They were stopped this
session. Restart them with:

```bash
docker start solovis-take-home-db-1 solovis-take-home-web-1
```

The two stacks cannot run simultaneously without remapping FinSight's ports. Note
the API port is hardcoded as `"8000:8000"` in `docker-compose.yml` — only the
Postgres port is parameterized (`POSTGRES_PORT`).

**Local toolchain (mostly irrelevant, deliberately):**
- Host Python is **3.10.5**; `pyproject.toml` requires ≥3.11. **Do not install
  3.12 locally** — run tests in the container instead:
  ```bash
  docker compose exec api pip install pytest && docker compose exec api pytest -q
  ```
- Node is **v16**; Vite 5+ needs 18+. Blocks the Phase 3 React frontend only.

**`.env` is populated** with a real Anthropic API key (108 chars, `sk-ant-api03`),
a spend limit set in the console. Gitignored, never committed.

---

## 7. Resuming work

```bash
cd ~/projects/finsight
docker compose up -d              # no --build needed; the image is cached
curl -s localhost:8000/health | python3 -m json.tool
```

Healthy looks like `{"status":"ok","pgvector":true,...}`.

Useful shortcuts (`Makefile`):

```bash
make logs     # follow API logs — first place to look on a 500
make db       # psql shell inside the db container
make health
make ingest
```

Code edits apply live — `./backend` is bind-mounted and uvicorn runs with
`--reload`. Only dependency changes need `docker compose up --build`.

**Data safety:** `docker compose down` preserves the database (it lives in the
`pgdata` named volume). `docker compose down -v` **destroys it**. There is no
backup and no Alembic migration history — `main.py:33` uses
`create_all()`, which creates missing tables but never migrates existing ones.
Switch to Alembic before there is real data worth keeping.

---

## 8. Orientation for a new agent

Read in this order:

1. `docs/HOW-IT-WORKS.md` — architecture and RAG concepts, written for a reader
   with no prior background
2. `docs/DATA-SOURCES.md` — per-institution export formats and their confidence
   levels; read before writing any parser
3. `backend/app/models.py` — the four tables
4. `backend/app/ingestion/pipeline.py` — the orchestrator; the whole flow is here
5. `backend/app/rag/router.py` — the aggregate-vs-semantic decision, which is the
   central design idea

`FinSight-Design-Plan.md` is the **original** plan and is knowingly out of date in
two places: it says DCU has no CSV export (it does), and it puts PDF parsing in
Phase 1 (it belongs in Phase 2 or nowhere). `docs/DATA-SOURCES.md` supersedes it.

**Working style note:** the owner is learning this stack as it's built and wants
to run commands themselves rather than have an agent run them. Explain what a
command does and what its output means; hand over the command rather than
executing it, unless asked.
