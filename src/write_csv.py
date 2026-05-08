import csv
import re
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def fmt(value):
    """Format a numeric value to 2 decimal places, or return empty string."""
    if value is None:
        return ""
    return f"{value:.2f}"


def parse_ship_to(ship_to):
    """Return (company, street, suburb, postcode, contact, phone) from the ship_to block."""
    lines = [l.strip() for l in (ship_to or "").split("\n") if l.strip()]
    contact = lines[0] if len(lines) > 0 else ""
    company = lines[1] if len(lines) > 1 else ""
    street  = lines[2] if len(lines) > 2 else ""
    phone   = lines[4] if len(lines) > 4 else ""

    suburb = postcode = ""
    if len(lines) > 3:
        suburb_line = lines[3]
        # "Glen Innes, Auckland 1072" — postcode is the trailing 4-digit number
        m = re.search(r"\b(\d{4})\b", suburb_line)
        postcode = m.group(1) if m else ""
        suburb = suburb_line.split(",")[0].strip()

    return company, street, suburb, postcode, contact, phone


def write_csv(po, warnings):
    po_number = po.get("po_number") or "UNKNOWN"
    output_path = OUTPUT_DIR / f"{po_number}.csv"

    company, street, suburb, postcode, contact, phone = parse_ship_to(po.get("ship_to"))

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Section 1 — PO number
        writer.writerow(["PO Number"])
        writer.writerow([po_number])

        # Section 2 — delivery address and contact
        writer.writerow([])
        writer.writerow(["Company Name", "Street Address", "Suburb", "Postcode", "Contact Name", "Phone"])
        writer.writerow([company, street, suburb, postcode, contact, phone])

        # Section 3 — line items
        writer.writerow([])
        writer.writerow(["SKU", "SKU Qty", "Unit Price"])
        for item in po.get("line_items") or []:
            writer.writerow([
                item.get("sku") or "",
                item.get("qty") if item.get("qty") is not None else "",
                fmt(item.get("unit_price")),
            ])

        # Section 4 — warnings (omitted on clean run)
        if warnings:
            writer.writerow([])
            writer.writerow(["Warnings"])
            for w in warnings:
                writer.writerow([w])

    return output_path


def main():
    sys.path.insert(0, str(Path(__file__).parent))
    from extract_po import extract_po, validate, find_pdf

    pdf_path = find_pdf()
    print(f"Reading: {pdf_path.name}", file=sys.stderr)

    po = extract_po(pdf_path)
    warnings = validate(po)
    output_path = write_csv(po, warnings)

    print(f"Written: {output_path}", file=sys.stderr)
    if warnings:
        print(f"{len(warnings)} warning(s):", file=sys.stderr)
        for w in warnings:
            print(f"  WARNING: {w}", file=sys.stderr)
    else:
        print("No warnings.", file=sys.stderr)


if __name__ == "__main__":
    main()
