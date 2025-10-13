# app/slices/entity/__init__.py
from flask import Blueprint

bp = Blueprint(
    "entity", __name__, url_prefix="/entity", template_folder="templates"
)
# Register light façades for other slices (keeps Extensions neutral)
from app.extensions import entity_api, entity_read  # type: ignore

from . import models, routes  # noqa: E402, F401
from . import services as svc  # noqa: E402
from .services import (  # noqa: E402
    ensure_org,
    ensure_person,
    ensure_role,
    upsert_address,
    upsert_contacts,
)

entity_api.register(
    ensure_person=ensure_person,
    ensure_org=ensure_org,
    upsert_contacts=upsert_contacts,
    upsert_address=upsert_address,
    ensure_role=ensure_role,
)

entity_read.register(
    list_people_with_role=svc.list_people_with_role,
    person_view=svc.person_view,
    list_orgs_with_role=svc.list_orgs_with_role,
)
