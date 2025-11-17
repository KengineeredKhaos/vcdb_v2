# tests/seeds.py

from app.lib.ids import new_ulid
from app.slices.customers.services import ensure_customer
from app.slices.resources.services import ensure_resource
from app.slices.sponsors.services import ensure_sponsor


def _as_ulid(x):
    return getattr(x, "ulid", x)

def seed_minimal_party_triplet(db_session):
    """
    Create a single party triplet (entity→customer/resource/sponsor) and
    return (entity_ulid, customer_ulid, resource_ulid, sponsor_ulid).
    """
    entity_ulid = new_ulid()
    req = new_ulid()  # request_id must be a 26-char ULID

    cust = ensure_customer(entity_ulid=entity_ulid, request_id=req, actor_ulid=None)
    res  = ensure_resource(entity_ulid=entity_ulid, request_id=req, actor_ulid=None)
    spon = ensure_sponsor(entity_ulid=entity_ulid, request_id=req, actor_ulid=None)

    cust_ulid = _as_ulid(cust)
    res_ulid  = _as_ulid(res)
    spon_ulid = _as_ulid(spon)

    return entity_ulid, cust_ulid, res_ulid, spon_ulid
