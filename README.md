# PO Co-Pilot

A small command-line tool that reads purchase order PDFs and produces a clean,
validated CSV ready for manual entry into Pronto ERP.

## What it does

Drop supplier emails into `emails/` and PO PDFs into `samples/`. The triage
script classifies each email and pulls any attached PO PDFs into `samples/`.
The batch script then reads every PDF in `samples/`, extracts the header,
ship-to address, and line items, validates the arithmetic against the PDF's
own totals, and writes one CSV per PO into `output/` — formatted to match the
order Pronto's data-entry screen expects.

```
   emails/                         samples/                        output/
   ┌──────────┐                    ┌──────────┐                    ┌──────────┐
   │  *.eml   │                    │  *.pdf   │                    │  *.csv   │
   └────┬─────┘                    └────┬─────┘                    └────▲─────┘
        │                               │                               │
        ▼                               ▼                               │
   ┌──────────┐  saves PO PDFs    ┌──────────┐                          │
   │ triage.py├──────────────────▶│ batch.py │──────────────────────────┘
   └──────────┘   into samples/   └────┬─────┘
                                       │ uses
                                       ▼
                            extract_po.py + write_csv.py
```

## Requirements

- Python 3.9 or newer.
- An [Anthropic API key](https://console.anthropic.com/) — only needed for
  email triage. The PDF batch pipeline runs entirely offline.
- macOS notes: `python3` is preinstalled on recent macOS versions, so no
  Homebrew install is required. All Python dependencies go inside a project
  virtual environment (see Setup) — the system Python is never modified.

## Setup

```
git clone <repo-url> po-copilot
cd po-copilot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file in the project root with your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE
```

All commands below assume the venv is active. If you close and reopen
Terminal, re-run `source venv/bin/activate` from the project folder before
running any of the scripts. When the venv is active your terminal prompt is
prefixed with `(venv)`; run `deactivate` to return to the system Python.

## How to run it

### Process a folder of PO PDFs

Place one or more PO PDFs in `samples/`, then run:

```
python src/batch.py
```

A summary table is printed to the terminal and one CSV per PO is written to
`output/`. Exit code is non-zero if any PDF failed to process.

### Triage a folder of emails

Export `.eml` files from your mail client into `emails/`, then run:

```
python src/triage.py
```

Each email is classified as `PO-PDF`, `PO-text`, or `not-PO`. Any PDF
attached to a `PO-PDF` email is copied into `samples/` automatically, ready
to be picked up by the next `batch.py` run.

## Sample input/output

### Batch run against `samples/`

```
$ python src/batch.py
Processing PO-2026-04812.pdf ...
Processing PO-2026-04813.pdf ...
Processing PO-2026-04814.pdf ...
Processing PO-2026-04815.pdf ...

Status  PO Number      Source File        Items  Total (NZ$)  Warnings
------  -------------  -----------------  -----  -----------  --------
[OK]    PO-2026-04812  PO-2026-04812.pdf  6      943.74       0
[OK]    PO-2026-04813  PO-2026-04813.pdf  4      1453.77      0
[OK]    PO-2026-04814  PO-2026-04814.pdf  8      643.13       0
[WARN]  PO-2026-04815  PO-2026-04815.pdf  5      985.49       1
```

### Extracted JSON (intermediate)

`extract_po()` returns a dictionary like this before validation and CSV
writing. `ship_to` and `vendor` are kept as raw multi-line strings; the CSV
writer is what splits the ship-to block into the columns Pronto expects.
Dates are preserved in the PDF's own DD/MM/YYYY format.

```json
{
  "po_number": "PO-2026-04813",
  "date": "06/05/2026",
  "currency": "NZD",
  "vendor": "Steelside Distributors NZ Ltd\nSales / Trade Counter\n182 Neilson Street\nOnehunga, Auckland 1061\n...",
  "ship_to": "Toby Fitzgerald\nHarborline Engineering Ltd\n12 Apirana Avenue\nGlen Innes, Auckland 1072\n(09) 555 4821",
  "subtotal": 1239.8,
  "gst": 185.97,
  "shipping": 28.0,
  "other": 0.0,
  "total": 1453.77,
  "line_items": [
    {
      "sku": "ST-RHS-50-3M",
      "description": "RHS steel section 50x50x3mm, 6m length",
      "qty": 12,
      "unit_price": 48.2,
      "line_total": 578.4
    },
    ...
  ]
}
```

### Resulting CSV (`output/PO-2026-04813.csv`)

```
PO Number
PO-2026-04813

Company Name,Street Address,Suburb,Postcode,Contact Name,Phone
Harborline Engineering Ltd,12 Apirana Avenue,Glen Innes,1072,Toby Fitzgerald,(09) 555 4821

SKU,SKU Qty,Unit Price
ST-RHS-50-3M,12,48.20
ST-FLAT-25-6M,20,14.30
ST-ANG-40-6M,8,32.75
CS-WELD-MIG-1KG,6,18.90
```

If validation produced warnings, a `Warnings` section is appended after the
line items (line totals not matching, GST off by more than a cent, missing
required fields, etc.). Clean runs omit it. Example tail of
`output/PO-2026-04815.csv`:

```

Warnings
PT-ROLL-230: qty×unit_price (10×15.5=155.0) doesn't match line_total (145.0)
```

### Triage run against `emails/`

```
$ python src/triage.py
Classifying 01_po_with_pdf.eml ...
Classifying 02_po_in_body_structured.eml ...
Classifying 03_po_in_body_conversational.eml ...
Classifying 04_order_acknowledgement.eml ...
Classifying 05_quote_enquiry.eml ...
Classifying 06_internal_meeting.eml ...

Status   Sender                                    Subject                                        Reason
-------  ----------------------------------------  ---------------------------------------------  ------------------------------------------------------------------
PO-PDF   Sandra Tipene <accounts@pacificfastener.  Purchase Order PO-2026-04812 - Pacific Fasten  Email explicitly states 'Please find attached our purchase ord...
PO-text  Steelside Sales <sales@steelside.co.nz>   PO-2026-04901 - Steelside Distributors         A new purchase order is being issued to this company with a P...
PO-text  Dave from Coatings <dave@coatingsnz.co.n  Order for next Tuesday                         A new purchase order is being issued to this company with a P...
not-PO   Pacific Fastener Accounts <accounts@paci  Re: Your PO-2026-04812 - confirmed and shippi  This is an order acknowledgement from the vendor confirming r...
not-PO   Quotes Team <quotes@steelside.co.nz>      Quote Q-9821 - RHS pricing as requested        This is a quotation with pricing valid for 30 days; the vend...
not-PO   Priya Kumar <priya.kumar@harborline-eng.  Friday team lunch - venue?                     This is a casual internal email about scheduling a team lunch...

Summary: 1 PO-PDF, 2 PO-text, 3 not-PO — 1 PDF(s) saved to samples/
```

## Limitations

Be aware of these before pointing the tool at real production data:

- **One PO layout only.** The extractor is tuned to a single supplier's PDF
  template. Other vendors' POs will likely fail or extract garbage; treat
  every new format as an unknown until verified.
- **Text-based PDFs only.** No OCR. Scanned PDFs and image-only PDFs will
  produce empty extractions.
- **Single-page PDFs only.** Multi-page POs are untested and will probably
  drop line items past page 1.
- **NZD and 15% GST are hardcoded.** No support yet for other currencies or
  tax rates; the totals validation assumes 15% GST with a ±$0.01 tolerance.
- **No live Outlook or IMAP integration.** Emails must be exported manually
  to `.eml` files and dropped into `emails/`. There is no fetch step.
- **Manual file placement.** Both `emails/` and `samples/` are populated by
  hand. Nothing is downloaded, watched, or polled.
- **Triage doesn't deduplicate.** If a PDF with the same filename already
  exists in `samples/`, the incoming attachment is saved as
  `PO-XXXX (1).pdf` rather than skipped. `samples/` needs occasional manual
  cleanup.

## Project structure

```
po-copilot/
├── src/                Python source (extract_po, write_csv, batch, triage)
├── samples/            drop PO PDFs here (gitignored — empty on fresh clone)
├── emails/             drop .eml files here (gitignored — empty on fresh clone)
├── output/             generated CSVs land here (safe to delete)
├── tests/              small test fixtures
├── .env                your ANTHROPIC_API_KEY (gitignored — create on setup)
├── requirements.txt    Python dependencies
├── CLAUDE.md           project notes that Claude Code reads when working in this repo
└── README.md
```
