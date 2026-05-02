# PO Co-Pilot

A small command-line tool that reads purchase order PDFs and produces a clean,
validated CSV ready for manual entry into Pronto ERP.

## What it does

- Reads PO PDFs from the `samples/` folder
- Extracts structured fields: vendor, PO number, date, line items, and totals
- Validates that required fields are present and that line item totals match the PO total
- Writes a tidy CSV to `output/` with columns ordered to match Pronto's data-entry screen

## Who it's for

A single operator who currently re-keys purchase orders into Pronto by hand.
The CSV is not imported automatically — it's a reference document that makes
the keying step faster and less error-prone.

---

*Day 1 scaffold — Python source code coming on Day 2.*
