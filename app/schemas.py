from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import InvoiceStatus


class CustomerCreate(BaseModel):
    name: str
    email: EmailStr


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    created_at: datetime


class InvoiceItemCreate(BaseModel):
    description: str
    quantity: int = Field(gt=0)
    unit_price: int = Field(ge=0)  # بالقروش


class InvoiceCreate(BaseModel):
    customer_id: int
    currency: str = "EGP"
    items: list[InvoiceItemCreate] = Field(min_length=1)


class InvoiceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str
    quantity: int
    unit_price: int


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: int
    status: InvoiceStatus
    currency: str
    total_amount: int
    created_at: datetime
    items: list[InvoiceItemOut]

class InvoiceStatusUpdate(BaseModel):
    status: InvoiceStatus


class PaymentCreate(BaseModel):
    amount: int = Field(gt=0)  # بالقروش


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    amount: int
    created_at: datetime


class WebhookEndpointCreate(BaseModel):
    url: str


class WebhookEndpointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    secret: str
    active: bool
    created_at: datetime