# Billing API

A billing/invoicing REST API built with **FastAPI + PostgreSQL**, focused on the
problems real payment systems face: concurrency, duplicate requests, and
reliable event delivery.

## Features

- Customers, invoices with line items, payments
- Invoice state machine: `draft → open → paid / void` (no going back)
- **Money stored as integers (minor units)**, never floats
- **Race-condition safe payments** using `SELECT ... FOR UPDATE`
- **Idempotency keys** to prevent duplicate payments on client retries
- **Signed webhooks** (HMAC-SHA256) with retries and exponential backoff
- Alembic migrations, Dockerized, tested with pytest

## Quick start

```bash
cp .env.example .env   # or create .env (see below)
docker compose up --build
docker compose exec api alembic upgrade head
```

API docs: http://localhost:8000/docs

Run tests:

```bash
docker compose exec api pytest tests -v
```

## Design decisions

### Money as integers
Amounts are stored in minor units (piastres): 1500.50 EGP = `150050`.
Floats cannot represent decimals exactly, so they are never used for money.
DB `CHECK` constraints reject negative amounts even if application code is wrong.

### Concurrency: row locking
Recording a payment runs in one transaction. The invoice row is locked with
`SELECT ... FOR UPDATE`, so two simultaneous payments cannot both pass the
"remaining balance" check.

**Proof:** a test fires 10 concurrent full payments at one invoice.
Without the lock it failed every time (2-3 payments succeeded instead of 1);
with the lock exactly one succeeds and the rest get `409`.

### Idempotency
Clients send an `Idempotency-Key` header. The key and a hash of the request
body are stored with the response, in the same transaction as the payment.

- Same key + same body → the stored response is replayed (no new payment)
- Same key + different body → `422`
- Verified by a test with 10 concurrent requests sharing one key: one payment.

### Webhooks
On `invoice.paid`, a delivery row is written **in the same transaction** as
the payment (so a rollback never emits an event). Sending happens in the
background and is retried by a worker with exponential backoff
(1s, 5s, 30s, 2m, 10m), up to 5 attempts, then marked `failed`.
Every payload is signed: `HMAC-SHA256(secret, timestamp + "." + body)`
in `X-Webhook-Signature`, so receivers can verify authenticity.

## Known limitations / future work

- Run a **single worker** only. With several, two could pick the same
  delivery. Fix: claim rows with `SELECT ... FOR UPDATE SKIP LOCKED`.
- Delivery is at-least-once; webhook consumers should be idempotent.
- No authentication yet (planned: API keys).
- The webhook secret is returned on every read; it should be shown once.