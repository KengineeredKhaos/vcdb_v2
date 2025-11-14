# app/slices/devtools/services.py

from app.extensions import db
from app.slices.entity.models import Entity
from app.slices.customers.models import Customer
from app.slices.resources.models import Resource
from app.slices.sponsors.models import Sponsor
from app.slices.logistics.models import InventoryItem as Skus

def seed_manifest():
    # Deterministic counts; if your seed stamps ULID ranges, include them here too.
    s = db.session
    return {
        "entities": s.query(Entity).count(),
        "customers": s.query(Customer).count(),
        "resources": s.query(Resource).count(),
        "sponsors": s.query(Sponsor).count(),
        "skus": s.query(Skus).count(),
    }
