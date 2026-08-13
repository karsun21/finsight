# Project State — 2026-08-12

Handoff notes, rewritten at the end of the second working session. Companion to
`docs/HOW-IT-WORKS.md`, which explains the architecture and the RAG concepts from
scratch and holds the authoritative scope statement in §1.1.

**Owner:** Karthik Sundar
**Repo:** `~/projects/finsight`, branch `master`
**Phase:** 1 (banking + credit). **Real Capital One data is ingested.** The
pipeline has run end to end on it.

---

## 1. Scope — read this first

Two decisions define what this project is. Neither should be reversed without a
reason.

**A. Coarse categories only** (2026-08-06). Net worth plus spending at bucket
granularity — "dining", "travel" — never "coffee specifically". This dropped the
scikit-learn categorizer and the two-stage "semantic filter → SQL aggregate"
retrieval design.

**B. Two institutions automated, three by hand** (2026-08-12). Capital One
(credit) and DCU (cash) get parsers. Vanguard, Fidelity, and Morgan Stanley get
**hand-entered quarterly holdings snapshots** instead. Those three parsers add no
new architecture while being the most expensive to write — Vanguard's
multi-section CSV, Morgan Stanley's two `.xlsx` reports, and Fidelity's
balances existing only in a quarterly PDF. Balances move slowly enough that
typing a few rows a quarter wins.

**Net worth is not dropped.** `holdings` is already keyed on `(institution,
as_of_date, ticker)` and does not care whether a row came from a parser or from
you. `/net-worth`, `/allocation`, and the SQL rollups work identically either way.

Full reasoning: `docs/HOW-IT-WORKS.md` §1.1.

---

## 2. What is verified working

Everything below has actually run on this machine, and everything from "real
Capital One CSV" down ran against **real financial data**, not fixtures.

- `docker compose up` — Postgres 16 + pgvector, schema auto-created, institutions seeded
- **196 real transactions ingested** from three Capital One statement exports
  covering 2026-04-11 to 2026-07-11
- Parser matched the real export layout with zero warnings and zero failures
- **Content-hash file skip** — re-running `/ingest` with an already-processed file
  present correctly skipped it (`files_seen: 3, files_ingested: 2`)
- **Categorization** — observed on real data down to **4 uncategorized rows out of
  196**, at which point rules were added for the last four merchants
- Local embeddings — 384-dim vectors, batched per file, no API cost
- Test suite green in the container (49 passing at last container run)

## 2a. What is NOT verified — start here next session

Three things were written and reasoned about but **never actually run**. Do not
report them as working without checking.

1. **The final re-ingest output was never seen.** After the last taxonomy changes
   (Fabletics → shopping, PerksAtWork → entertainment, Ventra → transport, Google
   One → subscriptions, fitness → health) the predicted breakdown was: dining 83,
   shopping 47, transport 39, health 7, groceries 6, travel 5, entertainment 3,
   card_payment 3, subscriptions 1, donations 1, housing 1, **uncategorized 0** —
   196 rows, spending summing to −3653.51. **Confirm against reality**:

   ```bash
   docker compose exec db psql -U finsight -d finsight -c \
     "SELECT category, count(*), round(sum(amount),2) AS total
      FROM transactions GROUP BY category ORDER BY count DESC;"
   ```

2. **`_coverage_facts()` has never executed.** It compiles and its partial-month
   logic was unit-checked in isolation, but no `/chat` call has run since it was
   added, so its output has never been seen in a real prompt.

3. **`/chat` has never been asked a question against real data.** Both routes were
   exercised in the first session on a 4-row synthetic fixture only. This is the
   headline feature and it is the least-tested thing in the project.

   ```bash
   curl -sS -X POST localhost:8000/chat -H 'content-type: application/json' \
     -d '{"question": "How much did I spend on dining?"}' | python3 -m json.tool

   # the one that exercises the coverage fix — a naive answer here claims
   # spending collapsed in July, when July is simply 11 days long
   curl -sS -X POST localhost:8000/chat -H 'content-type: application/json' \
     -d '{"question": "How has my spending changed month to month?"}' | python3 -m json.tool

   # semantic route: should say "semantic" in the response, not "aggregate"
   curl -sS -X POST localhost:8000/chat -H 'content-type: application/json' \
     -d '{"question": "What was that charge from the storage place?"}' | python3 -m json.tool
   ```

   Check `route` and `rows_used` in each response, not just the prose. An answer
   that looks right via the wrong route is a misrouting bug waiting to surface on
   a question where it matters.

---

## 3. The real-data state

| | |
|---|---|
| Institutions with data | Capital One only |
| Transactions | 196 |
| Coverage | 2026-04-11 → 2026-07-11, contiguous, no gaps |
| Complete calendar months | May and June only — **April and July are partial** |
| Holdings | 0 — none entered yet |
| Categories | 11 in use; uncategorized count **unconfirmed since the last rule change**, see §2a |

The three source CSVs live in `inbox/capital_one/` and are **gitignored**. The
database lives in the `pgdata` Docker volume, not in the repo.

**Statement periods run mid-month to mid-month** (~11th to ~12th), so calendar
month rollups split each statement across two buckets. `_coverage_facts()` in
`rag/retrieval.py` now tells the LLM which months are partial, because the
rollups are correct while the conclusion drawn from them ("spending collapsed in
July") is not.

---

## 4. Work completed this session

**Categorizer rewritten.** `pipeline.py` used to do `txn.category or
categorize(...)`, which short-circuited on Capital One's own label and meant the
rules never ran for card transactions at all. Now `resolve_category()` runs
description rules **first**, falls back to a mapped issuer label, then `None`.
Taxonomy is `CATEGORIES` in `classification/rules.py`, validated at import.

**Five short-token substring bugs found and fixed.** `MTA` matched inside
`PYMTAUTHDATE` (a card payment counted as transport), `ATM` inside `TREATMENT`,
`ACH` inside `COACH`, `FEE` inside `COFFEE`, `RENT` inside `AVIS RENT A CAR`. All
`\b`-anchored now with named regression tests. **This is the failure mode to
watch for whenever a short pattern is added** — nothing errors, the row just
lands in the wrong bucket.

**File dedup by content hash.** `ingestion_log.file_hash` replaced the
filename-only check. Capital One names every export identically.

**Within-file duplicate handling.** Two genuinely identical same-day charges used
to collide on `dedup_hash` and 500 the whole ingest. Now the occurrence index
*within the file* joins the key — occurrence 0 hashes unchanged, the second
hashes `base#1`. Counting per file rather than per database is what keeps
re-ingestion idempotent; see the docstring on `occurrence_hash()`.

**Persistence wrapped.** A constraint violation now logs one failed file instead
of 500-ing `/ingest` and abandoning the rest of the inbox.

**Taxonomy decisions made against real data** (all reversible, all one-line):

| Decision | Rationale |
|---|---|
| Local transit → `transport`, not `travel` | Capital One files subway fares under a travel-ish label by MCC range. 18 of 19 "travel" rows were commuting. `travel` means trips; `transport` means getting around. |
| `other travel` issuer label → `None` | Grab bag: carried transit *and* self-storage. Real travel arrives as `airfare`/`hotels`/`lodging`. |
| Fitness → `health`, not `entertainment` | Issuer put gym memberships beside concert tickets. Owner chose folding into health over a separate `fitness` bucket, to keep the bucket count down. |
| `utilities` above `transport` in rule order | So phone carriers win the word "METRO". |
| `travel` and `donations` buckets added | Both named explicitly by the owner or found in real data. |

---

## 5. Open issues, in priority order

**1. `rag/retrieval.py` semantic path truncates silently.** Returns exactly
`retrieval_top_k` (20) rows with no signal that more matched, so Claude can sum 20
of 30 relevant rows and state a confident wrong total. Mitigation: when the result
count equals `k`, say so in the facts — the same technique `_coverage_facts()`
now uses. Lower priority because coarse questions route to SQL.

**2. No `issuer_category` column.** We store the *resolved* category and discard
Capital One's original label, so "why is this row in this bucket?" is not
answerable in SQL — diagnosing the travel problem required re-running the rules by
hand. Adding it needs one `ALTER TABLE` (see §7). Recommended before more data
lands.

**3. `/net-worth` excludes cash and says so** (`includes_cash: false`). Correct,
but net worth stays incomplete until the DCU parser and the manual holdings
snapshots exist.

**4. No migrations.** `main.py` uses `create_all()`, which creates missing tables
but never alters existing ones. There is real data now and no backup. This already
bit once, when `file_hash` was added. **Switch to Alembic before the next schema
change.**

**5. `scikit-learn` is still in `pyproject.toml`** and nothing imports it. Dropping
it would meaningfully shrink the image.

**6. `make test` in the Makefile is wrong** — it runs `cd backend && pytest -q` on
the host, which has neither pytest nor a new enough Python. Should be
`docker compose exec api pytest -q`.

---

## 6. Next steps

**Do this first — it takes five minutes and closes out §2a:** confirm the final
category breakdown, then ask `/chat` the three questions in §2a and check the
`route` field on each. Everything below assumes that came back clean.

**Blocked on the owner:**

1. **Export one month from DCU Digital Banking.** `parsers/dcu.py` is 43 lines of
   `NotImplementedError` written against a *guessed* format, and under decision B
   it is now half the pipeline — the single blocking item. Needed: the header row
   plus a few amount-scrubbed sample rows. ⚠️ Also confirm the export UI still
   works post-merger — DCU merged with First Tech on 2026-01-01, and
   `docs/DATA-SOURCES.md:46` flags this as the finding most likely to be stale.

**Unblocked code work:**

2. Manual holdings entry — probably a generic `inbox/holdings/*.csv` parser so a
   few hand-typed rows a quarter flow through the same pipeline. This is the other
   half of net worth.
3. The `issuer_category` column (§5.2).
4. Truncation signal on the semantic path (§5.1).

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
docker compose logs --tail 50 api          # -f follows forever; Ctrl+C to exit
docker compose exec db psql -U finsight -d finsight
docker compose exec api pytest -q
curl -sS -X POST localhost:8000/ingest | python3 -m json.tool
curl -sS localhost:8000/health | python3 -m json.tool
```

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

Healthy looks like `{"status":"ok","pgvector":true,"transactions":196,...}`.

Code edits apply live — `./backend` is bind-mounted and uvicorn runs `--reload`.
Only dependency changes need `--build`.

**Re-ingesting after a categorization change.** The category is baked into the
embedded text, so changing rules requires a real re-ingest, not an `UPDATE`. The
source CSVs stay in `inbox/`, so clearing both tables is enough — deleting the log
row is what lets the file-hash check see the file as new again:

```bash
docker compose exec db psql -U finsight -d finsight -c \
  "DELETE FROM transactions; DELETE FROM ingestion_log;"
curl -sS -X POST localhost:8000/ingest | python3 -m json.tool
```

**Data safety.** `docker compose down` preserves the database. `docker compose
down -v` **destroys it** — and also wipes `hfcache`, forcing a re-download of the
embedding model. There is no backup and no migration history.

**Adding a column** (until Alembic exists): `create_all()` will not alter an
existing table, so do it by hand and restart:

```bash
docker compose exec db psql -U finsight -d finsight -c \
  "ALTER TABLE transactions ADD COLUMN issuer_category VARCHAR(64);"
docker compose restart api
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

`FinSight-Design-Plan.md` is the original plan and is knowingly out of date;
`docs/DATA-SOURCES.md` and `HOW-IT-WORKS.md` §1.1 supersede it.

**Working style.** The owner is learning this stack as it is built and prefers to
run commands themselves. Explain what a command does and what its output means,
and hand it over rather than executing it, unless asked. They respond well to
being told when a number looks wrong and why — several real bugs this session were
found by treating a plausible-looking result skeptically rather than accepting it.
