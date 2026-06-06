import os
import sys
import requests
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))
from shared.utils.db import get_connection

NP_API_KEY = os.getenv("NP_API_KEY", "")
NP_API_URL = "https://api.novaposhta.ua/v2.0/json/"


def _normalize_phone(phone: str) -> str:
    import re
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("380") and len(digits) == 12:
        return "0" + digits[3:]
    if digits.startswith("80") and len(digits) == 11:
        return "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("0"):
        return digits
    return digits


def get_ttn_info(ttn: str, phone: str = "") -> dict:
    """
    Track a Nova Poshta waybill via TrackingDocument/getStatusDocuments.
    Returns: recipient_name, recipient_phone, city, warehouse, cod_sum, status
    """
    result = {
        "ttn": ttn,
        "recipient_name": None,
        "recipient_phone": None,
        "city": None,
        "warehouse": None,
        "cod_sum": None,
        "status": None,
        "status_code": None,
        "raw": {},
    }

    if not NP_API_KEY:
        result["error"] = "NP_API_KEY not set in .env"
        return result

    payload = {
        "apiKey": NP_API_KEY,
        "modelName": "TrackingDocument",
        "calledMethod": "getStatusDocuments",
        "methodProperties": {
            "Documents": [{"DocumentNumber": ttn, "Phone": phone or ""}]
        },
    }

    try:
        r = requests.post(NP_API_URL, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        result["error"] = str(e)
        return result

    if not data.get("success"):
        result["error"] = "; ".join(data.get("errors", ["unknown error"]))
        return result

    docs = data.get("data", [])
    if not docs:
        result["error"] = "No data returned for this TTN"
        return result

    doc = docs[0]
    result["raw"] = doc
    result["recipient_name"]  = (doc.get("RecipientFullName") or "").strip() or None
    phone_r = doc.get("PhoneRecipient") or ""
    result["recipient_phone"] = _normalize_phone(phone_r) if phone_r else None
    result["city"]            = doc.get("CityRecipient") or None
    result["warehouse"]       = doc.get("WarehouseRecipient") or None
    result["status"]          = doc.get("Status") or None
    result["status_code"]     = doc.get("StatusCode") or None

    cod_raw = doc.get("CashPaymentAmount") or doc.get("AnnouncedPrice") or 0
    try:
        result["cod_sum"] = float(cod_raw)
    except (ValueError, TypeError):
        result["cod_sum"] = None

    return result


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _price_score(actual: float, expected: float) -> float:
    if not expected:
        return 0.0
    diff = abs(actual - expected)
    if diff > expected * 0.05:
        return 0.0
    return round(1.0 - diff / expected, 3)


def match_order_by_np_data(ttn_info: dict) -> list:
    """
    Search rozetka_processed_orders with 3-level priority:
      1. exact phone                       -> score 1.0,      match_by='phone'
      2. name similarity (>=0.6) + price   -> weighted score, match_by='name+price'
      3. price only (within +-5%)          -> price score,    match_by='price'
    Returns immediately when matches found at any level.
    """
    phone   = ttn_info.get("recipient_phone")
    cod_sum = ttn_info.get("cod_sum")
    name    = ttn_info.get("recipient_name")
    matches = []

    try:
        conn = get_connection()
        cur  = conn.cursor()

        # Level 1: exact phone
        if phone:
            cur.execute(
                "SELECT order_id, total_price, phone, recipient"
                " FROM rozetka_processed_orders WHERE phone = %s",
                (phone,),
            )
            for row in cur.fetchall():
                matches.append({
                    "order_id": row["order_id"],
                    "score":    1.0,
                    "match_by": "phone",
                })

        if matches:
            cur.close(); conn.close()
            return matches

        # Level 2: name similarity (>=0.6) + price within 5%
        if name and cod_sum and cod_sum > 0:
            margin = cod_sum * 0.05
            cur.execute(
                "SELECT order_id, total_price, recipient"
                " FROM rozetka_processed_orders"
                " WHERE total_price BETWEEN %s AND %s AND recipient IS NOT NULL",
                (cod_sum - margin, cod_sum + margin),
            )
            for row in cur.fetchall():
                n_score = _similarity(name, row["recipient"])
                if n_score < 0.6:
                    continue
                p_score  = _price_score(float(row["total_price"]), cod_sum)
                combined = round(n_score * 0.7 + p_score * 0.3, 3)
                matches.append({
                    "order_id": row["order_id"],
                    "score":    combined,
                    "match_by": "name+price",
                })
            matches.sort(key=lambda x: x["score"], reverse=True)

        if matches:
            cur.close(); conn.close()
            return matches

        # Level 3: price only within 5%
        if cod_sum and cod_sum > 0:
            margin = cod_sum * 0.05
            cur.execute(
                "SELECT order_id, total_price"
                " FROM rozetka_processed_orders"
                " WHERE total_price BETWEEN %s AND %s",
                (cod_sum - margin, cod_sum + margin),
            )
            for row in cur.fetchall():
                p_score = _price_score(float(row["total_price"]), cod_sum)
                matches.append({
                    "order_id": row["order_id"],
                    "score":    p_score,
                    "match_by": "price",
                })
            matches.sort(key=lambda x: x["score"], reverse=True)

        cur.close()
        conn.close()
    except Exception as e:
        print(f"match_order_by_np_data error: {e}", file=sys.stderr)

    return matches
