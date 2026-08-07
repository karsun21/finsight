# How FinSight Works

A ground-up explanation of what this project is, what every piece of technology in
it does, and how a single line from a bank statement becomes an answer to a
question you type. No prior knowledge assumed — especially not about RAG, which
gets its own section built from scratch.

Read it top to bottom. Each part builds on the one before.

---

## Contents

1. [What FinSight is](#1-what-finsight-is)
2. [The whole thing in one diagram](#2-the-whole-thing-in-one-diagram)
3. [The tech stack, piece by piece](#3-the-tech-stack-piece-by-piece)
4. [RAG explained from zero](#4-rag-explained-from-zero)
5. [Following one transaction all the way through](#5-following-one-transaction-all-the-way-through)
6. [What happens when you ask a question](#6-what-happens-when-you-ask-a-question)
7. [Five design decisions worth understanding](#7-five-design-decisions-worth-understanding)
8. [Every file in the repo](#8-every-file-in-the-repo)
9. [What's built and what isn't](#9-whats-built-and-what-isnt)
10. [Glossary](#10-glossary)

---

## 1. What FinSight is

You have money in five places: a checking account at DCU, a Capital One credit
card, a Vanguard brokerage account, a Fidelity 401(k), and Morgan Stanley ESPP
shares. Each one has its own website, its own login, its own idea of what a
"transaction" looks like. None of them talk to each other. If you want to know
what you spent on dining last quarter, or how much of your net worth is tied up in
your employer's stock, you're opening five tabs and doing arithmetic by hand.

FinSight is a program that:

1. **Reads** the CSV and PDF files those five institutions let you download
2. **Normalizes** them — turns five different formats into one consistent shape
3. **Stores** them in a single database on your laptop
4. **Answers questions about them in plain English**

That last part is the interesting one, and it's where RAG comes in.

**Everything runs on your machine.** There's no cloud service, no account to sign
up for, no company holding your financial data. The one exception is that when you
ask a question, the relevant rows get sent to Anthropic's API so Claude can phrase
an answer — and even then, only the handful of rows relevant to your question, not
your whole database.

---

## 2. The whole thing in one diagram

```
   YOU                                          YOUR LAPTOP
    │
    │  download CSV from
    │  capitalone.com
    ▼
 ~/Downloads/transactions.csv
    │
    │  cp into the folder
    ▼
 inbox/capital_one/june.csv  ─────────────┐
                                          │
                                          │  (a "bind mount" makes this
                                          │   folder visible inside Docker)
                                          ▼
    ┌──────────────────────────────────────────────────────────────┐
    │  DOCKER                                                      │
    │                                                              │
    │   ┌──────────────────────┐      ┌────────────────────────┐   │
    │   │  API container       │      │  DB container          │   │
    │   │                      │      │                        │   │
    │   │  FastAPI (Python)    │◄────►│  PostgreSQL 16         │   │
    │   │   ├ parsers          │      │   + pgvector extension │   │
    │   │   ├ dedup            │      │                        │   │
    │   │   ├ categorizer      │      │   transactions         │   │
    │   │   ├ embedding model  │      │   holdings             │   │
    │   │   └ chat logic       │      │   institutions         │   │
    │   │                      │      │   ingestion_log        │   │
    │   └──────────┬───────────┘      └────────────────────────┘   │
    │              │                                               │
    └──────────────┼───────────────────────────────────────────────┘
                   │
         ┌─────────┴──────────┐
         │                    │
         ▼                    ▼
    YOU, via curl        Anthropic API
    localhost:8000       (only on /chat, only
                          the relevant rows)
```

Two containers. One holds the database, one holds the Python program. They talk to
each other over a private network. You talk to the Python one on port 8000.

---

## 3. The tech stack, piece by piece

For each tool: what it is, why it's here, and where to see it in the repo.

### Docker and Docker Compose

**What it is.** Docker runs programs inside *containers* — isolated mini-computers
with their own filesystem, their own installed software, their own network. A
container is built from an *image*, which is a snapshot of a filesystem someone
already prepared.

**Why it's here.** This project needs Python 3.12, PostgreSQL 16, the pgvector
extension, ghostscript, and about 30 Python libraries. Installing all of that on
your Mac directly would be tedious, would conflict with other projects, and would
be impossible to reproduce on another machine. Instead, `docker compose up` builds
it all inside containers, and `docker compose down -v` deletes every trace.

Your Mac has Python 3.10 installed. **That is completely irrelevant** to this
project — the API container has its own Python 3.12 inside it.

**Docker Compose** is the tool that runs *several* containers together as a unit.
`docker-compose.yml` describes both containers, wires them onto a shared network,
and starts them in the right order (the API waits for the database to be healthy).

**Where to look:** `docker-compose.yml`, `backend/Dockerfile`

Two ideas from that file are worth understanding, because they explain how files
and data move around:

**Bind mounts** connect a folder on your Mac to a path inside a container:

```yaml
- ./inbox:/inbox:ro
```

Your `inbox/` folder appears inside the container as `/inbox`. Not a copy — the
same folder. Drop a file in on your Mac and the container sees it instantly. The
`:ro` means *read-only*: the container physically cannot modify or delete your
statements.

```yaml
- ./backend:/srv
```

Same trick for the source code. This is why the API is started with `--reload` —
when you edit a Python file on your Mac, the container sees the change and
restarts the server automatically. No rebuild needed to change code.

**Named volumes** are Docker-managed storage that isn't in your project folder:

```yaml
- pgdata:/var/lib/postgresql/data      # the database's actual data
- hfcache:/root/.cache/huggingface     # the downloaded embedding model
```

`pgdata` is where your ingested transactions physically live. It survives
restarts and rebuilds. `docker compose down -v` — note the `-v` — is what deletes
it. `hfcache` saves you re-downloading the 90 MB embedding model every rebuild.

### PostgreSQL

**What it is.** A relational database: data in tables with rows and columns, and a
query language called SQL for asking precise questions about it.

**Why it's here.** You need somewhere to put thousands of transactions that
supports "sum every dining charge between March and June" without loading
everything into memory. That's exactly what a relational database is for.

**Where to look:** the tables are defined in `backend/app/models.py`. There are
four:

| Table | What's in it |
|---|---|
| `institutions` | Five rows, one per bank. Seeded automatically at startup. |
| `transactions` | One row per purchase, payment, deposit — money moving. |
| `holdings` | One row per investment position at a point in time — money sitting. |
| `ingestion_log` | One row per file processed. Audit trail: what worked, what failed. |

The `transactions` / `holdings` split matters. A transaction is an *event* ("on
March 4th, $42.10 left my account"). A holding is a *snapshot* ("as of March 31st,
I owned 12.4 shares of VTSAX worth $1,800"). Net worth comes from holdings; spending
comes from transactions. Different shapes, different questions, different tables.

### pgvector

**What it is.** An extension that teaches PostgreSQL a new column type — `vector` —
and how to measure the distance between two vectors efficiently.

**Why it's here.** This is what makes semantic search possible without a second
database. Section 4 explains what a vector is and why you'd want to measure
distance between them. For now: it means the embeddings live *in the same table*
as the transactions they describe, so you never have to keep two systems in sync.

**Where to look:** `db/init/01_init.sql` turns the extension on (a single
`CREATE EXTENSION` that runs once, on first startup). `models.py:46` declares the
column. `rag/retrieval.py:20` uses it.

### FastAPI

**What it is.** A Python framework for building web APIs. You write a function,
decorate it with a URL, and it becomes an HTTP endpoint.

**Why it's here.** It's how you talk to the program. Instead of running scripts,
you send HTTP requests — which means a React frontend can later talk to exactly
the same endpoints your `curl` commands hit.

**Where to look:** `backend/app/api/routes/`, one file per group of endpoints.

| Endpoint | What it does |
|---|---|
| `GET /health` | Is everything alive? Row counts. |
| `POST /ingest` | Scan `inbox/`, process new files. |
| `GET /ingestion-log` | What happened during past ingests. |
| `GET /transactions` | List/filter transactions. |
| `GET /holdings` | List/filter investment positions. |
| `GET /net-worth` | Total investment value, and over time. |
| `GET /allocation` | Percentage breakdown by position. |
| `POST /chat` | **Ask a question in English.** |

FastAPI also generates interactive documentation for free at
<http://localhost:8000/docs> — every endpoint, its parameters, and a button to try
it. Worth clicking through once.

### SQLAlchemy

**What it is.** An ORM — Object-Relational Mapper. It lets you write Python instead
of SQL strings, and turns database rows into Python objects.

**Why it's here.** Compare:

```sql
SELECT * FROM transactions WHERE category = 'dining' ORDER BY txn_date DESC;
```
```python
select(Transaction).where(Transaction.category == "dining").order_by(desc(Transaction.txn_date))
```

The second is checked by your editor, refactorable, and can't be broken by a
malformed string. It also defines the tables themselves — `models.py` is both the
Python classes *and* the schema definition. On startup, `main.py:33` calls
`Base.metadata.create_all()`, which creates any table that doesn't exist yet.
That's why there's no separate "set up the database" step.

**Where to look:** `backend/app/models.py`, `backend/app/db.py`

### Pydantic

**What it is.** A validation library. You declare what shape data should have, and
it enforces it.

**Why it's here.** Two jobs:

1. **API contracts** (`schemas.py`) — what a response looks like. `TransactionOut`
   deliberately omits the `embedding` column, so 384 floats per row don't get
   dumped into your terminal.
2. **Configuration** (`config.py`) — reads environment variables into a typed
   object. `get_settings().chat_model` instead of `os.environ["CHAT_MODEL"]` with
   a fallback everywhere.

### pandas

**What it is.** The standard Python library for tabular data. Reads a CSV into a
`DataFrame` — a table you can filter, transform, and iterate over.

**Why it's here.** Every parser starts with `pd.read_csv()`. It handles quoted
fields, commas inside descriptions, missing values, and encoding issues you'd
otherwise write by hand.

**Where to look:** `backend/app/ingestion/parsers/capital_one.py:39`

### sentence-transformers (and torch)

**What it is.** A library that runs small neural networks that turn text into
vectors — lists of numbers that represent meaning. The specific model here is
`all-MiniLM-L6-v2`: about 90 MB, produces 384 numbers per input.

**Why it's here.** It's the engine behind semantic search. Section 4 explains what
that means in detail.

**The important practical facts:** it runs *on your laptop*, it's free, it costs
nothing per use, and no text is sent anywhere. It's also why the Docker build is
3 GB and takes ten minutes — sentence-transformers depends on **torch** (PyTorch),
a large numerical computing library.

**Where to look:** `backend/app/rag/embeddings.py`

### The Anthropic API (Claude)

**What it is.** A paid web service. You send text, you get generated text back.

**Why it's here.** It's the piece that turns retrieved database rows into a
sentence a human wants to read. It is *not* the piece that knows your finances —
it never sees your database, only whatever rows get handed to it for one question.

Note the deliberate limits placed on it in `rag/llm.py:9-20`: answer only from the
provided rows, never estimate, never recompute totals. The design treats the LLM as
a *writer*, not a calculator. More on why in section 6.

**Two models, two jobs** (`.env`):
- `CHAT_MODEL=claude-sonnet-5` — writing answers
- `CLASSIFY_MODEL=claude-haiku-4-5` — cheaper model reserved for simple
  classification (not used yet; the rule-based categorizer handles that for now)

### scikit-learn

**What it is.** A classical machine-learning library.

**Why it's here.** It's in the dependency list for a *future* phase: training a
model to categorize transactions from your corrections. Right now categorization
is done by a list of regular expressions in `classification/rules.py`. That's
intentional — a machine learning model needs thousands of labeled examples to
learn from, and you don't have any yet. The rules generate them.

---

## 4. RAG explained from zero

This is the conceptual heart of the project. Take your time here.

### 4.1 The problem

Claude has read an enormous amount of text, but it has never seen *your* bank
statements. Ask it "how much did I spend at Chipotle last month" and it has
nothing to work with.

So the obvious fix: paste your transactions into the message along with the
question. And for a handful of rows, that genuinely works. But:

- **Volume.** Five accounts over a few years is tens of thousands of rows. Sending
  all of it with every question is slow and expensive — you pay per word sent.
- **Dilution.** Even when everything fits, burying one relevant row in 40,000
  irrelevant ones makes the answer worse, not better.

So you want to send **only the rows relevant to the question.** That's the entire
idea. The hard part is deciding what "relevant" means.

### 4.2 Why keyword search isn't enough

The obvious approach: search the descriptions for words from the question.

It breaks immediately. You ask *"how much do I spend on coffee?"* Your statement
says:

```
STARBUCKS STORE #4412
DUNKIN #338822
BLUE BOTTLE COFFEE
```

Keyword search on "coffee" finds the third. It misses Starbucks and Dunkin
entirely, because the word "coffee" doesn't appear in them. A human knows all three
are coffee. The computer doesn't, because it's matching *letters*, not *meaning*.

You need search that understands that "STARBUCKS" and "coffee" are related.

### 4.3 Embeddings: turning meaning into numbers

Here's the idea that makes it work.

**Imagine a map.** Not of places — of *meanings*. Every piece of text gets a
position on it, placed so that things meaning similar things end up near each
other. "Dog" sits near "puppy." "Starbucks" sits near "coffee shop," which sits
near "cafe." "Mortgage payment" sits far away from all of them, over in a
different neighborhood with "rent" and "property tax."

On such a map, "find things related to coffee" becomes a *geometry* problem: go to
where "coffee" sits, and grab whatever's nearby. Starbucks comes back — not because
the letters match, but because it's in the same neighborhood.

A position on a flat map is two numbers: how far right, how far up. But two numbers
can't capture everything that makes meanings similar or different. Language has far
more dimensions of variation than that — formality, topic, sentiment, whether it's
a place or an action, and thousands of subtler things.

So instead of 2 numbers, we use **384**.

You can't picture a 384-dimensional space, and you don't need to. Every intuition
from the 2D map still holds: things have positions, positions can be close or far
apart, and close means similar. The extra dimensions just give the model more room
to express *how* things are similar.

**That list of 384 numbers is called an embedding.** The neural network that
produces it — `all-MiniLM-L6-v2` — was trained on a very large amount of text
specifically so that texts with similar meanings come out with similar numbers.

Concretely, this line of text:

```
2026-03-04 | Capital One | dining | $-42.10 | CHIPOTLE MEXICAN GRILL
```

goes into the model, and this comes out:

```
[0.0231, -0.0817, 0.0442, 0.1103, -0.0056, ... 379 more numbers]
```

Individually those numbers mean nothing — nobody can tell you what dimension 147
represents. What matters is only their *relationship* to other embeddings. The
embedding of "coffee purchase" will be numerically close to this one. The embedding
of "401k contribution" will be far away.

**Where this happens in the code:** `rag/embeddings.py:17`. The function
`embed_texts()` takes a list of strings and returns a list of 384-number lists.
That's the whole interface.

### 4.4 Measuring "close"

If every row is a point in 384-dimensional space, "find similar rows" means "find
the nearest points." Distance in high dimensions works the same way it does on a
map — there's just a formula that handles all 384 coordinates at once.

The specific measure here is **cosine distance**. Rather than measuring straight
distance between two points, it measures the *angle* between them, treating each
embedding as an arrow pointing out from the origin. Two arrows pointing in nearly
the same direction are similar, regardless of length. In practice this works better
for text, because it cares about *what* a text is about rather than how long or how
emphatic it is.

You never write this formula. pgvector implements it, and SQLAlchemy exposes it as
a method:

```python
.order_by(Transaction.embedding.cosine_distance(vector)).limit(k)
```

That single line is "give me the 20 rows whose meaning is closest to this."
It's `rag/retrieval.py:20`.

### 4.5 Putting it together: what RAG actually is

**RAG** stands for **Retrieval-Augmented Generation.** Read the name backwards and
it explains itself:

- **Generation** — an LLM generating an answer.
- **Augmented** — but given extra information it wouldn't otherwise have.
- **Retrieval** — and that information was *retrieved* by searching, based on the
  question.

The full loop, as this repo implements it:

```
INGESTION TIME (once per file, when you drop a statement in)

   "2026-03-04 | Capital One | dining | $-42.10 | CHIPOTLE MEXICAN GRILL"
                          │
                          ▼
              [ all-MiniLM-L6-v2 model ]
                          │
                          ▼
              [0.0231, -0.0817, ... ]  ← 384 numbers
                          │
                          ▼
      stored in the transactions table, in the `embedding` column,
      in the same row as the date, amount, and description


QUERY TIME (every time you ask a question)

   "how much do I spend on coffee?"
                          │
                          ▼
              [ the exact same model ]           ← this matters
                          │
                          ▼
              [0.0198, -0.0774, ... ]  ← 384 numbers
                          │
                          ▼
      "Postgres, give me the 20 rows whose embedding is
       closest to this one"                       ← pgvector does this
                          │
                          ▼
      20 rows of text, most of them coffee-ish
                          │
                          ▼
      sent to Claude, along with the question and instructions
                          │
                          ▼
      "You spent $87.43 across 14 coffee purchases..."
```

**The critical detail:** the same model must embed both the stored rows and the
question. Two different models produce coordinates on two different maps, and
comparing positions across them is meaningless. That's why `EMBEDDING_MODEL` is a
config value and why changing it means re-embedding everything.

### 4.6 Where RAG breaks — and why this repo has a router

Now the part most tutorials skip, and the reason `rag/router.py` exists.

Ask **"what's my net worth?"** Follow the loop above: the question gets embedded,
the 20 nearest holdings come back, they get sent to Claude, and Claude adds them
up and states a number with total confidence.

**That number is wrong.** You have 60 positions. It summed 20 of them. Nothing in
the process flags a problem — the retrieval worked exactly as designed, and the
answer is fluent, specific, and false.

The failure is fundamental, not a tuning problem. Semantic search answers *"which
rows are most like this?"* Some questions need *"every row, no exceptions."* Those
are different operations, and no amount of increasing `k` fixes it in general.

So this project **classifies the question before answering it**:

- **Aggregate-shaped** — "net worth", "total", "how much did I", "allocation",
  "average", "monthly", "compared to". These skip vector search entirely and run
  real SQL: `SUM`, `GROUP BY`, over *all* rows. Postgres computes the number.
- **Lookup-shaped** — "what was that charge from Chipotle?", "did I pay for
  parking at the airport?". These need a few specific rows out of thousands.
  Vector search is exactly right.

`rag/router.py` does this with a list of regular expressions — no AI, no API call,
free and instant. If it sees "net worth" or "total" or "how much did I," it routes
to SQL. Otherwise, vectors.

And on the SQL path, the numbers arriving at Claude are already computed. The
system prompt says so explicitly (`rag/llm.py:18`):

> *Any figure labeled as a total or aggregate was already computed in SQL. Use it
> as given; do not recompute or re-add the underlying rows.*

**The principle worth taking away: let the database do arithmetic, and let the
language model do language.** LLMs are excellent at phrasing and terrible at being
trusted with sums. Postgres is the opposite. The router is what keeps each doing
the thing it's good at.

The response from `/chat` includes which route it took, so you can always see which
path produced an answer:

```json
{"answer": "...", "route": "aggregate", "rows_used": 47}
```

---

## 5. Following one transaction all the way through

Concrete walkthrough. One row, from bank website to database. This is the row from
the test fixture:

```csv
Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit
2026-03-04,2026-03-05,1234,CHIPOTLE MEXICAN GRILL,Dining,42.10,
```

### Stage 1 — You drop the file

```bash
cp ~/Downloads/transactions.csv ~/projects/finsight/inbox/capital_one/march.csv
```

**The folder you choose is meaningful.** Putting it in `capital_one/` is how the
program knows it's a Capital One file. There's no inspecting the file to guess.
This is why the parsers only need to detect *format*, never institution.

Through the bind mount, the container now sees `/inbox/capital_one/march.csv`.

### Stage 2 — You trigger a run

```bash
curl -X POST localhost:8000/ingest
```

FastAPI routes this to `trigger_ingest()` in `api/routes/ingest.py:14`, which calls
`ingest_inbox()` in `ingestion/pipeline.py:33`. Everything below happens inside
that one function.

### Stage 3 — Scan and dispatch

The pipeline walks each institution folder (`pipeline.py:38`). For each file it
finds, it asks two questions:

**"Have I already done this one?"** — `_already_ingested()` at `pipeline.py:89`
checks the `ingestion_log` table for a successful run on that filename. If found,
skip.

> ⚠️ This check is **filename-only**. Capital One names every export the same
> thing, so your second month's file gets silently skipped. Rename each export
> with a date — `capital_one_2026-03.csv` — until this is fixed.

**"What parser handles this?"** — `resolve()` in `ingestion/registry.py:44` looks
up the folder in a dictionary:

```python
"capital_one": [CapitalOneCSVParser, CapitalOnePDFParser],
```

and picks the first one whose declared extensions match `.csv`. That's
`CapitalOneCSVParser`.

### Stage 4 — Parse

`parsers/capital_one.py:37` runs. It:

1. Reads the CSV with pandas, lowercasing all the column names
2. **Verifies the layout is what it expects** — if `transaction date` or
   `description` is missing, it raises an error that *lists the columns it actually
   found*. That error message is designed to be pasted to whoever is fixing the
   parser.
3. Converts each row into a `NormalizedTransaction` — the universal shape defined
   in `ingestion/base.py:17`, which every parser for every institution produces.

For our Chipotle row:

| CSV field | Becomes | Note |
|---|---|---|
| `2026-03-04` | `txn_date` | parsed into a real date object |
| `2026-03-05` | `posted_date` | |
| `CHIPOTLE MEXICAN GRILL` | `description` | |
| `Debit: 42.10` | `amount = -42.10` | **sign flipped** |
| `Dining` | `category = "dining"` | Capital One's own label, kept |

**The sign convention** (`models.py:38`) is one rule applied everywhere: negative
is money out, positive is money in. Capital One uses two separate columns instead
of a sign, so the parser translates. Every parser is responsible for this
translation — which is what makes `SUM(amount)` meaningful across five institutions
that all disagree about how to represent an outflow.

**Parsers do nothing else.** No database access, no hashing, no embedding. That's
deliberate: it means a parser can be tested with one small file and no
infrastructure, which is exactly what `tests/test_capital_one_parser.py` does.

### Stage 5 — Deduplicate

Now in `_persist()` (`pipeline.py:101`). For each parsed transaction, a fingerprint
is computed (`ingestion/dedup.py:19`):

```
"Capital One|2026-03-04|-42.10|CHIPOTLE MEXICAN GRILL"  →  sha256  →  "a3f9c2..."
```

If that fingerprint already exists in the database, the row is skipped as a
duplicate.

**Why this matters more than it looks.** Capital One's CSV only goes back 90 days,
but its PDF statements go back 7 years. So the plan is CSV for recent data, PDFs
for history — which guarantees the same transaction arrives twice, in two different
renderings. The CSV might say `CHIPOTLE MEXICAN GRILL 887766554` while the PDF says
`Chipotle  Mexican Grill`.

So before hashing, the description is **normalized** (`dedup.py:13`): uppercased,
trailing reference numbers stripped, runs of whitespace collapsed. Both renderings
collapse to the same string, produce the same hash, and become one row.
`tests/test_dedup_and_routing.py:10` pins exactly this behavior.

The `dedup_hash` column also has a **unique constraint** in the database, so even
if the application logic somehow missed it, Postgres refuses the duplicate.

> ⚠️ The flip side: the check only looks at rows *already in the database*, not at
> other rows in the same file. Two genuinely identical charges on the same day —
> two $3.50 coffees at the same shop — produce the same hash, and the unique
> constraint rejects the whole batch. Known issue, small fix.

### Stage 6 — Categorize

`pipeline.py:118`:

```python
category=txn.category or categorize(txn.description)
```

If the parser already produced a category, use it. Otherwise run
`classification/rules.py:31`, which tests the description against an ordered list
of regular expressions and returns the first match — `CHIPOTLE|STARBUCKS|DOORDASH|…`
→ `"dining"`, and so on. No match returns `None`, which is honest: the row stays
uncategorized rather than getting a wrong label.

For Capital One the `or` short-circuits, because Capital One ships its own merchant
categories.

> ⚠️ This creates a taxonomy split. Capital One's labels ("Other Services",
> "Merchandise") and the rule labels ("subscriptions", "groceries") are different
> vocabularies, so a spending breakdown will contain both. Netflix arrives as
> `other services` rather than `subscriptions`. Worth reconciling later.

### Stage 7 — Embed

`pipeline.py:146`. Each row is rendered as a line of text
(`rag/embeddings.py:27`):

```
2026-03-04 | Capital One | dining | $-42.10 | CHIPOTLE MEXICAN GRILL
```

and the whole file's worth of lines goes through the model **in one batch** — the
model has meaningful per-call overhead, so one call with 200 lines beats 200 calls.

That text format is doing double duty: it's what gets embedded *and* it's what
Claude will eventually read. That's why it's human-readable and self-describing
rather than compact.

### Stage 8 — Insert

`pipeline.py:161`. All rows are written to Postgres in one transaction, and one row
is added to `ingestion_log` recording the filename, the parser used, the status,
how many rows were inserted, how many were duplicates, and any warnings.

That log is the audit trail. When an ingest silently does nothing, it's the first
place to look:

```bash
curl localhost:8000/ingestion-log | python3 -m json.tool
```

### Stage 9 — It's queryable

```bash
curl "localhost:8000/transactions?category=dining&start=2026-03-01"
```

And it's now one of the rows that vector search can find.

---

## 6. What happens when you ask a question

```bash
curl -X POST localhost:8000/chat -H 'content-type: application/json' \
  -d '{"question": "How much did I spend on dining last month?"}'
```

**Step 1 — Route** (`api/routes/chat.py:15`). `route()` checks the question against
the aggregate patterns. "How much did I" matches → **aggregate**.

**Step 2a — The aggregate path** (`rag/retrieval.py:61`). No vector search at all.
Three SQL queries run against *all* rows:

- Latest holding per (institution, ticker), summed → total investment value, plus
  each position's percentage
- `SUM(amount) GROUP BY category` → spend by category
- `SUM(amount) GROUP BY month` → net cash flow per month, last 12

Each result becomes a plain sentence:

```
Spend by category: dining = $-412.88 (17 txns)
Net cash flow 2026-03: $-2,104.55
Total investment market value (latest snapshot per position): $84,201.19
```

**Step 2b — The semantic path** (`rag/retrieval.py:11`). For lookup-shaped
questions instead: embed the question, fetch the 20 nearest transactions and 10
nearest holdings by cosine distance, render them as text lines.

**Step 3 — Ask Claude** (`rag/llm.py:31`). Either way, you end up with a list of
text lines. They're wrapped in tags and sent with the question:

```
<data>
Spend by category: dining = $-412.88 (17 txns)
Net cash flow 2026-03: $-2,104.55
...
</data>

Question: How much did I spend on dining last month?
```

Plus the system prompt (`llm.py:9`), which is where the guardrails live:

- Answer **only** from the provided rows
- If the rows don't contain the answer, **say so** and name what's missing
- Cite specific numbers; never estimate or extrapolate
- Totals were already computed in SQL — use them as given, don't recompute
- Negative is money out, positive is money in

**Step 4 — Respond.** You get back the answer, the route taken, and how many rows
were used. `route` and `rows_used` are your debugging surface: an answer that seems
off with `"route": "semantic"` usually means the router misclassified an aggregate
question, and the fix is a pattern in `router.py`, not a prompt change.

**What this costs.** Embedding is free and local. The only paid call is Step 3 —
one request, a few thousand words. Fractions of a cent per question.

---

## 7. Five design decisions worth understanding

**1. The folder is the institution.** Dispatch is driven by which subfolder you
drop a file into, not by inspecting its contents. Content-sniffing five
institutions' formats would be fragile and would need updating every time a bank
changed a header. Choosing a folder is unambiguous and takes you one second.

**2. Dedup is what makes the two-source strategy safe.** Recent data comes from
CSVs, history from PDFs, and they overlap. Without normalize-then-hash, backfilling
would duplicate everything. This is why `dedup.py` strips reference numbers before
hashing — that's not a detail, it's the thing that makes the whole ingestion
strategy viable.

**3. Route before you retrieve.** Covered in 4.6. The single most important idea in
the project: aggregate questions get SQL, lookup questions get vectors, and the LLM
never does arithmetic.

**4. `inbox/` is mounted read-only.** `docker-compose.yml:43`. The pipeline can
read your statements and cannot alter or delete them. A bug in a parser can produce
bad database rows — recoverable — but can't touch your original files.

**5. Parsers are pure functions.** File in, normalized records out. No database, no
network, no hashing. Every parser is testable with one small fixture file, which is
why you can verify the Capital One parser without Postgres running at all.

---

## 8. Every file in the repo

```
docker-compose.yml          Defines both containers, the network, mounts, volumes
Makefile                    Shortcuts: make up / logs / db / test / ingest / health
.env                        Your secrets and settings (gitignored, never committed)
.env.example                Template for .env, safe to commit
FinSight-Design-Plan.md     The original plan this was built from
README.md                   Quick start and status
docs/DATA-SOURCES.md        Research on all 5 institutions' export formats — read
                              this before writing any parser
docs/HOW-IT-WORKS.md        This document

db/init/01_init.sql         Enables the pgvector extension. Runs once, ever.

inbox/                      Drop zone. One folder per institution. Gitignored.
  capital_one/  dcu/  vanguard/  fidelity/  morgan_stanley/

backend/
  Dockerfile                How the API image is built
  pyproject.toml            Python dependencies

  app/
    main.py                 Starts FastAPI, creates tables, seeds institutions
    config.py               Reads environment variables into a typed Settings object
    db.py                   Database connection and session management
    models.py               ★ The four tables. Start here to understand the data.
    schemas.py              API request/response shapes

    api/routes/
      health.py             GET /health
      ingest.py             POST /ingest, GET /ingestion-log
      transactions.py       GET /transactions
      holdings.py           GET /holdings
      analytics.py          GET /net-worth, GET /allocation
      chat.py               POST /chat  ← 8 lines; the logic is in rag/

    ingestion/
      base.py               ★ The parser contract every parser implements
      registry.py           Folder + extension → which parser
      dedup.py              Fingerprinting, so re-dropping a file is a no-op
      pipeline.py           ★★ The orchestrator. The most important file here.
      parsers/
        capital_one.py      ✅ CSV implemented + tested. PDF is a stub.
        dcu.py              🚧 Stub. Next to be written.
        vanguard.py         🚧 Stub. Multi-section CSV — read the docstring.
        fidelity.py         🚧 Stub.
        morgan_stanley.py   🚧 Stub. Excel, not CSV.

    classification/
      rules.py              Regex → category. The Phase 1 categorizer.

    rag/
      embeddings.py         ★ Text → 384 numbers. Local, free.
      router.py             ★ Aggregate vs semantic. The key routing decision.
      retrieval.py          ★ Vector search + the SQL rollups
      llm.py                The Claude call and the system prompt

  tests/
    fixtures/capital_one_sample.csv    4 synthetic rows, no real data
    test_capital_one_parser.py         Parser correctness
    test_dedup_and_routing.py          Dedup collision + router classification
```

**If you read four files, read these:** `models.py` (the data), `pipeline.py` (the
flow), `rag/router.py` (the key idea), `rag/retrieval.py` (both query paths).

---

## 9. What's built and what isn't

| | Status |
|---|---|
| Docker setup, Postgres + pgvector | ✅ Done |
| Database schema, auto-created at startup | ✅ Done |
| Ingestion pipeline (scan→parse→dedup→classify→embed→insert) | ✅ Done |
| Capital One CSV parser | ✅ Done, tested |
| Dedup with cross-format normalization | ✅ Done, tested |
| Rule-based categorizer | ✅ Done |
| REST endpoints | ✅ Done |
| RAG chat with routing | ✅ Built, not yet tested on real data |
| DCU parser | 🚧 Stub — next |
| Vanguard / Fidelity / Morgan Stanley parsers | 🚧 Stubs — Phase 2 |
| All PDF parsers | 🚧 Stubs — backfill, Phase 2 |
| Cash balances in net worth | ⬜ Needs the DCU parser first |
| scikit-learn categorizer | ⬜ Phase 2 — needs labeled data first |
| Scheduled jobs (weekly summary, anomaly detection) | ⬜ Not started |
| React frontend | ⬜ Phase 3 |

**Known issues to fix soon** (all flagged with ⚠️ above):

1. `pipeline.py:89` skips files by name only → same-named exports get silently
   ignored. Workaround: date-stamp your filenames.
2. `pipeline.py:101` doesn't dedup within a single file → two identical same-day
   charges cause the whole ingest to fail.
3. Capital One's categories and the rule categories are different vocabularies.

---

## 10. Glossary

**API** — A way for programs to talk to each other over HTTP. You send a request to
a URL, you get structured data back.

**Bind mount** — A folder on your Mac made visible inside a container. Same folder,
two names. Changes on either side are instantly visible on the other.

**Container** — An isolated mini-computer with its own filesystem and installed
software, running on your machine.

**Cosine distance** — A way of measuring how different two embeddings are, based on
the angle between them. Small = similar meaning.

**Dedup hash** — A fingerprint of a transaction, used to recognize the same
transaction arriving twice in different formats.

**Embedding** — A list of numbers (384 here) representing the *meaning* of a piece
of text, such that similar meanings produce numerically similar lists.

**Endpoint** — One URL your API responds to, like `/transactions`.

**Image** — A snapshot of a filesystem that containers are created from.

**LLM** — Large Language Model. Claude is one. Generates text.

**ORM** — Object-Relational Mapper. Lets you write Python instead of SQL.

**pgvector** — A PostgreSQL extension that adds a vector column type and distance
functions, letting one database hold both your structured data and your embeddings.

**RAG** — Retrieval-Augmented Generation. Search your own data for relevant pieces,
give those pieces to an LLM, have it write the answer.

**Semantic search** — Search by meaning rather than by matching letters. Finds
Starbucks when you search for coffee.

**System prompt** — Standing instructions given to an LLM before the user's
question. Where this project's "don't do arithmetic" rules live.

**Vector** — A list of numbers. In this context, an embedding.

**Volume** — Docker-managed storage that persists after a container is deleted.
Where your database actually lives.
