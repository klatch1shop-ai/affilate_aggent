import re
import sys
import os
import pdfplumber
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from shared.utils.db import get_connection


def normalize_phone(phone: str) -> str:
    """Normalize +380XXXXXXXXX or 380XXXXXXXXX to 0XXXXXXXXX."""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("380") and len(digits) == 12:
        return "0" + digits[3:]
    if digits.startswith("80") and len(digits) == 11:
        return "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        return digits
    return digits


def _extract_ttn(text: str):
    # NP TTN format: XX XXXX XXXX XXXX (14 digits, possibly space-separated)
    m = re.search(r"\b(\d{2})\s+(\d{4})\s+(\d{4})\s+(\d{4})\b", text)
    if m:
        return m.group(1) + m.group(2) + m.group(3) + m.group(4)
    # Fallback: 14 consecutive digits
    m = re.search(r"\b(\d{14})\b", text)
    if m:
        return m.group(1)
    return None


def _extract_recipient_block(text: str):
    """
    NP waybill: pdfplumber merges two columns left-to-right per line.
    Layout per line: <sender_token>  <recipient_token>
    After "КОМУ:" header, right-column tokens are the recipient.
    Heuristic: find standalone mixed-case Cyrillic full name on its own line.
    """
    lines = text.splitlines()

    # Find index of line containing "КОМУ"
    kому_idx = next(
        (i for i, l in enumerate(lines) if "КОМУ" in l.upper()), None
    )

    recipient = None
    city = None

    # Full name pattern: "Прізвище Ім'я По-батькові" in mixed case (not ALL CAPS)
    name_re = re.compile(
        r"^[А-ЯІЇЄ][а-яіїє']+\s+[А-ЯІЇЄ][а-яіїє']+(?:\s+[А-ЯІЇЄ][а-яіїє']+)?$"
    )

    # City from "Місто, Відділення" pattern (first occurrence = destination)
    city_branch_re = re.compile(
        r"([А-ЯІЇЄ][а-яіїє'\-]+(?:\s[А-ЯІЇЄ][а-яіїє'\-]+)*),\s*(?:Відділення|вул\.|відд)"
    )

    # Large destination city at top (ALL CAPS standalone line)
    dest_re = re.compile(r"^([А-ЯІЇЄ\-]{3,30})$")

    for i, line in enumerate(lines):
        line = line.strip()

        # Destination city — first ALL CAPS Cyrillic line
        if city is None and dest_re.match(line):
            city = line.capitalize()

        # Mixed-case full name after КОМУ block
        if kому_idx is not None and i > kому_idx and name_re.match(line):
            if recipient is None:
                recipient = line

        # City from "Місто, Відділення" (prefer first match = destination branch)
        if city is None:
            cm = city_branch_re.search(line)
            if cm:
                city = cm.group(1)

    return recipient, city


def parse_ttn_pdf(pdf_path: str) -> dict:
    """Parse Nova Poshta waybill PDF, extract TTN, phone, recipient, city."""
    result = {"ttn": None, "phone": None, "recipient": None, "city": None}

    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    result["ttn"] = _extract_ttn(text)

    # Phone: first Ukrainian phone in text (recipient side — left column for dest-city wbs)
    phones = re.findall(
        r"(?:\+?380|0)\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", text
    )
    if phones:
        result["phone"] = normalize_phone(phones[0])

    result["recipient"], result["city"] = _extract_recipient_block(text)

    return result


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def match_order_by_ttn_data(parsed: dict) -> list:
    """
    Search rozetka_processed_orders for orders matching parsed TTN data.
    Returns list of dicts with order_id and score.
    """
    phone = parsed.get("phone")
    recipient = parsed.get("recipient")
    city = parsed.get("city")
    matches = []

    try:
        conn = get_connection()
        cur = conn.cursor()

        if phone:
            cur.execute(
                "SELECT order_id, recipient, city FROM rozetka_processed_orders WHERE phone = %s",
                (phone,),
            )
            rows = cur.fetchall()
            for row in rows:
                score = 1.0
                if recipient and row["recipient"]:
                    score = max(score, _similarity(recipient, row["recipient"]))
                matches.append({"order_id": row["order_id"], "score": round(score, 3)})

        if not matches and (recipient or city):
            cur.execute(
                "SELECT order_id, recipient, city FROM rozetka_processed_orders "
                "WHERE recipient IS NOT NULL OR city IS NOT NULL"
            )
            rows = cur.fetchall()
            for row in rows:
                r_score = _similarity(recipient, row["recipient"]) if recipient else 0.0
                c_score = _similarity(city, row["city"]) if city else 0.0
                combined = (r_score + c_score) / 2
                if combined >= 0.6:
                    matches.append(
                        {"order_id": row["order_id"], "score": round(combined, 3)}
                    )
            matches.sort(key=lambda x: x["score"], reverse=True)

        cur.close()
        conn.close()
    except Exception as e:
        print(f"match_order_by_ttn_data error: {e}", file=sys.stderr)

    return matches
