import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import WebhookDelivery, WebhookEndpoint

MAX_ATTEMPTS = 5
BACKOFF_SECONDS = [1, 5, 30, 120, 600]  # exponential-ish


def sign(secret: str, timestamp: str, body: str) -> str:
    message = f"{timestamp}.{body}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def enqueue_event(db: Session, event_type: str, payload: dict) -> list[int]:
    """يسجّل delivery لكل endpoint نشط. بيتنادى جوه نفس الـ transaction."""
    endpoints = db.scalars(
        select(WebhookEndpoint).where(WebhookEndpoint.active.is_(True))
    ).all()
    deliveries = []
    for ep in endpoints:
        d = WebhookDelivery(
            endpoint_id=ep.id,
            event_type=event_type,
            payload=payload,
            status="pending",
            next_attempt_at=datetime.now(timezone.utc),
        )
        db.add(d)
        deliveries.append(d)
    db.flush()
    return [d.id for d in deliveries]


def deliver(delivery_id: int) -> None:
    """يحاول يبعت delivery واحدة ويسجّل النتيجة. بيشتغل في الخلفية."""
    db = SessionLocal()
    try:
        d = db.get(WebhookDelivery, delivery_id)
        if not d or d.status == "delivered":
            return
        ep = db.get(WebhookEndpoint, d.endpoint_id)

        body = json.dumps(
            {"type": d.event_type, "data": d.payload}, sort_keys=True
        )
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": f"sha256={sign(ep.secret, timestamp, body)}",
        }

        d.attempts += 1
        try:
            r = httpx.post(ep.url, content=body, headers=headers, timeout=5)
            d.last_status_code = r.status_code
            ok = 200 <= r.status_code < 300
            d.last_error = None if ok else f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            ok = False
            d.last_status_code = None
            d.last_error = str(e)[:500]

        if ok:
            d.status = "delivered"
            d.next_attempt_at = None
        elif d.attempts >= MAX_ATTEMPTS:
            d.status = "failed"
            d.next_attempt_at = None
        else:
            d.status = "pending"
            delay = BACKOFF_SECONDS[min(d.attempts - 1, len(BACKOFF_SECONDS) - 1)]
            d.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
        db.commit()
    finally:
        db.close()

def retry_due_deliveries() -> int:
    """يعيد المحاولة للـ deliveries المتأخرة. بيرجّع عددها."""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        ids = db.scalars(
            select(WebhookDelivery.id).where(
                WebhookDelivery.status == "pending",
                WebhookDelivery.next_attempt_at <= now,
            )
        ).all()
    finally:
        db.close()

    for did in ids:
        deliver(did)
    return len(ids)