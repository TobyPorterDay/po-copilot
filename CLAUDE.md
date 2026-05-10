# PO Co-Pilot

A small command-line tool that reads purchase order PDFs and outputs a
clean, validated CSV ready for manual entry into Pronto ERP.

## About me

Working through Claude Code 101 with no prior coding experience.
This file captures project conventions so Claude stays focused on
small, reviewable changes. The instructions below default to:

- Explaining each step before doing it, especially shell commands and
  library installs.
- Using Plan Mode for anything that touches more than one file or runs
  more than one shell command.
- Small, reviewable changes — one file or one function at a time.
- Python as the implementation language (most beginner-friendly for PDF
  work). Keep dependencies minimal and well-known.
- Asking before installing anything system-wide.

## Project scope

**In scope**

- Reading PO PDFs from a `samples/` folder.
- Extracting structured fields: vendor, PO number, date, line items
  (description, qty, unit price, line total), totals, currency.
- Validating: required fields present, line totals add up to PO total,
  vendor matches a known list (when one is provided).
- Writing a clean CSV to `output/`, with the column order matching how
  the data is keyed into Pronto.

**Out of scope (for now)**

- Writing data into Pronto itself. The CSV is consumed by a human
  typist (me). Pronto integration would require IT involvement and is
  a Phase 2 conversation.
- Pulling PDFs out of Outlook automatically. That's a Day 5 stretch
  goal, not the MVP.

## Folder layout

- `emails/` — `.eml` files to triage. Ignored by git; drop real emails here.
- `samples/` — PO PDFs to process. Treat anything here as redacted or
  fake unless I explicitly say otherwise.
- `output/` — generated CSVs. Safe to overwrite.
- `src/` — Python source code.
- `tests/` — small test fixtures and scripts.
- `CLAUDE.md` — this file. Update it when conventions change.

## Conventions

- All currency amounts are NZD unless the PDF says otherwise.
- If a field isn't present in the PDF, leave it empty in the output —
  never guess.
- Commits explain *what* and *why*, not just *what*.
- Do not add `Co-Authored-By:` trailers to commit messages.

## PO format notes

Observed from `samples/sample_po_redacted.pdf` (2026-05-02).

**Document type:** Text-based PDF (real text layer, no OCR needed).

**Document-level fields present:**
- Buyer name + address (top-left header block)
- Date — format is DD/MM/YYYY (NZ convention; `02/05/2026` = 2 May 2026)
- PO number — format `PO-YYYY-NNNNN`
- Vendor name + address
- Ship-to name + address
- Requisitioner, Ship Via, F.O.B., Shipping Terms (one row of four fields)

**Line item table columns:** ITEM #, DESCRIPTION, QTY, UNIT PRICE, TOTAL

**Output CSV structure (single file, three sections separated by blank rows):**

Section 1 — PO number:
`PO Number`
`PO-2026-04812`

Section 2 — delivery address and contact:
`Company Name, Street Address, Suburb, Postcode, Contact Name, Phone`
`Harborline Engineering Ltd, 12 Apirana Avenue, Glen Innes, 1072, Toby Fitzgerald, (09) 555 4821`

Section 3 — one row per product line item:
`SKU, SKU Qty, Unit Price`
`FX-M08-50-SS, 250, 0.84`

Section 4 — warnings (only present if validation produced warnings):
`Warnings`
`<warning 1>`
`<warning 2>`
One warning per row. Omit this section entirely on a clean run.

Notes:
- Ship To block is the source for address fields (not the Vendor block).
- ship_to lines in order: line 0 = Contact Name, line 1 = Company Name, line 2 = Street Address, line 3 = suburb/postcode line.
- In the PDF, suburb and postcode appear on one line as `Glen Innes, Auckland 1072`; split on comma, then extract the trailing 4-digit postcode.
- GST, Shipping, and Other rows are excluded from the line items section of the CSV.

**Totals block fields:** SUBTOTAL, GST 15%, SHIPPING, OTHER, TOTAL (with explicit "NZ$" label)

**Known parsing traps:**

1. **Wrapped item codes** — the ITEM # column is narrow, so long codes
   wrap mid-string inside the cell (e.g., `FX-NUT-M08-ZN` appears as
   `FX-NUT-M08-Z` / `N` on separate lines). The parser must detect and
   re-join these fragments.

2. **Date is DD/MM/YYYY** — must not let any library silently treat it
   as MM/DD/YYYY.

3. **GST is ex-GST pricing** — unit prices and line totals are all
   before GST. GST appears only in the totals block as a separate
   calculated line. Need to decide with the user whether the CSV
   carries GST and shipping rows or product line items only.

4. **GST rounding** — 796.30 × 15% = 119.445, PDF shows 119.44
   (rounded down). Validation should allow ±$0.01 tolerance.

5. **"OTHER" row** — present in totals, zero on this sample but may be
   non-zero on other POs; should be captured.

6. **Single page** — this sample fits on one page. Multi-page behaviour
   is still an open question (see "Open questions" below).

## What's been built

- **`src/extract_po.py`** — reads a PDF from `samples/`, returns a structured dictionary.
- **`src/extract_po.py` → `validate(po)`** — 8 checks (required fields, line items present, per-item fields, per-item arithmetic, subtotal, GST, grand total, date sanity). Never raises; returns a list of warning strings. All floating-point comparisons use ±$0.01 tolerance.
- **`src/write_csv.py`** — writes `output/<po_number>.csv` in three sections (PO header / Ship-to address / Line items), plus an optional Warnings section if validation produced any issues.
- **`src/batch.py`** — batch processor for a folder of PDFs. Iterates `samples/*.pdf`, runs extract → validate → write_csv for each, and prints a summary report (status, PO number, source file, item count, total, warning count). Per-PDF errors are caught and logged as `[FAIL]` rows so one bad PDF doesn't take down the run; exit code is non-zero if any PDF failed. Validation pipeline verified end-to-end against the deliberately-broken `PO-2026-04815` (line-total mismatch surfaces correctly as a `[WARN]`).
- **`src/triage.py`** — email triage front-end. Drop `.eml` files into `emails/`, run `python src/triage.py`. Parses each email (subject, sender, body, attachments) with Python's stdlib `email` module, then calls `claude-haiku-4-5` to classify it as `PO-PDF`, `PO-text`, or `not-PO`. Rejects lookalikes (order acknowledgements, quotes, shipping notifications) via a careful system prompt. For every `PO-PDF` hit, saves the attached PDF into `samples/` so `batch.py` can pick it up on the next run. Prints a one-row-per-email triage report plus a summary line.

## Lessons learned

1. **Use `extract_tables()`, not raw text + regex** — pdfplumber's table extractor correctly handles column alignment and cell boundaries; regex on raw text output breaks on wrapped lines and inconsistent whitespace.

2. **Phantom `None` column at index 3** — this PDF's line items table has a spurious empty column between QTY (index 2) and UNIT PRICE (index 4); skip index 3 when reading row values.

3. **Totals rows live inside the line items table** — rows for SUBTOTAL, GST 15%, SHIPPING, OTHER, and TOTAL appear at the bottom of the same table, with the label in column 3 and the value in column 5; filter them out by checking whether column 0 (ITEM #) is empty.

4. **Wrapped SKUs arrive as cells with `\n`** — pdfplumber preserves the line break inside the cell string rather than splitting it into two rows; join on `\n` and strip whitespace to reconstruct the full code.

## Open questions / future work

- The exact list of fields Pronto needs and the order they're entered.
- The vendor master list (approved suppliers).
- Whether to handle multi-page POs or first-page-only.
- Tax handling (GST line vs. inclusive prices).
