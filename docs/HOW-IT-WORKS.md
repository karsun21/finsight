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
8. [Keeping code, schema, and machines in sync](#8-keeping-code-schema-and-machines-in-sync)
9. [Every file in the repo](#9-every-file-in-the-repo)
10. [What's built and what isn't](#10-whats-built-and-what-isnt)
11. [Glossary](#11-glossary)

---

## 1. What FinSight is

You have money in five places: a checking account at DCU, a Capital One credit
card, a Vanguard brokerage account, a Fidelity 401(k), and Morgan Stanley ESPP
shares. Each one has its own website, its own login, its own idea of what a
"transaction" looks like. None of them talk to each other. If you want to know
what you spent on dining last quarter, or how much of your net worth is tied up in
your employer's stock, you're opening five tabs and doing arithmetic by hand.

FinSight is a program that:

1. **Reads** the files those institutions let you download
2. **Normalizes** them — turns different formats into one consistent shape
3. **Stores** them in a single database on your laptop
4. **Answers questions about them in plain English**

That last part is the interesting one, and it's where RAG comes in.

### 1.1 Scope: one source automated, the rest entered by hand

The five institutions are **not** treated equally, and that's a deliberate
decision rather than unfinished work.

| | Institutions | How data arrives | Why |
|---|---|---|---|
| **Automated** | Capital One (credit) | CSV → `inbox/` → parser → `transactions` | This is where *spending* lives, it changes daily, and it's thousands of rows. Automation earns its keep. |
| **Manual** | Vanguard, Fidelity, Morgan Stanley | A holdings snapshot entered by hand, quarterly | These are *balances*, not events. They move slowly, they're a handful of rows, and their export formats are the three worst in the set. |

The reasoning: parsers three, four, and five would add no new architecture — each
is another "read a file, rename the columns, flip a sign." They'd also be the most
expensive ones to write. Vanguard's CSV has multiple sections stacked in one file.
Morgan Stanley is `.xlsx` and needs two separate reports. Fidelity's CSV is
activity-only, so the per-fund 401(k) balances that actually matter for net worth
exist **only** in a quarterly PDF statement.

Against that: a 401(k) balance changes slowly, and you care about it four times a
year. Hand-entering a few rows a quarter beats writing and maintaining a PDF
parser to extract the same numbers.

**This does not drop net worth from the project.** The `holdings` table
(`models.py:52`) is already keyed on `(institution, as_of_date, ticker)` —
explicitly designed as point-in-time snapshots, with net worth over time being a
series of them. It does not care whether a snapshot came from a parser or from
you typing it. Every downstream feature — `/net-worth`, `/allocation`, the SQL
rollups the chat router uses — works identically either way.

**What this scope also removes,** and shouldn't be reintroduced without a reason:

| Dropped | Why |
|---|---|
| The scikit-learn categorizer | Target granularity is coarse — "dining", "travel", "groceries", not "coffee specifically". ~15 regex rules cover that. An ML model earns its place only at fine granularity. |
| Two-stage "semantic filter → SQL aggregate" retrieval | It existed to answer "how much on coffee" when coffee isn't a category. At coarse granularity every spending question is a `GROUP BY category`, which the aggregate path already does correctly over *all* rows. |
| PDF parsers, all institutions | Optional historical backfill. Nothing in the target scope needs them. |

The semantic/vector path stays — see §4.6 for what its job actually is now.

**What this scope makes *more* important:** the category taxonomy. When the
product is coarse buckets, the bucket labels *are* the product. The taxonomy is
`CATEGORIES` in `classification/rules.py`, and Stage 6 of §5 explains how a row
gets assigned to one.

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
| `institutions` | Five rows, one per bank. Seeded automatically at startup (`registry.py:28`). All five stay seeded even though only two are automated — the investment institutions still own their manually-entered holdings. |
| `transactions` | One row per purchase, payment, deposit — money moving. Fed by Capital One. |
| `holdings` | One row per investment position at a point in time — money sitting. Fed by hand, quarterly. |
| `ingestion_log` | One row per file processed, including its content hash. Audit trail *and* the "have I seen this file?" check. |

The `transactions` / `holdings` split matters, and it's what makes the scope
decision in §1.1 cheap. A transaction is an *event* ("on March 4th, $42.10 left my
account"). A holding is a *snapshot* ("as of March 31st, I owned 12.4 shares of
VTSAX worth $1,800"). Net worth comes from holdings; spending comes from
transactions. Different shapes, different questions, different tables — and
different rates of change, which is exactly why one side is worth automating and
the other isn't.

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
Python classes *and* the schema definition. The database's actual shape is applied
from Alembic migrations, which run in the container command before the server
starts; see §8 for why `create_all()` was not good enough.

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

### scikit-learn — vestigial, slated for removal

**What it is.** A classical machine-learning library.

**Why it's here.** It isn't, anymore. It's still listed in
`backend/pyproject.toml:20` from when the plan included training a categorizer on
your hand-corrections, but the scope decision in §1.1 dropped that. Nothing
imports it. Categorization is a list of regular expressions in
`classification/rules.py`, and at coarse granularity that's sufficient — an ML
model earns its place when you need "coffee" separated from "dining", and you
don't.

Dropping the dependency would meaningfully shrink the Docker image. Left in for
now because the image is already built and cached.

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

### 4.7 What the semantic path is actually for here

Section 4.2 used *"how much do I spend on coffee?"* to motivate embeddings,
because it's the cleanest illustration of why matching letters fails. Keep the
lesson, but note that it is **no longer a question this project targets** — under
the coarse-category scope (§1.1), coffee isn't a category, and "how much" routes
to SQL anyway.

So what does the semantic path earn its place doing? **Lookup, not totals:**

- *"What was that charge from Chipotle?"*
- *"Did I pay for parking at the airport in March?"*
- *"What's that recurring thing that starts with SQ?"*

These need a handful of specific rows pulled out of thousands, identified by
meaning rather than by an exact string you'd have to already know. That's what
vector search is genuinely good at, and it's why the path stays even though the
headline features route around it.

The distinction to hold onto: **semantic search is for finding rows, SQL is for
counting them.** Both are here because both jobs exist.

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

**"Have I already done this one?"** — the file's **contents** are sha256'd
(`dedup.py`, `file_hash()`), and `_already_ingested()` checks the `ingestion_log`
table for a successful run carrying that hash. If found, skip.

Contents rather than filename, because Capital One names every export
`transactions.csv`. A name-based check — which is what this used to be — meant the
second month's download looked like one already processed and was silently
skipped: `files_seen` incremented and nothing else happened. Hashing the bytes
gets both directions right:

- A **renamed copy** of a file already ingested → same hash → skipped, no work.
- A **same-named file with different rows** → different hash → processed.

Date-stamping your exports on the way in is still a good habit for your own sake,
but it's no longer load-bearing.

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

**The identical-charges problem.** Two $3.50 coffees at the same shop on the same
day are indistinguishable under that fingerprint — same institution, same date,
same amount, same description. Both are real charges, so neither of the obvious
answers is acceptable: letting them collide makes the unique constraint reject the
entire batch, and dropping the second understates your spending.

So the **occurrence index within the file** becomes part of the key
(`dedup.py`, `occurrence_hash()`). The first identical row hashes to the base
digest unchanged; the second hashes `base#1`; the third `base#2`.

The subtle part is *where the index comes from*. It's counted per file, not from
what's already in the database. That's what keeps re-ingestion idempotent:

| | Occurrence indices generated | Result |
|---|---|---|
| Drop a file with two coffees | 0, 1 | both inserted |
| Drop the **same file again** | 0, 1 | both found, both skipped ✓ |
| Later file overlaps, has both | 0, 1 | both found, both skipped ✓ |
| Earlier file had one, later has two | 0, 1 | first skipped, second inserted ✓ |

Had the index been derived from the database instead, the second ingest would see
occurrence 0 taken, insert at occurrence 1, and duplicate the very row it was
supposed to recognize.

Holdings work differently on purpose: one position per (institution, snapshot
date, ticker) is the entire point of that key, so a repeat inside one file is a
malformed statement rather than a second real position. Those are skipped and
counted as duplicates.

### Stage 6 — Categorize

`pipeline.py:118`:

```python
category=resolve_category(txn.description, txn.category)
```

Two things can suggest a category: the merchant description, and whatever label
the issuer shipped in its own export. `resolve_category()` in
`classification/rules.py` decides between them, in this order:

1. **Description rules first.** An ordered list of regular expressions, first
   match wins — `CHIPOTLE|STARBUCKS|DOORDASH|…` → `"dining"`.
2. **Issuer label as fallback,** mapped through `ISSUER_CATEGORIES` onto the
   project's own vocabulary (`merchandise` → `shopping`, `airfare` → `travel`).
3. **`None`.** No match anywhere. This is a real answer, not a failure — an
   uncategorized row is recoverable, a confidently wrong bucket silently
   corrupts every spending total that follows.

**Why descriptions beat the issuer.** This used to read
`txn.category or categorize(...)`, which looks harmless and was the worst bug in
the project. Capital One ships a category on every row, so the `or` short-circuited
and the rules *never ran at all* for card transactions. Two vocabularies ended up
in one column: `KROGER #421` was filed as `merchandise` instead of `groceries`,
`NETFLIX.COM` as `other services` instead of `subscriptions`. Under the
coarse-category scope (§1.1) **category is the entire product** — every spending
question is a `GROUP BY category` — so issuer labels being the wrong vocabulary
isn't cosmetic.

Some issuer labels map to nothing on purpose. `other`, `other services`, and
`professional services` are grab bags carrying no real signal, so they're recorded
as an explicit `None` in the map. That's deliberately distinct from a label that's
simply *missing* from the map — an unrecognized label gets logged once with a
warning, so when your real export contains a category we've never seen you find
out from the logs instead of from a pile of silent NULLs.

> ⚠️ **Timing:** the resolved category is baked into the text that gets embedded
> in Stage 7, so changing categorization rules after ingesting means
> **re-ingesting**, not just an `UPDATE`. Get the taxonomy roughly right before
> loading real history.

**One trap worth knowing about, because it will come back.** The rules match
against the uppercased description with `re.search`, so a short pattern matches
*inside longer words*. Every one of these was live at some point:

| Pattern | Silently matched | Result |
|---|---|---|
| `MTA` | `CAPITAL ONE MOBILE PY`**`MTA`**`UTHDATE` | a card payment counted as transport |
| `ATM` | `SPINE TRE`**`ATM`**`ENT CENTER` | a medical bill counted as a cash withdrawal |
| `ACH` | `CO`**`ACH`** ` OUTLET`, `BE`**`ACH`** ` CLUB` | retail counted as a transfer |
| `FEE` | `PEETS COF`**`FEE`** | coffee counted as a bank fee |
| `RENT` | `AVIS `**`RENT`**` A CAR` | a rental car counted as housing |

All five are now `\b`-anchored, and `tests/test_categorization.py` pins each one.
The failure mode is what makes this nasty: nothing errors, the row just lands in
the wrong bucket and the totals are quietly wrong.

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

**2. Dedup is what makes overlapping exports safe.** Capital One's CSV export is
capped at ~90 days, so you pull it month by month and the windows overlap — the
same charge arrives in two files. Without normalize-then-hash you'd double-count
every overlap. (The original motivation was CSV-vs-PDF backfill, where the same
transaction renders differently in each format; PDFs are now optional per §1.1,
but overlapping CSV windows keep the requirement alive either way.) This is why
`dedup.py` strips trailing reference numbers before hashing — not a detail, it's
what makes re-dropping a file a no-op instead of a corruption.

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

## 8. Keeping code, schema, and machines in sync

Two tools in this repo exist for the same underlying reason: **things that live
outside your code can quietly drift away from it.** Alembic keeps the database's
shape in step with `models.py`. GitHub Actions keeps your laptop in step with
every other machine. Both were added after a real incident, and both catch a class
of bug whose defining feature is that nothing errors when it happens.

### Alembic — version control for the database schema

Your code is in git. Your database is not. That gap is the whole problem.

**What the project did before.** On startup it called
`Base.metadata.create_all()`, which means: *look at `models.py`, and create any
table that does not exist yet.* That works perfectly until you change a table that
already exists — because `create_all` only ever **creates**. It never **alters**.

Add a column to a table that is already there and `create_all` sees the table,
decides there is nothing to do, and returns. No error. No warning. Your Python now
believes in a column the database has never heard of, and you find out at the
first query that touches it. This happened here once already, when `file_hash` was
added to `ingestion_log`.

**What Alembic does instead.** Every schema change becomes a numbered file in
`backend/alembic/versions/` with an `upgrade()` that applies it and a
`downgrade()` that undoes it. The database records which revision it is currently
on, in a table called `alembic_version`. `alembic upgrade head` means "apply
whatever revisions this database has not seen yet."

Schema history now lives in the repo, in order, reviewable in a diff — like
commits, but for table structure:

```
1a47c85fc709   baseline schema        the four tables as they already existed
9aebc89a15f0   add issuer_category    keeps the issuer's own label per row
```

**Two steps that look strange the first time.** *Stamping* was needed because this
database already had its tables, built by `create_all`. Running the baseline
against it would have failed — you cannot create tables that exist. So the version
row was written directly: "you are already at `1a47c85fc709`." That is a claim, and
a claim can be wrong, which is what `alembic check` is for: it compares `models.py`
against the live schema and reports `No new upgrade operations detected` only if
they genuinely agree. Stamping without checking would have baked in any drift
invisibly.

**One gotcha specific to this project.** The `embedding` columns are pgvector's
`Vector` type. Autogenerate renders them as
`pgvector.sqlalchemy.vector.VECTOR(dim=384)` but does *not* add the import, so
every migration touching one would fail with `NameError`. `alembic/script.py.mako`
— the template new migrations are generated from — adds that import permanently.

**Day to day:**

```bash
docker compose exec api alembic revision --autogenerate -m "what changed"
docker compose exec api alembic upgrade head
docker compose exec api alembic current   # which revision is this database on
docker compose exec api alembic check     # do the models match the schema
```

Autogenerate *proposes*; it does not decide. Read the generated file before
applying it.

### GitHub Actions — running the checks on a machine that is not yours

**Continuous integration** is simply the practice of checking every change
automatically. GitHub Actions is GitHub's way of doing it: you write a config file
(`.github/workflows/tests.yml`), and on every push GitHub boots a **brand-new
Ubuntu machine**, follows your steps in order, reports pass or fail, and throws the
machine away.

**The freshness is the entire point**, and this project supplies the perfect
illustration. The test suite passed for weeks. But pytest was never in the Docker
image — `pip install -e .` installs the main dependencies and skips the `[dev]`
extras. Some earlier session had installed pytest by hand inside a running
container, where it sat invisibly until that container was recreated and the tests
abruptly could not run at all.

On the machine where it was written, everything looked fine. On a fresh clone, the
command this project's own docs call *the* way to run tests would have failed
immediately. A clean machine cannot accumulate that kind of hidden state.

**What the workflow does**, in order: starts a Postgres with pgvector, installs the
real dependency set exactly as the Dockerfile does, applies the migrations to an
empty database, checks for drift, runs pytest. The whole run takes about two
minutes.

Two of those steps are worth more than they look:

- **Migrations against an empty database** proves they can build the schema from
  nothing, on hardware that has never seen this project. That is hard to prove on
  your own machine, because your database already has the tables — it is why the
  baseline had to be generated against a throwaway database in the first place.
- **`alembic check`** fails the build if someone edits `models.py` without
  generating a migration. Drift is caught in seconds instead of surfacing weeks
  later — which is exactly how the stale-categories bug happened, where the rules
  were correct in the file and the database was three weeks behind them.

The badge at the top of `README.md` is an image GitHub serves reflecting the latest
result.

**The one-line version: Alembic stops your schema drifting from your code, and CI
stops your machine drifting from everyone else's.** Both convert a failure that is
late, silent, and confusing into one that is early, loud, and obvious.

---

## 9. Every file in the repo

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
  capital_one/                ← the only automated source
  vanguard/  fidelity/  morgan_stanley/   ← kept but unused; see §1.1

.github/workflows/
  tests.yml                 CI: migrations from empty, drift check, tests — see §8

backend/
  Dockerfile                How the API image is built
  pyproject.toml            Python dependencies
  alembic.ini               Alembic config; the URL is set in env.py, not here
  alembic/
    env.py                  Takes the database URL from app.config — see §8
    script.py.mako          Template new migrations are generated from
    versions/               ★ One file per schema change, in order

  app/
    main.py                 Starts FastAPI, seeds institutions, serves the UI at /
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
        capital_one.py      ✅ CSV, implemented and tested — the only parser.
                              The DCU, Vanguard, Fidelity and Morgan Stanley
                              stubs were deleted 2026-09-01; they had never run.
                              Their export formats live in docs/DATA-SOURCES.md.

    classification/
      rules.py              Regex → category. The Phase 1 categorizer.

    rag/
      embeddings.py         ★ Text → 384 numbers. Local, free.
      router.py             ★ Aggregate vs semantic. The key routing decision.
      retrieval.py          ★ Vector search + the SQL rollups
      llm.py                The Claude call and the system prompt

    static/
      index.html            The chat UI, served at GET /. One self-contained
                              file — no build step, no framework, no CDN.

  tests/
    fixtures/capital_one_sample.csv    4 synthetic rows, no real data
    test_capital_one_parser.py         Parser correctness
    test_dedup_and_routing.py          Dedup collision + router classification
```

**If you read four files, read these:** `models.py` (the data), `pipeline.py` (the
flow), `rag/router.py` (the key idea), `rag/retrieval.py` (both query paths).

---

## 10. What's built and what isn't

Everything marked ✅ has actually been run end to end on this machine, against a
synthetic fixture. **The database is currently empty** — no real financial data has
been ingested yet.

| | Status |
|---|---|
| Docker setup, Postgres + pgvector | ✅ Done |
| Database schema, auto-created at startup | ✅ Done |
| Ingestion pipeline (scan→parse→dedup→classify→embed→insert) | ✅ Done |
| Capital One CSV parser | ✅ Done, tested |
| Dedup with cross-format normalization | ✅ Done, tested (both layers) |
| Rule-based categorizer, 17-bucket taxonomy | ✅ Done, tested — rules beat issuer labels, `travel` bucket added |
| REST endpoints | ✅ Done |
| RAG chat with routing | ✅ Both routes verified on synthetic data |
| DCU / Vanguard / Fidelity / Morgan Stanley parsers | ⬜ Descoped — stubs deleted 2026-09-01, see §1.1 |
| Manual holdings entry (Vanguard / Fidelity / Morgan Stanley) | ⬜ Not started — the remaining half of net worth |
| Cash balances in net worth | ⬜ Descoped with the DCU parser |
| Vanguard / Fidelity / Morgan Stanley parsers | ⬜ Descoped, see §1.1 |
| All PDF parsers | ⬜ Descoped — optional backfill only |
| scikit-learn categorizer | ⬜ Dropped, see §1.1 |
| Scheduled jobs (weekly summary, anomaly detection) | ⬜ Not started |
| React frontend | ⬜ Phase 3 (blocked locally: Node 16, Vite needs 18+) |

**Known issues, in priority order** (all flagged with ⚠️ above):

1. ~~`pipeline.py:118` — Capital One's categories bypass the rule categorizer.~~
   **Fixed.** Rules now run first and the issuer label is a mapped fallback;
   `travel` and `insurance`/`entertainment` buckets added; five substring
   mismatches found and anchored along the way. See Stage 6 of §5.
2. ~~`pipeline.py:89` skips files by name only.~~ **Fixed.** The check is now a
   sha256 of file contents, recorded in `ingestion_log.file_hash`. See Stage 3.
3. ~~`pipeline.py:101` doesn't dedup within a single file.~~ **Fixed.** Identical
   same-day charges are stored at successive occurrence indices instead of
   colliding, and persistence is now wrapped so a constraint violation logs a
   failed file rather than 500-ing the run and abandoning the rest of the inbox.
   See Stage 5.
4. **Semantic path truncates silently** — `retrieval.py` returns exactly
   `retrieval_top_k` (20) rows with no signal that more matched, so Claude can sum
   20 of 30 relevant rows and state a confident wrong total. Cheap mitigation: when
   the result length equals `k`, tell the LLM the list was truncated. Lower
   priority now that coarse questions route to SQL.
5. **`/net-worth` excludes cash and says so** (`includes_cash: false`). Correct
   behavior, but net worth stays incomplete until the manual holdings
   snapshots exist.

**One structural risk worth naming:** `aggregate_facts()` in `rag/retrieval.py`
has no test coverage at all, and every test in the suite is pure-unit — there is
no database fixture to build one on. That function supplies every number the model
speaks, and the gap is how a monthly rollup that netted card payments into
spending, and therefore reported a fall as a rise, survived from the day it was
written.

---

## 11. Glossary

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
