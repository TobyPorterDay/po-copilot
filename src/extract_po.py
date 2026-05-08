import json
import re
import sys
from pathlib import Path

import pdfplumber

SAMPLES_DIR = Path(__file__).parent.parent / "samples"


def find_pdf():
    pdfs = sorted(SAMPLES_DIR.glob("*.pdf"))
    if not pdfs:
        sys.exit("No PDF files found in samples/")
    return pdfs[0]


def find_table(tables, header_text):
    """Return the first table whose top-left cell contains header_text."""
    for t in tables:
        if t and t[0] and any(header_text in str(cell) for cell in t[0] if cell):
            return t
    return None


def to_float(value):
    """Convert a string like '796.30' or '1,234.56' to float, or return None."""
    if not value:
        return None
    cleaned = str(value).replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_po(pdf_path):
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()

        # --- Date and PO number ---
        # These live in a small two-row table in the top-right corner.
        header_table = find_table(tables, "DATE")
        po_number = date = None
        if header_table:
            for row in header_table:
                if row and row[0] == "DATE":
                    date = (row[1] or "").strip()
                elif row and row[0] == "PO #":
                    po_number = (row[1] or "").strip()

        # --- Vendor and Ship To ---
        # pdfplumber extracts each bordered block as its own table.
        # Each is a two-row table: ['VENDOR'] then [<multi-line address>].
        vendor_table = find_table(tables, "VENDOR")
        vendor = None
        if vendor_table and len(vendor_table) > 1:
            vendor = (vendor_table[1][0] or "").strip()

        ship_to_table = find_table(tables, "SHIP TO")
        ship_to = None
        if ship_to_table and len(ship_to_table) > 1:
            ship_to = (ship_to_table[1][0] or "").strip()

        # --- Line items and totals ---
        # The main grid has six columns (pdfplumber detects a phantom None
        # column at index 3 between QTY and UNIT PRICE):
        #   0: ITEM #  1: DESCRIPTION  2: QTY  3: None  4: UNIT PRICE  5: TOTAL
        # Totals rows appear at the bottom of the same table with their
        # label in column 3 and value in column 5.
        items_table = find_table(tables, "ITEM")
        line_items = []
        subtotal = gst = shipping = other = total = currency = None

        if items_table:
            for row in items_table[1:]:  # skip header row
                sku_raw = (row[0] or "").strip()
                col3 = (row[3] or "").strip()
                col5 = (row[5] or "").strip()

                # Totals rows: label in column 3, value in column 5, no SKU
                if col3 and not sku_raw:
                    if col3 == "SUBTOTAL":
                        subtotal = to_float(col5)
                    elif col3.startswith("GST"):
                        gst = to_float(col5)
                    elif col3 == "SHIPPING":
                        shipping = to_float(col5)
                    elif col3 == "OTHER":
                        other = to_float(col5)
                    elif col3 == "TOTAL":
                        # col5 looks like "NZ$ 943.74"
                        m = re.search(r"NZ\$\s*([\d,]+\.\d{2})", col5)
                        if m:
                            total = to_float(m.group(1))
                            currency = "NZD"
                    continue

                # Wrapped item codes contain a newline — remove it
                sku = sku_raw.replace("\n", "")
                description = (row[1] or "").strip()
                qty_raw = (row[2] or "").strip()
                unit_price_raw = (row[4] or "").strip()
                line_total_raw = col5

                # Skip blank padding rows
                if not sku and not description:
                    continue

                qty = int(qty_raw) if qty_raw.isdigit() else (qty_raw or None)
                line_items.append({
                    "sku": sku,
                    "description": description,
                    "qty": qty,
                    "unit_price": to_float(unit_price_raw),
                    "line_total": to_float(line_total_raw),
                })

        return {
            "po_number": po_number,
            "date": date,
            "currency": currency,
            "vendor": vendor,
            "ship_to": ship_to,
            "subtotal": subtotal,
            "gst": gst,
            "shipping": shipping,
            "other": other,
            "total": total,
            "line_items": line_items,
        }


def validate(po):
    warnings = []
    CENT = 0.01

    # 1. Required fields
    for field in ("po_number", "date", "vendor", "total"):
        if not po.get(field):
            warnings.append(f"Missing required field: {field}")

    # 2. At least one line item
    items = po.get("line_items") or []
    if not items:
        warnings.append("No line items found")

    for i, item in enumerate(items):
        label = item.get("sku") or f"item[{i}]"

        # 3. Per-item fields present
        for field in ("sku", "description", "qty", "unit_price", "line_total"):
            if item.get(field) is None or item.get(field) == "":
                warnings.append(f"{label}: missing {field}")

        # 4. Per-item arithmetic
        qty, unit_price, line_total = item.get("qty"), item.get("unit_price"), item.get("line_total")
        if None not in (qty, unit_price, line_total):
            expected = round(qty * unit_price, 2)
            if abs(expected - line_total) > CENT:
                warnings.append(
                    f"{label}: qty×unit_price ({qty}×{unit_price}={expected}) "
                    f"doesn't match line_total ({line_total})"
                )

    # 5. Subtotal sanity
    subtotal = po.get("subtotal")
    line_totals = [it.get("line_total") for it in items]
    if subtotal is not None and all(v is not None for v in line_totals):
        calc = round(sum(line_totals), 2)
        if abs(calc - subtotal) > CENT:
            warnings.append(f"Subtotal mismatch: sum of line_totals={calc}, extracted subtotal={subtotal}")

    # 6. GST sanity
    gst = po.get("gst")
    if subtotal is not None and gst is not None:
        expected_gst = round(subtotal * 0.15, 2)
        if abs(expected_gst - gst) > CENT:
            warnings.append(f"GST mismatch: 15% of subtotal={expected_gst}, extracted GST={gst}")

    # 7. Grand total sanity
    total = po.get("total")
    if None not in (subtotal, gst, total):
        calc_total = round(subtotal + gst + (po.get("shipping") or 0) + (po.get("other") or 0), 2)
        if abs(calc_total - total) > CENT:
            warnings.append(f"Total mismatch: subtotal+gst+shipping+other={calc_total}, extracted total={total}")

    # 8. Date sanity
    from datetime import datetime
    date = po.get("date")
    if date:
        try:
            parsed = datetime.strptime(date, "%d/%m/%Y")
            if not (2020 <= parsed.year <= 2030):
                warnings.append(f"Date year {parsed.year} is outside expected range 2020–2030")
        except ValueError:
            warnings.append(f"Date '{date}' is not a valid DD/MM/YYYY date")

    return warnings


def main():
    pdf_path = find_pdf()
    print(f"Reading: {pdf_path.name}\n", file=sys.stderr)
    result = extract_po(pdf_path)
    print(json.dumps(result, indent=2))
    warnings = validate(result)
    print()
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}")
    else:
        print("No warnings.")


if __name__ == "__main__":
    main()
