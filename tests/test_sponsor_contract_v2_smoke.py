# tests/test_sponsor_contract_v2_smoke.py
from app.extensions.contracts import sponsors_v2 as spx
from app.lib.ids import new_ulid
from app.slices.entity import services as ent_svc


def test_sponsors_v2_smoke(app):
    # make an org (Entity)
    org = ent_svc.ensure_org(
        legal_name="Sponsor Smoke",
        ein=None,
        request_id=new_ulid(),
        actor_ulid=None,
    )

    # create sponsor
    r = spx.create_sponsor(
        entity_ulid=org, request_id=new_ulid(), actor_ulid=None
    )
    sid = r["data"]["sponsor_ulid"]
    assert r["ok"] and len(sid) == 26

    # upsert one canonical capability (from your SPONSOR_CAPS)
    r2 = spx.upsert_capabilities(
        sponsor_ulid=sid,
        capabilities={"funding.cash_grant": {"has": True, "note": "seed"}},
        request_id=new_ulid(),
        actor_ulid=None,
    )
    assert r2["ok"]
    assert r2["data"]["sponsor"]["sponsor_ulid"] == sid

    # pledge upsert (cash)
    pid = new_ulid()
    r3 = spx.pledge_upsert(
        sponsor_ulid=sid,
        pledge={
            "pledge_ulid": pid,
            "type": "cash",
            "status": "proposed",
            "currency": "USD",
            "stated_amount": 25000,
            "notes": "demo",
        },
        request_id=new_ulid(),
        actor_ulid=None,
    )
    assert r3["ok"]
    assert r3["data"]["pledge_ulid"] == pid

    # move pledge status
    r4 = spx.pledge_set_status(
        pledge_ulid=pid,
        status="active",
        request_id=new_ulid(),
        actor_ulid=None,
    )
    assert r4["ok"]

    # fetch profile
    prof = spx.get_profile(sponsor_ulid=sid)
    assert prof["ok"]
    assert prof["data"]["sponsor_ulid"] == sid
