
from __future__ import annotations

import re

from app.extensions import db
from app.slices.entity.models import Entity, EntityAddress, EntityContact, EntityRole


def _nonce(html: bytes) -> str:
    text = html.decode("utf-8")
    m = re.search(r'name="wiz_nonce" value="([^"]+)"', text)
    assert m, text
    return m.group(1)


def test_entity_wizard_person_minimum_creation_flow(client, app):
    # Step 1: load person core page to get nonce
    resp = client.get("/entity/wizard/person")
    assert resp.status_code == 200
    nonce = _nonce(resp.data)

    # Step 1 commit: create core only
    resp = client.post(
        "/entity/wizard/person",
        data={
            "wiz_nonce": nonce,
            "first_name": "Michael",
            "last_name": "Shaw",
            "preferred_name": "",
            "dob": "",
            "last_4": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    contact_url = resp.headers["Location"]
    assert "/entity/wizard/" in contact_url
    assert contact_url.endswith("/contact")

    entity_ulid = contact_url.split("/entity/wizard/")[1].split("/contact")[0]

    # Step 2: submit blank contact honestly; no row should be created.
    resp = client.get(contact_url)
    assert resp.status_code == 200
    nonce = _nonce(resp.data)

    resp = client.post(
        contact_url,
        data={
            "wiz_nonce": nonce,
            "email": "",
            "phone": "",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    address_url = resp.headers["Location"]
    assert address_url.endswith("/address")

    # Step 3: explicitly defer address
    resp = client.get(address_url)
    assert resp.status_code == 200
    nonce = _nonce(resp.data)

    resp = client.post(
        address_url,
        data={
            "wiz_nonce": nonce,
            "action": "skip",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    role_url = resp.headers["Location"]
    assert role_url.endswith("/role")

    # Step 4: assign required initial role
    resp = client.get(role_url)
    assert resp.status_code == 200
    nonce = _nonce(resp.data)

    resp = client.post(
        role_url,
        data={
            "wiz_nonce": nonce,
            "role": "customer",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    next_url = resp.headers["Location"]
    assert next_url.endswith("/next")

    # Final page should render successfully.
    resp = client.get(next_url)
    assert resp.status_code == 200

    with app.app_context():
        ent = db.session.get(Entity, entity_ulid)
        assert ent is not None
        assert ent.kind == "person"

        active_roles = (
            db.session.query(EntityRole)
            .filter(
                EntityRole.entity_ulid == entity_ulid,
                EntityRole.archived_at.is_(None),
            )
            .all()
        )
        assert len(active_roles) == 1
        assert active_roles[0].role == "customer"

        contacts = (
            db.session.query(EntityContact)
            .filter(EntityContact.entity_ulid == entity_ulid)
            .all()
        )
        assert contacts == []

        addresses = (
            db.session.query(EntityAddress)
            .filter(EntityAddress.entity_ulid == entity_ulid)
            .all()
        )
        assert addresses == []
