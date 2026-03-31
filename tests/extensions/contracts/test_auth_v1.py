from __future__ import annotations

from app.extensions import db
from app.extensions.contracts import auth_v1
from app.slices.auth.models import Role


def _get_or_create_role(code: str) -> None:
    row = db.session.query(Role).filter_by(code=code).one_or_none()
    if row is None:
        db.session.add(Role(code=code, is_active=True))
        db.session.flush()


def test_auth_v1_create_account_and_set_roles(app):
    with app.app_context():
        _get_or_create_role("staff")
        _get_or_create_role("admin")

        created = auth_v1.create_account(
            username="contract_mshaw",
            password="temp-pass-1",
            roles=["staff"],
            entity_ulid="01AAAAAAAAAAAAAAAAAAAAAAAA",
        )

        assert created["username"] == "contract_mshaw"
        assert created["roles"] == ["staff"]

        updated = auth_v1.set_account_roles(created["ulid"], ["admin"])
        assert updated["roles"] == ["admin"]
