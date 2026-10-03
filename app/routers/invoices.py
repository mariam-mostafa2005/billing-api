import hashlib
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import (
    Customer,
    IdempotencyKey,
    Invoice,
    InvoiceItem,
    InvoiceStatus,
    Payment,
)
from app.schemas import (
    InvoiceCreate,
    InvoiceOut,
    InvoiceStatusUpdate,
    PaymentCreate,
    PaymentOut,
)

router = APIRouter(prefix="/invoices", tags=["invoices"])


def load_invoice(db: Session, invoice_id: int) -> Invoice | None:
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.items))
        .where(Invoice.id == invoice_id)
    )
    return db.scalars(stmt).first()


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(payload: InvoiceCreate, db: Session = Depends(get_db)):
    if not db.get(Customer, payload.customer_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")

    items = [
        InvoiceItem(
            description=i.description,
            quantity=i.quantity,
            unit_price=i.unit_price,
        )
        for i in payload.items
    ]
    # الإجمالي بيتحسب في السيرفر بالقروش، مش من العميل
    total = sum(i.quantity * i.unit_price for i in items)

    invoice = Invoice(
        customer_id=payload.customer_id,
        currency=payload.currency,
        total_amount=total,
        items=items,
    )
    db.add(invoice)
    db.commit()
    return load_invoice(db, invoice.id)


@router.get("", response_model=list[InvoiceOut])
def list_invoices(db: Session = Depends(get_db)):
    stmt = (
        select(Invoice)
        .options(selectinload(Invoice.items))
        .order_by(Invoice.id)
    )
    return db.scalars(stmt).all()


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = load_invoice(db, invoice_id)
    if not invoice:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
    return invoice


ALLOWED_TRANSITIONS = {
    InvoiceStatus.draft: {InvoiceStatus.open, InvoiceStatus.void},
    InvoiceStatus.open: {InvoiceStatus.paid, InvoiceStatus.void},
    InvoiceStatus.paid: set(),
    InvoiceStatus.void: set(),
}


@router.patch("/{invoice_id}/status", response_model=InvoiceOut)
def update_status(
    invoice_id: int,
    payload: InvoiceStatusUpdate,
    db: Session = Depends(get_db),
):
    # FOR UPDATE بيقفل صف الفاتورة لحد ما الـ transaction تخلص
    stmt = select(Invoice).where(Invoice.id == invoice_id).with_for_update()
    invoice = db.scalars(stmt).first()
    if not invoice:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")

    if payload.status not in ALLOWED_TRANSITIONS[invoice.status]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot change status from {invoice.status.value} "
            f"to {payload.status.value}",
        )

    invoice.status = payload.status
    db.commit()
    return load_invoice(db, invoice_id)


@router.post(
    "/{invoice_id}/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
)
def create_payment(
    invoice_id: int,
    payload: PaymentCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    endpoint = f"POST /invoices/{invoice_id}/payments"
    request_hash = hashlib.sha256(
        json.dumps(payload.model_dump(), sort_keys=True).encode()
    ).hexdigest()

    # قفل صف الفاتورة: أي طلب تاني على نفس الفاتورة هيستنى لحد ما نخلص
    stmt = select(Invoice).where(Invoice.id == invoice_id).with_for_update()
    invoice = db.scalars(stmt).first()
    if not invoice:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")

    # لو الـ key اتستخدم قبل كده: رجّع نفس الرد المحفوظ
    if idempotency_key:
        existing = db.scalars(
            select(IdempotencyKey).where(
                IdempotencyKey.key == idempotency_key,
                IdempotencyKey.endpoint == endpoint,
            )
        ).first()
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Idempotency-Key reused with a different request body",
                )
            response.status_code = existing.response_status
            response.headers["Idempotent-Replayed"] = "true"
            return existing.response_body

    if invoice.status != InvoiceStatus.open:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot pay an invoice in status {invoice.status.value}",
        )

    paid_so_far = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.invoice_id == invoice_id
        )
    )
    remaining = invoice.total_amount - paid_so_far
    if payload.amount > remaining:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Amount exceeds remaining balance ({remaining})",
        )

    payment = Payment(invoice_id=invoice_id, amount=payload.amount)
    db.add(payment)
    db.flush()  # عشان ياخد id و created_at قبل الحفظ

    if payload.amount == remaining:
        invoice.status = InvoiceStatus.paid

    out = PaymentOut.model_validate(payment).model_dump(mode="json")

    if idempotency_key:
        db.add(
            IdempotencyKey(
                key=idempotency_key,
                endpoint=endpoint,
                request_hash=request_hash,
                response_status=201,
                response_body=out,
            )
        )

    db.commit()
    return out