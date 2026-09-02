# Demo data

50 synthetic Capital One transactions across three statement exports, so the
project can be run end to end without anyone's real financial data.

Every amount, date, and card number here is invented. Merchant *brands* are real,
because the categorization rules match on them and inventing names would make the
demo categorize nothing — but store numbers and references are made up.

```bash
cp demo/capital_one/demo_*.csv inbox/capital_one/
curl -sS -X POST localhost:8000/ingest
```

Expect `files_seen: 3, files_ingested: 3, rows_ingested: 50`, and **zero
uncategorized rows**.

> ⚠️ The files are named `demo_*.csv` specifically so they cannot collide with a
> real Capital One export, which downloads as `capital_one_<month>.csv`. If you
> already have real statements ingested, this will *add* 50 synthetic rows to
> them and every total afterwards will be a mix of both. Clear the tables first
> if you want a clean demo — see "Removing it again" below.

## Why it looks the way it does

**The window is 2026-04-11 → 2026-07-11**, mirroring real statement cycles, which
run mid-month to mid-month. That makes April and July *partial* calendar months
while May and June are whole — which is the case `_coverage_facts()` exists to
handle. Without it, July's 11 days read as a collapse in spending. Ask "how has my
spending changed month to month?" and the answer will say so.

**Two different merchants contain the word "storage."** Public Storage is a
housing cost; Google One Storage is a subscription. Ask about "the storage place"
and the semantic route finds both and asks which you meant, rather than picking
one and sounding certain.

**Several rows disagree with the issuer's own label**, which is the point of
running description rules ahead of it:

| resolves to | Capital One calls it | rows | why the issuer label is wrong |
|---|---|---|---|
| `transport` | `Other Travel` | 8 | Transit fares sit in the same MCC block as airlines. A subway tap is not a trip. |
| `housing` | `Other Travel` | 3 | Self-storage lands under the same label — the same label, two unrelated answers. |
| `health` | `Entertainment` | 3 | The issuer files a gym beside concert tickets. |
| `subscriptions` | `Internet` | 3 | Google One is cloud storage, not an ISP. |
| `groceries` | `Merchandise` | 6 | Groceries and homewares share one bucket. |

Load it and run this to see that for yourself:

```bash
docker compose exec db psql -U finsight -d finsight -c "SELECT category, issuer_category, count(*) FROM transactions GROUP BY 1,2 ORDER BY 1,3 DESC;"
```

## Removing it again

The demo rows are ordinary transactions, so clearing them is the normal reset:

```bash
rm inbox/capital_one/demo_*.csv
docker compose exec db psql -U finsight -d finsight -c "DELETE FROM transactions; DELETE FROM ingestion_log;"
curl -sS -X POST localhost:8000/ingest
```

The glob is `demo_*` deliberately: it cannot match a real export. Deleting the
rows and re-ingesting is what rebuilds the database from whatever is left in
`inbox/`, because a category is baked into each row's embedding and cannot be
corrected by an `UPDATE`.
