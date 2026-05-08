import sys
from pathlib import Path

# Resolve sibling modules without installing the package
sys.path.insert(0, str(Path(__file__).parent))

from extract_po import extract_po, validate
from write_csv import write_csv

SAMPLES_DIR = Path(__file__).parent.parent / "samples"


def run_batch():
    pdfs = sorted(SAMPLES_DIR.glob("*.pdf"))
    if not pdfs:
        print("No PDF files found in samples/ — nothing to do.")
        return 0

    rows = []
    any_failed = False

    for pdf_path in pdfs:
        print(f"Processing {pdf_path.name} ...", file=sys.stderr)
        try:
            po = extract_po(pdf_path)
            warnings = validate(po)
            write_csv(po, warnings)

            po_number = po.get("po_number") or "UNKNOWN"
            item_count = len(po.get("line_items") or [])
            total = po.get("total")
            total_str = f"{total:.2f}" if total is not None else ""
            warn_count = len(warnings)
            status = "[OK]" if warn_count == 0 else "[WARN]"
            rows.append((status, po_number, pdf_path.name, item_count, total_str, warn_count, None))

        except Exception as exc:
            any_failed = True
            rows.append(("[FAIL]", "", pdf_path.name, "", "", "", str(exc)))

    _print_table(rows)
    return 1 if any_failed else 0


def _print_table(rows):
    headers = ("Status", "PO Number", "Source File", "Items", "Total (NZ$)", "Warnings")

    # Build display rows — FAIL rows show error message in PO Number column
    display = []
    for status, po_number, filename, items, total, warns, error in rows:
        if status == "[FAIL]":
            display.append((status, f"ERROR: {error}", filename, "", "", ""))
        else:
            display.append((status, po_number, filename, str(items), total, str(warns)))

    all_rows = [headers] + display
    widths = [max(len(r[i]) for r in all_rows) for i in range(len(headers))]

    separator = "  ".join("-" * w for w in widths)

    print()
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print(separator)
    for row in display:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


if __name__ == "__main__":
    sys.exit(run_batch())
