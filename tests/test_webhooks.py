import hashlib
import hmac
import json
from unittest.mock import patch

import httpx

from app.database import SessionLocal
from app.models import WebhookDelivery, WebhookEndpoint
from app.webhook_service import deliver, sign


def verify(secret: str, timestamp: str, body: str, signature: str) -> bool:
    """ده اللي المستلم بيعمله عشان يتأكد إن الرسالة منّا."""
    expected = hmac.new(
        secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def test_signature_is_valid_for_untouched_body():
    body = json.dumps({"type": "invoice.paid", "data": {"invoice_id": 1}})
    sig = sign("secret123", "1700000000", body)
    assert verify("secret123", "1700000000", body, sig)


def test_signature_fails_if_body_tampered():
    body = json.dumps({"type": "invoice.paid", "data": {"total_amount": 100}})
    sig = sign("secret123", "1700000000", body)
    tampered = body.replace("100", "1")
    assert not verify("secret123", "1700000000", tampered, sig)


def test_signature_fails_with_wrong_secret():
    body = "{}"
    sig = sign("secret123", "1700000000", body)
    assert not verify("other-secret", "1700000000", body, sig)


def test_deliver_sends_valid_signature_and_marks_delivered():
    db = SessionLocal()
    ep = WebhookEndpoint(url="https://receiver.test/hook", secret="s" * 64)
    db.add(ep)
    db.flush()
    d = WebhookDelivery(
        endpoint_id=ep.id,
        event_type="invoice.paid",
        payload={"invoice_id": 1, "total_amount": 5000},
        status="pending",
    )
    db.add(d)
    db.commit()
    delivery_id, secret = d.id, ep.secret
    db.close()

    captured = {}

    def fake_post(url, content, headers, timeout):
        captured["content"] = content
        captured["headers"] = headers
        return httpx.Response(200)

    with patch("app.webhook_service.httpx.post", fake_post):
        deliver(delivery_id)

    ts = captured["headers"]["X-Webhook-Timestamp"]
    sig = captured["headers"]["X-Webhook-Signature"].removeprefix("sha256=")
    assert verify(secret, ts, captured["content"], sig)

    db = SessionLocal()
    d = db.get(WebhookDelivery, delivery_id)
    assert d.status == "delivered"
    assert d.attempts == 1
    # تنضيف: نوقف الـ endpoint عشان ميتبعتلوش أحداث تانية
    db.get(WebhookEndpoint, d.endpoint_id).active = False
    db.commit()
    db.close()