# Data Source Validation

Checked the five institutions in `FinSight-Design-Plan.md` §2 against current
vendor documentation and user reports (August 2026).

**Method and its limit.** These findings come from vendor help pages and
community/tooling documentation, not from your own account exports — there were
no statement or transaction exports on this machine to check against (only two
DCU 1099-INT tax PDFs, which are not transaction data). Treat every "expected
header" note in the parsers as a hypothesis to confirm against your first real
export. Confidence is marked per row below.

---

## Summary

| Source | Design plan said | Verdict | Confidence |
|---|---|---|---|
| DCU | "No native CSV — must parse PDF tables" | **Wrong** — CSV export exists | High |
| Capital One | CSV native (90-day cap) + PDF (7-yr) | **Confirmed** | High |
| Vanguard | CSV native (18-month cap) + PDF | **Confirmed**, plus a format gotcha | High / Medium |
| Fidelity NetBenefits | CSV drops rows, prefer PDF | **Right conclusion, different reason** | Medium |
| Morgan Stanley | "check if migrated to E\*TRADE" | **Yes, migrated** | High |

**The headline consequence:** four of five sources have a working CSV/XLSX path
for recent data. PDF table extraction — the brittlest, highest-effort part of the
build (`camelot` + ghostscript + per-issuer layout tuning) — is *not* on the
Phase 1 critical path. It belongs in Phase 2 as historical backfill. The plan
currently puts DCU PDF parsing in Phase 1 on the mistaken premise that there is
no alternative.

---

## 1. DCU — checking/savings

**The plan's premise is wrong.** DCU Digital Banking exports account history
directly. Reported formats are CSV plus OFX / QFX (Quicken) / QBO (QuickBooks),
though multiple users report that the web interface DCU moved to around March
2022 dropped QFX and now offers CSV only.

eStatements are separately available as **PDF and HTML**, with a **7-year
archive** for both statements and Visa bills — so the PDF path still matters for
history older than whatever Digital Banking will export, just not for the
monthly flow.

⚠️ **Time-sensitive:** DCU merged with First Technology Federal Credit Union on
**January 1, 2026** — the combined institution kept DCU's charter but First
Tech's name. Digital banking platforms usually get consolidated after a merger of
that size, so confirm the export UI still looks the way the docs describe before
investing in a parser. This is the one finding most likely to be stale.

**Action:** implement `DCUCSVParser` first; keep `DCUPDFParser` for backfill.
DCU statements bundle checking, savings, and any loan into one PDF, so the PDF
parser must split by account section before extracting tables.

## 2. Capital One — credit card

**Confirmed as described.** `Download Transactions` on the account activity page
produces a CSV, capped at roughly **90 days** per export — the shortest window of
any major US issuer. PDF statements under *Statements & Documents* go back
**7 years**.

Two operational details the plan does not capture:

- The export is **desktop web only**. The mobile app does not expose it.
- Large date ranges sometimes time out, and the CSV omits running balances and
  statement totals. Pull month by month.

Observed header (implemented in `CapitalOneCSVParser`, verify on your first
export):

```
Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit
```

`Debit` and `Credit` are separate, mutually exclusive columns — there is no
single signed amount column. Capital One also supplies its own merchant category,
which is worth keeping as the initial label instead of re-deriving one.

## 3. Vanguard — brokerage

**18-month cap confirmed** for CSV/OFX downloads (My Accounts → Download Center).

Two things the plan misses:

1. **Format gotcha (medium confidence — verify on your export).** The Vanguard
   download is a *multi-section* CSV: a positions block and a transactions block
   concatenated into one file, separated by a blank line, with different column
   counts. A plain `pd.read_csv()` raises a tokenizing error on it. Split the file
   on blank lines and parse each block separately. This is why
   `VanguardCSVParser` is the one parser that yields both holdings and
   transactions from a single file.
2. **Backfill may not need PDFs at all.** The browser-visible transaction history
   goes back far further than the 18-month download cap (users report ~9 years,
   with custom date screens reaching to 1993). Screen-scraping that table is
   likely less work than parsing statement PDFs.

## 4. Fidelity NetBenefits — 401(k)

**The plan's conclusion — "prefer PDF as source of truth" — is right, but the
reason is more specific than "CSV occasionally drops rows."**

The CSV comes from *Activity & Orders* (pick account and date range → download
icon → CSV). That export reflects the **current account view, not the statement**:
it covers recent activity only, omits running balances, and is not the
comprehensive statement format. So it is a fine incremental transaction feed and
a bad source for balances.

For a 401(k), the authoritative record of contributions, employer match, and
per-fund balances is the **quarterly PDF statement**. That maps cleanly onto the
schema split: CSV → `transactions`, PDF → `holdings`.

Also: Fidelity CSVs append disclaimer text after the data rows. Parse until the
date column stops parsing rather than using a fixed `skipfooter` — the disclaimer
length changes between exports.

## 5. Morgan Stanley — ESPP

**The plan's open question is answered: yes, the migration happened.** Morgan
Stanley acquired E\*TRADE in 2020 and moved most Morgan Stanley at Work stock
plan participants onto the E\*TRADE platform between **2023 and 2025**. Accounts
formerly branded StockPlan Connect, Shareworks, or E\*TRADE stock plan are now
consolidated under Morgan Stanley at Work. **Check which platform your account
actually sits on before writing the parser** — it determines the file format.

On the E\*TRADE platform there are two relevant exports, and the plan's note that
there is "no holdings/gains export natively" is only true of either one alone:

| Report | Path | File | Gives you |
|---|---|---|---|
| Benefit History | At Work → My Account → Benefit History → Download → *Download Expanded* | `BenefitHistory.xlsx` | Purchase/vest/release events |
| Gains & Losses | Stock Plan → My Account → Gains & Losses → select tax year → Download → *Download Collapsed* | `G&L_Collapsed.xlsx` | Per-lot cost basis and gain/loss |

Together they give a full ESPP holdings picture. Both are **`.xlsx`, not CSV** —
`MorganStanleyReleasesParser` accepts `.xlsx`/`.xls`/`.csv` for that reason, and
`openpyxl` is in the dependency list. Expect a title/metadata block above the
real header row; find the header by searching for a known column name rather than
assuming `header=0`.

---

## Recommended changes to the design plan

1. **Rewrite the §2 table row for DCU** — CSV export exists; PDF is backfill only.
2. **Move PDF parsing out of Phase 1.** Phase 1 becomes: DCU CSV + Capital One
   CSV → normalize → dedup → rules classifier → RAG chat. Ship that, then add
   PDF backfill in Phase 2 alongside the investment parsers.
3. **Add the Vanguard multi-section CSV split** as an explicit task — it is the
   only place where the "just use pandas" assumption breaks outright.
4. **Split the Morgan Stanley source into two reports** (Benefit History +
   Gains & Losses) rather than one "Releases Report".
5. **Re-verify DCU before building its parser**, given the First Tech merger.
6. **Design the dedup hash for cross-format collision now, not later.** The whole
   point of a CSV-recent/PDF-backfill strategy is that the same transaction
   arrives twice in two different renderings. `app/ingestion/dedup.py` normalizes
   case, whitespace, and trailing reference numbers before hashing for exactly
   this reason, and `tests/test_dedup_and_routing.py` pins the behavior.

---

## Sources

- [DCU Digital Banking](https://www.dcu.org/dcu-support-center/digital-banking.html) ·
  [DCU eStatements](https://www.dcu.org/services/fee-free-services/estatements.html) ·
  [Bogleheads: DCU export formats](https://www.bogleheads.org/forum/viewtopic.php?t=286321) ·
  [Digital Federal Credit Union (Wikipedia — First Tech merger)](https://en.wikipedia.org/wiki/Digital_Federal_Credit_Union)
- [Capital One CSV export and the 90-day cap](https://ardenmoney.com/guide/export-csv/capital-one/) ·
  [Tiller: export Capital One transactions](https://tiller.com/export-capital-one-transactions/) ·
  [Keeper: export Capital One statements as CSV](https://www.keepertax.com/posts/how-to-export-capital-one-bank-statements-as-a-spreadsheet-csv)
- [Vanguard transaction history](https://transactions.web.vanguard.com/) ·
  [Bogleheads: downloading Vanguard transaction history](https://www.bogleheads.org/forum/viewtopic.php?t=286551) ·
  [Quicken: Vanguard transactions older than 18 months](https://community.quicken.com/discussion/7911300/download-vanguard-transactions-older-than-18-months) ·
  [madkins23/vanguard — CSV structure](https://github.com/madkins23/vanguard)
- [Exporting Fidelity transaction data to a spreadsheet](https://usefidelity.com/how-to-export-fidelity-transaction-data-and-portfolio-to-a-spreadsheet/) ·
  [Converting Fidelity statements](https://www.bankparse.com/blog/convert-fidelity-statement-to-excel-csv)
- [Morgan Stanley at Work stock plan account on E\*TRADE](https://us.etrade.com/stock-plans) ·
  [Navigating your Morgan Stanley at Work stock plan (PDF)](https://www.morganstanley.com/cs/pdf/et_account_management_etrade_com_us_noLC.pdf) ·
  [ukkit/vestwise — BenefitHistory.xlsx exports](https://github.com/ukkit/vestwise) ·
  [wligithub/tax-tool — G&L_Collapsed.xlsx](https://github.com/wligithub/tax-tool/blob/main/README.md)
