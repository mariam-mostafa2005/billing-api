import threading
import uuid

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def make_open_invoice(total_unit_price: int = 100000) -> int:
    customer = client.post(
        "/customers",
        json={"name": "Test", "email": f"{uuid.uuid4()}@example.com"},
    ).json()
    invoice = client.post(
        "/invoices",
        json={
            "customer_id": customer["id"],
            "items": [
                {"description": "Item", "quantity": 1, "unit_price": total_unit_price}
            ],
        },
    ).json()
    client.patch(f"/invoices/{invoice['id']}/status", json={"status": "open"})
    return invoice["id"]


def test_concurrent_full_payments_only_one_succeeds():
    invoice_id = make_open_invoice(100000)
    n = 10
    results = []
    barrier = threading.Barrier(n)

    def pay():
        barrier.wait()  # كل الطلبات تبدأ في نفس اللحظة
        r = client.post(
            f"/invoices/{invoice_id}/payments", json={"amount": 100000}
        )
        results.append(r.status_code)

    threads = [threading.Thread(target=pay) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(201) == 1
    assert results.count(409) == n - 1

    invoice = client.get(f"/invoices/{invoice_id}").json()
    assert invoice["status"] == "paid"