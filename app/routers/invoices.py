from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Customer, Invoice, InvoiceItem
from app.schemas import InvoiceCreate, InvoiceOut

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