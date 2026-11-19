"""Seed reference data and demo accounts. Idempotent.

Usage: python -m app.seed
"""

import csv
from pathlib import Path

from sqlalchemy import select

from .db import system_session
from .models import DEFAULT_CLIENT_SETTINGS, Client, Role, User, UserClient, VmrsCode, WarrantyRule
from .services.defaults import default_warranty_rules
from .security import hash_password

DATA = Path(__file__).parent / "data"

DEMO_USERS = [
    ("admin@audit-demo.com", "Avery Admin", Role.admin, "admin-password-123"),
    ("analyst@audit-demo.com", "Sam Analyst", Role.analyst, "analyst-password-123"),
]
DEMO_CLIENTS = [("Lone Prairie Freight", "lone-prairie", "lpfreight"), ("Gulf Coast Haulers", "gulf-coast", "gulfcoast")]


def seed_vmrs(db) -> int:
    n = 0
    with open(DATA / "vmrs_codes.csv") as f:
        for row in csv.DictReader(f):
            obj = db.get(VmrsCode, row["code"])
            if obj is None:
                db.add(VmrsCode(**row))
                n += 1
            else:
                obj.system, obj.component, obj.keywords = row["system"], row["component"], row["keywords"]
    return n


def main() -> None:
    with system_session() as db:
        added = seed_vmrs(db)
        users = {}
        for email, name, role, pw in DEMO_USERS:
            u = db.scalar(select(User).where(User.email == email))
            if not u:
                u = User(email=email, name=name, role=role, password_hash=hash_password(pw))
                db.add(u)
                db.flush()
            users[role] = u
        for name, slug, token in DEMO_CLIENTS:
            c = db.scalar(select(Client).where(Client.slug == slug))
            if not c:
                c = Client(name=name, slug=slug, inbound_email_token=token, settings=dict(DEFAULT_CLIENT_SETTINGS))
                db.add(c)
                db.flush()
                for r in default_warranty_rules():
                    db.add(WarrantyRule(client_id=c.id, **r))
            if slug == "lone-prairie" and not db.get(UserClient, (users[Role.analyst].id, c.id)):
                db.add(UserClient(user_id=users[Role.analyst].id, client_id=c.id))
        db.commit()
        print(f"Seeded: {added} new VMRS codes, {len(DEMO_USERS)} users, {len(DEMO_CLIENTS)} clients.")


if __name__ == "__main__":
    main()
