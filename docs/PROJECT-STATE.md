# Project State — 2026-09-01

Handoff notes, rewritten at the end of the third working session. Companion to
`docs/HOW-IT-WORKS.md`, which explains the architecture and the RAG concepts from
scratch and holds the authoritative scope statement in §1.1.

**Owner:** Karthik Sundar
**Repo:** `~/projects/finsight`, branch `main` (private GitHub remote `karsun21/finsight`)
**Phase:** 1 (banking + credit). **Real Capital One data is ingested, and `/chat`
has now been exercised against it on all three routes.**

---

## 1. Scope — read this first

Two decisions define what this project is. Neither should be reversed without a
reason.

**A. Coarse categories only** (2026-08-06). Net worth plus spending at bucket
granularity — "dining", "travel" — never "coffee specifically". This dropped the
scikit-learn categorizer and the two-stage "semantic filter → SQL aggregate"
retrieval design.

**B. One institution automated, the rest by hand** (2026-08-12, tightened
2026-09-01). Capital One (credit) has the only parser. Vanguard, Fidelity, and
Morgan Stanley get **hand-entered quarterly holdings snapshots** instead — those
parsers add no new architecture while being the most expensive to write
(Vanguard's multi-section CSV, Morgan Stanley's two `.xlsx` reports, Fidelity's
balances existing only in a quarterly PDF), and balances move slowly enough that
typing a few rows a quarter wins.

**Their stub parsers have been deleted**, along with DCU's and the Capital One
PDF stub — 165 lines of `NotImplementedError` that had never executed, against 96
lines of working code. Every export format they documented is preserved in
`docs/DATA-SOURCES.md`, which is where that research belongs. Re-adding a parser
is a new file plus one line in `registry.py`; `BaseParser` and the working Capital
One parser already show the pattern.

**Net worth is not dropped.** `holdings` is already keyed on `(institution,
as_of_date, ticker)` and does not care whether a row came from a parser or from
you. `/net-worth`, `/allocation`, and the SQL rollups work identically either way.

Full reasoning: `docs/HOW-IT-WORKS.md` §1.1.

---

## 2. What is verified working

Everything below has actually run on this machine against **real financial data**,
not fixtures.

- `docker compose up` — Postgres 16 + pgvector, schema auto-created, institutions seeded
- **196 real transactions ingested** from three Capital One statement exports
  covering 2026-04-11 to 2026-07-11
- Parser matched the real export layout with zero warnings and zero failures
- **Content-hash file skip** — re-running `/ingest` with an already-processed file
  present correctly skipped it
- **Categorization: 0 uncategorized out of 196**, confirmed by query, with every
  bucket matching the predicted breakdown and every amount delta reconciled to
  the cent (§4)
- Local embeddings — 384-dim vectors, batched per file, no API cost
- **`/chat` answered correctly on all three question shapes** (§2a)
- **Chat UI at `GET /`** — a single self-contained HTML file in
  `backend/app/static/`, served by the API. Each answer carries a badge naming
  the route that served it and how much it was given, which makes the
  aggregate-vs-semantic split visible rather than merely claimed.
- **`_coverage_facts()` executes and its partial-month clause does its job** —
  April and July are correctly excluded from trend comparisons
- Test suite green in the container: **77 passing**

> The previous version of this file said "49 passing" — it was stale by 23 tests.
> Treat counts in handoff notes as decaying; re-run rather than quote.

## 2a. §2a is empty — all three items closed 2026-09-01

The three things the last session flagged as written-but-never-run have now all
been run. Recorded here because *how* they failed is the useful part.

1. **Final category breakdown — confirmed, after a re-ingest.** The first query
   did not match the prediction: 4 uncategorized rows, health 3 not 7,
   entertainment 6 not 3, a `utilities` bucket that shouldn't exist. The rules
   were all present and correct in `rules.py`; **the database was three weeks
   stale.** A rule edit is invisible until a re-ingest, because the category is
   baked into the embedded text. After re-ingesting, every bucket matched.
2. **`_coverage_facts()` executed** — proven by `rows_used` arithmetic and by the
   coverage window appearing in the answer text. Its partial-month clause was
   then genuinely exercised by the month-over-month question and worked.
3. **`/chat` answered all three questions against real data.** Dining routed to
   `aggregate` and returned the correct $1,476.73 / 83 txns. The storage lookup
   routed to `semantic` and found the right row. The month-over-month question
   **failed on first run** and exposed two real bugs — both since fixed (§4).

---

## 3. The real-data state

| | |
|---|---|
| Institutions with data | Capital One only |
| Transactions | 196 |
| Coverage | 2026-04-11 → 2026-07-11, contiguous, no gaps |
| Complete calendar months | May and June only — **April and July are partial** |
| Holdings | 0 — none entered yet |
| Categories | 11 in use, **uncategorized 0**, confirmed 2026-09-01 |
| Spending total | **−3653.51** (excludes `card_payment`) — the invariant to check after any re-ingest |

Monthly spending, now that payments are excluded from the rollup:

| month | spending | payments |
|---|---|---|
| 2026-04 | −839.80 | — |
| 2026-05 | −1424.25 | 1 |
| 2026-06 | −1024.88 | 1 |
| 2026-07 | −364.58 | 1 |

The three source CSVs live in `inbox/capital_one/` and are **gitignored**. The
database lives in the `pgdata` Docker volume, not in the repo.

**Statement periods run mid-month to mid-month** (~11th to ~12th), so calendar
month rollups split each statement across two buckets, and April and July are
partial. `_coverage_facts()` tells the LLM which months are partial — verified
working.

---

## 4. Work completed this session

**Re-ingest closed a stale database.** See §2a.1. Every delta reconciled exactly:
shopping −29.99 (two Fabletics rows, 27.15 + 2.84), transport −5.00 (Ventra),
health/entertainment ±240.97 (four fitness rows, derived independently from both
buckets and agreeing), and the Google One row moving from `utilities` to
`subscriptions`. Spending total unchanged at −3653.51 throughout, which is what
proves rows moved buckets without amounts changing.

**Router bug: periodicity questions fell through to vector search.**
"How has my spending changed month to month?" matched none of the eleven
`AGGREGATE_PATTERNS` — the closest, `\bper month\b|\bmonthly\b`, does not cover
"month to month" — so it routed `semantic`, got 20 raw transactions, and the
model correctly refused to sum them. Fixed by adding three patterns covering the
*family* (month-to-month/over-month, each|every|by|per month|week|year, trend),
one of which replaces the narrower `per month`. Five test cases added.

⚠️ **The router is an allowlist that defaults to the route that cannot do
arithmetic.** Any rollup phrasing nobody enumerated degrades silently to vector
search. The docstring's escalation plan stands: **if a third distinct phrasing
misroutes, stop adding patterns and add the Haiku classifier.** One has misrouted
so far.

**Monthly rollup bug: card payments were netted into spending, inverting the
answer.** `aggregate_facts()` built its monthly fact as a bare
`sum(amount)` over all transactions and labelled it `Net cash flow`. With one
card payment per statement cycle, the payment dominates and flips the sign — the
model reported May→June as a **+$135.77 rise** when spending had in fact **fallen
$399.37 (28%)**. Fixed by reporting spending and payments as separate facts,
gated on a new `NON_SPEND_CATEGORIES` frozenset in `rules.py`
(`card_payment`, `transfer`, `income`, `investment_income`; `cash` deliberately
excluded — an ATM withdrawal is money going out), with a subset assert against
`CATEGORIES`.

This is the most instructive bug so far: well-formatted, confident, and
**backwards**, in a function with no test coverage, sitting there since the
aggregate path was written.

**Alembic, replacing `create_all()`.** `backend/alembic/`, with `env.py` taking
the URL from `app.config` rather than `alembic.ini` (blanked, with a comment)
so the app and its migrations cannot disagree about which database they mean.
`compare_type=True` is set — without it a `VARCHAR(32)` → `VARCHAR(64)` change is
silently ignored. `script.py.mako` imports `pgvector.sqlalchemy`, because
autogenerate renders the embedding columns as
`pgvector.sqlalchemy.vector.VECTOR(dim=384)` without adding the import, and every
migration touching them would otherwise die with a `NameError`.

The baseline had to be generated against a **scratch database** — autogenerating
against `finsight`, where `create_all()` had already built the tables, produces
an empty migration. It was then proved on a bare database (no tables, no
extension) before the live one was stamped, and `alembic check` confirms the
stamp is honest rather than hiding drift. The migration creates the `vector`
extension itself: `db/init/01_init.sql` only runs on first compose up against an
empty volume, so a migration depending on it is not self-sufficient.

Migrations now run in the container command before uvicorn, so an un-migrated
database fails at boot rather than at the first query hitting a missing column.

**`issuer_category`, and what it revealed.** Added as the first real migration —
`1a47c85fc709 → 9aebc89a15f0` against the live database, reversible, 196 rows and
the −3653.51 invariant intact through the `ALTER`. Backfilled by re-ingest;
populated for all 196 rows. The provenance it exposes confirms decisions
previously made from inference alone:

| resolved | issuer label | n |
|---|---|---|
| transport | other travel | 39 |
| housing | other travel | 1 |
| travel | other travel | 3 |
| health | entertainment | 4 |
| subscriptions | internet | 1 |
| groceries | merchandise | 6 |

`other travel` yields 43 rows across three resolved categories — direct evidence
it is a grab bag rather than a category, which is why it maps to `None`. The four
`health`/`entertainment` rows are the fitness reclassification, previously known
only from delta arithmetic.

**pytest was never in the image.** The Dockerfile ran `pip install -e .`, which
omits the `[dev]` extras. The suite had been passing only because some earlier
session pip-installed pytest into a container's writable layer; recreating the
container destroyed it. On a fresh clone the documented test command would have
failed. Fixed to `-e ".[dev]"`. This is the argument for CI in one incident.

---

## 5. Open issues, in priority order

**1. `aggregate_facts()` has no test coverage at all.** This is why the sign
inversion above survived from the day it was written. Every test in the suite is
pure-unit; there is no DB session fixture and no `conftest.py`. Adding one is the
prerequisite for testing the whole aggregate path. **Highest priority** — it is
the gap that hides this entire class of bug.

**2. No category×month cross-tab.** `aggregate_facts()` gives category totals for
the whole period and month totals across all categories, but never the two
crossed. "Which categories drove the May→June decline?" is unanswerable, and the
model has now flagged this itself, unprompted, on two separate questions.

**3. `rag/retrieval.py` semantic path truncates silently.** Returns exactly
`retrieval_top_k` (20) rows with no signal that more matched, so Claude can sum 20
of 30 relevant rows and state a confident wrong total. Both semantic calls this
session returned exactly 20. Mitigation: when the result count equals `k`, say so
in the facts — the same technique `_coverage_facts()` uses.

**4. `/net-worth` excludes cash and says so** (`includes_cash: false`). Correct,
but net worth stays incomplete until hand-entered holdings snapshots exist.

**5. `scikit-learn` is still in `pyproject.toml`** and nothing imports it.

**6. `make test` in the Makefile is wrong** — it runs `cd backend && pytest -q` on
the host, which has neither pytest nor a new enough Python. Should be
`docker compose exec api pytest -q`. (Moot until `make` is installed; see §7.)

*Closed 2026-09-01: no migrations (now Alembic, §4) and no `issuer_category`
column (now present and populated for all 196 rows, §4).*

---

## 6. Next steps

The goal shaping this order (set 2026-09-01): the owner is putting this on a
résumé for **mid-level backend roles**. That ranks demonstrated engineering rigour
above breadth of integrations, and it is why the DCU parser is *not* on this list.
A second CSV parser shows nothing the first one does not.

1. ~~Alembic migrations~~ — **done 2026-09-01** (§4).
2. **CI: GitHub Actions running `pytest`.** ~20 lines, and now demonstrably
   load-bearing: the Dockerfile installed `-e .` without the `[dev]` extras, so
   pytest was never in the image and the suite only ran in containers where
   someone had installed it by hand. CI would have caught that on day one.
3. **A DB session fixture + tests for `aggregate_facts()`** (§5.1). Every test in
   the suite is currently pure-unit; there is no `conftest.py`. This is the gap
   that hid the sign inversion.
4. **README with an architecture summary, a real `/chat` transcript, and a
   `/docs` screenshot**, plus a synthetic demo dataset grown from
   `capital_one_sample.csv`. The repo is private and full of real data, so this is
   how anyone else ever sees it work.
5. Category×month cross-tab (§5.2) — closes the gap the model keeps flagging.
6. Truncation signal on the semantic path (§5.3).
7. Manual holdings entry — probably a generic `inbox/holdings/*.csv` parser so a
   few hand-typed rows a quarter flow through the same pipeline. This, not DCU,
   is what unlocks net worth: DCU is cash, holdings are the investments.

**Explicitly not doing:** the DCU parser, and the Phase 3 React dashboard. If DCU
is ever revived it needs a real export header from the owner first, and
`docs/DATA-SOURCES.md:46` flags the post-merger export UI (DCU merged with First
Tech on 2026-01-01) as the finding most likely to be stale.

---

## 7. Environment — machine-specific facts that cost time

**Docker Desktop 4.4.2** (Dec 2021), engine 20.10.12, Compose v2.2.3.

⚠️ That version's Preferences → Resources pane has **no ADVANCED section**, so
there is no memory/CPU slider. Resources are set by fully quitting Docker Desktop
(it overwrites the file on exit) and editing:

```
~/Library/Group Containers/group.com.docker/settings.json
```

`memoryMiB` was raised 2048 → **6144** on 2026-08-06; the 2 GB default risked
OOM-killing the torch build. Backup at `settings.json.bak-20260806`.

⚠️ **`make` is not installed on this Mac.** There are no Xcode Command Line Tools,
so running any `make` target triggers an install dialog. Cancel it — every target
is a one-line wrapper. Use the commands directly:

```bash
docker compose up -d
docker compose logs --tail 50 api
docker compose exec db psql -U finsight -d finsight
docker compose exec api pytest -q
curl -sS -X POST localhost:8000/ingest | python3 -m json.tool
curl -sS localhost:8000/health | python3 -m json.tool
```

⚠️ **Write shell commands on a single line.** Backslash line-continuations break
when pasted here — the backslash escapes a *space* instead of a newline, and the
command mis-parses silently rather than erroring. This cost two round trips this
session (a `psql -c` that ran an empty query, and a `curl` that POSTed no body).

**Port conflict:** another project's containers (`solovis-take-home-*`) occupy
**8000** and **5433** — the exact ports FinSight needs. Stop them first. The API
port is hardcoded `"8000:8000"` in `docker-compose.yml`; only Postgres is
parameterized.

**Host toolchain is deliberately irrelevant.** Host Python is 3.10.5 and the
project needs ≥3.11; pytest and SQLAlchemy are not installed on the host. Run
tests in the container. Node is v16, which blocks the Phase 3 React frontend only.

**`.env` is populated** with a real Anthropic API key and a console spend limit.
Gitignored, never committed — verified against full git history.

---

## 8. Resuming work

```bash
docker stop solovis-take-home-db-1 solovis-take-home-web-1   # if running
cd ~/projects/finsight && docker compose up -d
curl -s localhost:8000/health | python3 -m json.tool
```

Healthy looks like `{"status":"ok","pgvector":true,"transactions":196,"holdings":0}`.

Code edits apply live — `./backend` is bind-mounted and uvicorn runs `--reload`.
Only dependency changes need `--build`.

**Re-ingesting after a categorization change.** ⚠️ **A rule edit does nothing
until you re-ingest.** The category is baked into the embedded text, so changing
rules requires a real re-ingest, not an `UPDATE` — and nothing warns you. This
silently cost three weeks: the rules were correct in the file the whole time
while every query reported the old buckets. Deleting the log row is what lets the
file-hash check see the file as new again:

```bash
docker compose exec db psql -U finsight -d finsight -c "DELETE FROM transactions; DELETE FROM ingestion_log;"
curl -sS -X POST localhost:8000/ingest | python3 -m json.tool
```

Then confirm — spending must still total **−3653.51**:

```bash
docker compose exec db psql -U finsight -d finsight -c "SELECT category, count(*), round(sum(amount),2) AS total FROM transactions GROUP BY category ORDER BY count DESC;"
```

**Data safety.** `docker compose down` preserves the database. `docker compose
down -v` **destroys it** — and also wipes `hfcache`, forcing a re-download of the
embedding model. There is no backup and no migration history.

**Adding a column.** Edit `models.py`, then autogenerate and apply. Never hand-write
an `ALTER TABLE` against the database — the whole point of Alembic is that the
schema's history is in the repo.

```bash
docker compose exec api alembic revision --autogenerate -m "what changed"
```

Read the generated file in `backend/alembic/versions/` before applying it —
autogenerate proposes, it does not decide. Then:

```bash
docker compose exec api alembic upgrade head
```

`docker compose up -d api` also applies migrations, since they run in the
container command before uvicorn. Useful checks:

```bash
docker compose exec api alembic current   # what revision is this database on
docker compose exec api alembic check     # do the models match the schema
docker compose exec api alembic downgrade -1
```

---

## 9. Repo hygiene

Verified 2026-08-12 against full git history: **no `.env`, no real CSV, no PDF has
ever been committed.** `.gitignore` covers `.env`, `inbox/*/*`, and every
statement file extension, with an exception for the synthetic test fixture.

Two things to keep true:

- `backend/tests/fixtures/capital_one_sample.csv` is **synthetic** — 4 invented
  rows. It is the one CSV that is allowed in the repo. Do not replace it with a
  real export.
- Tests reference real merchant *brands* (needed for the patterns to be
  meaningful) but store numbers, cities, and booking references have been
  genericized. Keep it that way when adding cases from real data.

---

## 10. Orientation for a new agent

Read in this order:

1. `docs/HOW-IT-WORKS.md` — architecture and RAG from zero; §1.1 is the scope
2. `docs/DATA-SOURCES.md` — per-institution export formats and confidence levels
3. `backend/app/models.py` — the four tables
4. `backend/app/ingestion/pipeline.py` — the orchestrator
5. `backend/app/classification/rules.py` — the taxonomy, which *is* the product
6. `backend/app/rag/router.py` — aggregate-vs-semantic, the central design idea
7. `backend/app/rag/retrieval.py` — `aggregate_facts()` is where the LLM's
   arithmetic comes from, and it is untested (§5.1)

`FinSight-Design-Plan.md` is the original plan and is knowingly out of date;
`docs/DATA-SOURCES.md` and `HOW-IT-WORKS.md` §1.1 supersede it.

**Working style.** The owner is learning this stack as it is built and prefers to
run commands themselves. Explain what a command does and what its output means,
and hand it over rather than executing it, unless asked. They respond well to
being told when a number looks wrong and why — **every real bug across three
sessions has been found that way**, by treating a plausible-looking result
sceptically rather than accepting it. The May→June "spending rose $135.77" answer
was well-formatted, internally consistent, and exactly backwards.
