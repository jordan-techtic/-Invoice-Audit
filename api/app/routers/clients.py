import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..deps import client_db, current_user, get_session, require_admin
from ..models import DEFAULT_CLIENT_SETTINGS, Client, Role, User, UserClient, WarrantyRule
from ..schemas import ClientCreate, ClientOut, ClientUpdate
from ..security import new_token
from ..services.defaults import default_warranty_rules

router = APIRouter(prefix="/clients", tags=["clients"])


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "client"


@router.get("", response_model=list[ClientOut])
def list_clients(user: User = Depends(current_user), db: Session = Depends(get_session)):
    q = select(Client).order_by(Client.name)
    if user.role != Role.admin:
        q = q.join(UserClient, UserClient.client_id == Client.id).where(UserClient.user_id == user.id)
    return db.scalars(q).all()


@router.post("", response_model=ClientOut, status_code=201)
def create_client(
    body: ClientCreate, request: Request, user: User = Depends(require_admin), db: Session = Depends(get_session)
):
    slug = base = _slugify(body.name)
    i = 2
    while db.scalar(select(Client.id).where(Client.slug == slug)):
        slug = f"{base}-{i}"
        i += 1
    client = Client(name=body.name, slug=slug, inbound_email_token=new_token(12).lower().replace("_", "x").replace("-", "x"),
                    settings=dict(DEFAULT_CLIENT_SETTINGS))
    db.add(client)
    db.flush()
    db.info["client_id"] = client.id
    for r in default_warranty_rules():
        db.add(WarrantyRule(client_id=client.id, **r))
    db.commit()
    audit.record(db, action="create", object_type="client", object_id=client.id, user_id=user.id, client_id=client.id, request=request)
    return client


@router.get("/{client_id}", response_model=ClientOut)
def get_client(client_id: uuid.UUID, db: Session = Depends(client_db)):
    return db.get(Client, client_id)


@router.patch("/{client_id}", response_model=ClientOut)
def update_client(client_id: uuid.UUID, body: ClientUpdate, request: Request, db: Session = Depends(client_db)):
    client = db.get(Client, client_id)
    changed = []
    if body.name is not None:
        client.name = body.name
        changed.append("name")
    if body.settings is not None:
        unknown = set(body.settings) - set(DEFAULT_CLIENT_SETTINGS)
        if unknown:
            raise HTTPException(422, f"Unknown setting: {', '.join(sorted(unknown))}. Remove it and try again.")
        client.settings = {**DEFAULT_CLIENT_SETTINGS, **client.settings, **body.settings}
        changed.append("settings")
    if body.service_offer_text is not None:
        client.service_offer_text = body.service_offer_text
        changed.append("service_offer_text")
    db.commit()
    audit.record(db, action="edit", object_type="client", object_id=client.id, detail={"fields": changed}, request=request)
    return client
