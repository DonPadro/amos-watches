from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Any

YAAD_ENDPOINT = os.environ.get("YAAD_ENDPOINT", "https://pay.hyp.co.il/p/").rstrip("/") + "/"


def site_url() -> str:
    return (os.environ.get("SITE_URL") or "http://127.0.0.1:4173").rstrip("/")


SITE_NAME = os.environ.get("SITE_NAME", "AMOS Watches")


def env(*names: str) -> str:
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def yaad_configured() -> bool:
    return bool(env("YAAD_MASOF") and env("YAAD_KEY") and env("YAAD_PASSP"))


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "AMOS-Watches/1.0"})
    with urllib.request.urlopen(req, timeout=25) as res:
        return res.read().decode("utf-8", errors="replace")


def yaad_create_payment(order: dict[str, Any]) -> dict[str, Any]:
    if not yaad_configured():
        return {
            "demo": True,
            "pay_url": f"{site_url()}/success?demo=1&Order={order['public_id']}&CCode=0&Amount={order['total']}",
        }
    params = {
        "action": "APISign",
        "What": "SIGN",
        "Sign": "True",
        "KEY": env("YAAD_KEY"),
        "PassP": env("YAAD_PASSP"),
        "Masof": env("YAAD_MASOF"),
        "Amount": str(order["total"]),
        "Coin": "1",
        "Order": order["public_id"],
        "Info": f"{SITE_NAME} {order['public_id']} משלוח עד הבית",
        "PageLang": "HEB",
        "UTF8": "True",
        "UTF8out": "True",
        "MoreData": "True",
        "ClientName": order["customer_name"],
        "email": order["email"],
        "cell": order["phone"],
        "city": order.get("city") or "",
        "street": order.get("address") or "",
        "zip": order.get("zip") or "",
        "SuccessURL": f"{site_url()}/success",
        "ErrorURL": f"{site_url()}/success?failed=1",
    }
    qs = urllib.parse.urlencode(params)
    signed = _get(f"{YAAD_ENDPOINT}?{qs}").strip()
    if "signature=" not in signed.lower() and "Sign=" not in signed:
        raise RuntimeError(f"Yaad APISign failed: {signed[:240]}")
    return {"demo": False, "pay_url": f"{YAAD_ENDPOINT}?{signed}"}


def yaad_verify_callback(query: dict[str, str]) -> bool:
    if query.get("demo") == "1" and not yaad_configured():
        return query.get("CCode", "0") in {"0", "00"}
    if not yaad_configured():
        return False
    params = {
        "action": "APISign",
        "What": "VERIFY",
        "Masof": env("YAAD_MASOF"),
        "KEY": env("YAAD_KEY"),
        "PassP": env("YAAD_PASSP"),
    }
    keep = ["Id", "CCode", "Amount", "ACode", "Order", "Fild1", "Fild2", "Fild3", "Sign", "sign"]
    for key in keep:
        if key in query:
            params[key] = query[key]
    raw = _get(f"{YAAD_ENDPOINT}?{urllib.parse.urlencode(params)}")
    return "CCode=0" in raw.replace(" ", "")


def notify_whatsapp(message: str) -> dict[str, Any]:
    to = env("ADMIN_WHATSAPP").lstrip("+")
    token = env("WHATSAPP_ACCESS_TOKEN")
    phone_id = env("WHATSAPP_PHONE_NUMBER_ID")
    wa_link = f"https://wa.me/{to}?text={urllib.parse.quote(message)}" if to else ""
    if token and phone_id and to:
        body = json.dumps(
            {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": message},
            }
        ).encode()
        req = urllib.request.Request(
            f"https://graph.facebook.com/v21.0/{phone_id}/messages",
            data=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                return {"sent": True, "provider": "cloud_api", "status": res.status, "whatsapp_url": wa_link}
        except urllib.error.HTTPError as exc:
            return {"sent": False, "provider": "cloud_api", "error": exc.read().decode()[:400], "whatsapp_url": wa_link}
    return {"sent": False, "provider": "link", "whatsapp_url": wa_link}


def send_email_receipt(order: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    host = env("SMTP_HOST")
    to = order.get("email") or ""
    lines = [f"{row['title']} × {row['qty']} — ₪{row['price']}" for row in items]
    ship = f"{order.get('address') or ''}, {order.get('city') or ''} {order.get('zip') or ''}".strip()
    text = (
        f"קבלה — {SITE_NAME}\n"
        f"הזמנה {order['public_id']}\n"
        f"סטטוס: {order['status']}\n"
        f"משלוח עד הבית (על חשבוננו): {ship}\n\n"
        + "\n".join(lines)
        + f"\n\nמשלוח: ₪0\nסה\"כ: ₪{order['total']}\nתודה. יוקרה בכל שנייה ⏱"
    )
    if not host or not to:
        return {"sent": False, "reason": "smtp_or_email_missing", "preview": text}
    msg = EmailMessage()
    msg["Subject"] = f"קבלה {order['public_id']} | {SITE_NAME}"
    msg["From"] = env("SMTP_FROM") or env("SMTP_USER")
    msg["To"] = to
    msg.set_content(text)
    context = ssl.create_default_context()
    with smtplib.SMTP(host, int(env("SMTP_PORT") or "587"), timeout=20) as smtp:
        smtp.starttls(context=context)
        if env("SMTP_USER"):
            smtp.login(env("SMTP_USER"), env("SMTP_PASSWORD"))
        smtp.send_message(msg)
    return {"sent": True}


def fetch_google_reviews() -> dict[str, Any]:
    key = env("GOOGLE_PLACES_API_KEY")
    place_id = env("GOOGLE_PLACE_ID")
    if not key or not place_id:
        return {"configured": False, "reviews": [], "rating": None, "count": 0}
    qs = urllib.parse.urlencode(
        {
            "place_id": place_id,
            "fields": "reviews,rating,user_ratings_total,name",
            "key": key,
            "language": "he",
        }
    )
    payload = json.loads(_get(f"https://maps.googleapis.com/maps/api/place/details/json?{qs}"))
    result = payload.get("result") or {}
    reviews = [
        {
            "author": row.get("author_name") or "אורח",
            "rating": int(row.get("rating") or 0),
            "body": row.get("text") or "",
            "relative_time": row.get("relative_time_description") or "",
        }
        for row in (result.get("reviews") or [])
        if row.get("text")
    ]
    return {
        "configured": True,
        "name": result.get("name"),
        "rating": result.get("rating"),
        "count": result.get("user_ratings_total"),
        "reviews": reviews,
    }


def order_whatsapp_text(order: dict[str, Any], items: list[dict[str, Any]]) -> str:
    lines = ", ".join(f"{row['title']}×{row['qty']}" for row in items)
    ship = f"{order.get('address') or ''} {order.get('city') or ''} {order.get('zip') or ''}".strip()
    return (
        f"הזמנה חדשה AMOS {order['public_id']}\n"
        f"{order['customer_name']} | {order['phone']} | {order['email']}\n"
        f"משלוח עד הבית (עלינו): {ship}\n"
        f"{lines}\nסה\"כ ₪{order['total']} | {order['status']}"
    )
