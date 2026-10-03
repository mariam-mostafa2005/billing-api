import threading
import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def make_open_invoice(unit_price: int = 100000) -> int:
    customer = client.post(
        "/customers",
        json={"name": "Test", "email": f"{uuid.uuid4()}@example.com"},
    ).json()
    invoice = client.post(
        "/invoices",
        json={
            "customer_id": customer["id"],
            "items": [
                {"description": "Item", "quantity": 1, "unit_price": unit_price}
            ],
        },
    ).json()
    client.patch(f"/invoices/{invoice['id']}/status", json={"status": "open"})
    return invoice["id"]


def test_same_key_same_body_returns_same_payment():
    invoice_id = make_open_invoice(100000)
    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}

    r1 = client.post(
        f"/invoices/{invoice_id}/payments", json={"amount": 30000}, headers=headers
    )
    r2 = client.post(
        f"/invoices/{invoice_id}/payments", json={"amount": 30000}, headers=headers
    )

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    assert r2.headers.get("idempotent-replayed") == "true"


def test_same_key_different_body_is_rejected():
    invoice_id = make_open_invoice(100000)
    key = str(uuid.uuid4())
    headers = {"Idempotency-Key": key}

    r1 = client.post(
        f"/invoices/{invoice_id}/payments", json={"amount": 30000}, headers=headers
    )
    r2 = client.post(
        f"/invoices/{invoice_id}/payments", json={"amount": 40000}, headers=headers
    )

    assert r1.status_code == 201
    assert r2.status_code == 422


def test_concurrent_requests_with_same_key_create_one_payment():
    invoice_id = make_open_invoice(100000)
    key = str(uuid.uuid4())
    n = 10
    results = []
    barrier = threading.Barrier(n)

    def pay():
        barrier.wait()
        r = client.post(
            f"/invoices/{invoice_id}/payments",
            json={"amount": 10000},
            headers={"Idempotency-Key": key},
        )
        results.append((r.status_code, r.json().get("id")))

    threads = [threading.Thread(target=pay) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # كل الردود 201 وكلها بنفس id الدفعة (دفعة واحدة بس اتسجّلت)
    assert all(code == 201 for code, _ in results)
    assert len({pid for _, pid in results}) == 1