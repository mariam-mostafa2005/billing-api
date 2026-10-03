import time

from app.webhook_service import retry_due_deliveries

if __name__ == "__main__":
    print("webhook worker started", flush=True)
    while True:
        n = retry_due_deliveries()
        if n:
            print(f"retried {n} deliveries", flush=True)
        time.sleep(2)