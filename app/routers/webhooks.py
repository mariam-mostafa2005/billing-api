import secrets

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import WebhookEndpoint
from app.schemas import WebhookEndpointCreate, WebhookEndpointOut

router = APIRouter(prefix="/webhook-endpoints", tags=["webhooks"])


@router.post("", response_model=WebhookEndpointOut, status_code=status.HTTP_201_CREATED)
def create_endpoint(payload: WebhookEndpointCreate, db: Session = Depends(get_db)):
    endpoint = WebhookEndpoint(
        url=payload.url,
        secret=secrets.token_hex(32),  # 64 حرف، بيتولّد عشوائي
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    return endpoint


@router.get("", response_model=list[WebhookEndpointOut])
def list_endpoints(db: Session = Depends(get_db)):
    return db.scalars(select(WebhookEndpoint).order_by(WebhookEndpoint.id)).all()