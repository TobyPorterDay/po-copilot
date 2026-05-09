import email
import email.policy
import json
import re
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

EMAILS_DIR = Path(__file__).parent.parent / "emails"
SAMPLES_DIR = Path(__file__).parent.parent / "samples"

SYSTEM_PROMPT = """You are an email classifier for a company that issues purchase orders (POs) to vendors.
Your job is to decide whether each email is a new purchase order that the company received, or not.

Classify each email into exactly one of these three categories:

PO-PDF
  A new purchase order is being issued TO this company, and the PO document is attached as a PDF.
  Signals: body says something like "please find attached", "enclosed is our PO", "attached purchase order";
  the attachment filename looks like a PO (e.g. PO-2026-04820.pdf, purchase_order.pdf).

PO-text
  A new purchase order is being issued TO this company, but the PO is written inside the email body
  itself — there is no PDF attachment carrying the PO. The body will contain a PO number, line items,
  quantities, prices, and a total.

not-PO
  Everything else. This includes — but is not limited to:
  - ORDER ACKNOWLEDGEMENTS: the vendor is confirming receipt of a PO that THIS company already sent them.
    Look for phrases like "we have received your purchase order", "order confirmation", "thank you for
    your order", references to a PO number the vendor is acknowledging.
  - QUOTES / PROFORMAS: the vendor is pricing goods that haven't been committed to yet.
    Look for "quotation", "quote", "proforma", "valid for 30 days", "subject to your approval".
  - SHIPPING NOTIFICATIONS: "your order has been dispatched", tracking numbers, delivery ETAs.
  - INVOICES: requests for payment after goods have been delivered.
  - NEWSLETTERS, PROMOTIONS, UNRELATED EMAIL.

Critical rule: do NOT classify on keywords alone. Read the meaning of the email.
A subject line containing "PO" does not make it a PO — an order acknowledgement often mentions
the PO number in the subject. Ask yourself: is someone issuing a NEW purchase order to US right now?

Reply with ONLY a JSON object, no other text, no markdown fences:
{"classification": "<PO-PDF|PO-text|not-PO>", "reason": "<one concise sentence explaining why>"}"""


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def parse_eml(path: Path) -> dict:
    raw = path.read_bytes()
    msg = email.message_from_bytes(raw, policy=email.policy.default)

    subject = str(msg.get("Subject", "")).strip()
    sender = str(msg.get("From", "")).strip()
    date = str(msg.get("Date", "")).strip()

    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is None:
        body = ""
    else:
        content_type = body_part.get_content_type()
        payload = body_part.get_content()
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")
        body = _strip_html(payload) if content_type == "text/html" else payload

    attachments = []
    for part in msg.iter_attachments():
        filename = part.get_filename() or ""
        content_type = part.get_content_type()
        try:
            payload_bytes = part.get_payload(decode=True)
        except Exception:
            payload_bytes = b""
        attachments.append({
            "filename": filename,
            "content_type": content_type,
            "bytes": payload_bytes or b"",
        })

    return {
        "subject": subject,
        "sender": sender,
        "date": date,
        "body": body,
        "attachments": attachments,
        "source": path.name,
    }


def classify(parsed: dict, client: anthropic.Anthropic) -> tuple[str, str]:
    attachment_summary = (
        ", ".join(a["filename"] or a["content_type"] for a in parsed["attachments"])
        if parsed["attachments"]
        else "none"
    )
    user_message = (
        f"Subject: {parsed['subject']}\n"
        f"From: {parsed['sender']}\n"
        f"Date: {parsed['date']}\n"
        f"Attachments: {attachment_summary}\n\n"
        f"Body:\n{parsed['body'][:3000]}"
    )

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=256,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    raw = response.content[0].text.strip()

    # Extract the JSON object even if the model wraps it in markdown fences
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    json_str = match.group(0) if match else raw

    try:
        data = json.loads(json_str)
        label = data.get("classification", "not-PO")
        reason = data.get("reason", raw)
    except json.JSONDecodeError:
        label = "not-PO"
        reason = f"(parse error) {raw[:120]}"

    if label not in ("PO-PDF", "PO-text", "not-PO"):
        label = "not-PO"

    return label, reason


def _unique_path(dest_dir: Path, filename: str) -> Path:
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    candidate = dest_dir / filename
    n = 1
    while candidate.exists():
        candidate = dest_dir / f"{stem} ({n}){suffix}"
        n += 1
    return candidate


def save_pdf_attachments(parsed: dict) -> list[Path]:
    saved = []
    for att in parsed["attachments"]:
        name = att["filename"] or ""
        is_pdf = name.lower().endswith(".pdf") or att["content_type"] == "application/pdf"
        if not is_pdf:
            continue
        dest = _unique_path(SAMPLES_DIR, name or "attachment.pdf")
        dest.write_bytes(att["bytes"])
        saved.append(dest)
    return saved


def _print_table(rows: list[tuple]) -> None:
    headers = ("Status", "Sender", "Subject", "Reason")
    all_rows = [headers] + [(r[0], r[1], r[2], r[3]) for r in rows]
    widths = [max(len(str(row[i])) for row in all_rows) for i in range(len(headers))]
    sep = "  ".join("-" * w for w in widths)
    print()
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print(sep)
    for row in rows:
        print("  ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))


def run_triage() -> int:
    load_dotenv(override=True)  # use .env as source of truth, even if env var is set elsewhere (e.g. accidentally exported empty in current shell)
    client = anthropic.Anthropic()

    emls = sorted(EMAILS_DIR.glob("*.eml"))
    if not emls:
        print("No .eml files found in emails/ — nothing to do.")
        return 0

    rows = []
    pdf_count = 0
    label_counts = {"PO-PDF": 0, "PO-text": 0, "not-PO": 0}

    for eml_path in emls:
        print(f"Classifying {eml_path.name} ...", file=sys.stderr)
        try:
            parsed = parse_eml(eml_path)
            label, reason = classify(parsed, client)

            sender_short = parsed["sender"][:40]
            subject_short = parsed["subject"][:45]
            status = label

            if label == "PO-PDF":
                saved = save_pdf_attachments(parsed)
                if saved:
                    pdf_count += len(saved)
                else:
                    status = "[!] PO-PDF"
                    reason = "classified as PO-PDF but no PDF attachment found — " + reason

            label_counts[label] = label_counts.get(label, 0) + 1
            rows.append((status, sender_short, subject_short, reason))

        except Exception as exc:
            rows.append(("[ERR]", eml_path.name, "", str(exc)[:80]))

    _print_table(rows)
    print()
    print(
        f"Summary: {label_counts['PO-PDF']} PO-PDF, "
        f"{label_counts['PO-text']} PO-text, "
        f"{label_counts['not-PO']} not-PO — "
        f"{pdf_count} PDF(s) saved to samples/"
    )
    return 0


if __name__ == "__main__":
    sys.exit(run_triage())
