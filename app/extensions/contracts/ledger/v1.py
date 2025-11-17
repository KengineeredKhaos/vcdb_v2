# app/extensions/contracts/ledger/v1.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VerifyReportDTO:
    ok: bool
    count: int | None = None
    bad_ulid: str | None = None


def verify(chain_key: str | None = None) -> VerifyReportDTO:
    from app.slices.ledger.services import verify_chain

    r = verify_chain(chain_key)
    return VerifyReportDTO(
        ok=r.get("ok", False),
        count=r.get("count"),
        bad_ulid=r.get("bad_ulid"),
    )
