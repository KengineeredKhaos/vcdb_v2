from __future__ import annotations

import pytest

from app.slices.customers import services as svc


ENTITY_ULID = "01KN8N38ADHNP3VQTYV8RC3YES"
ACTOR_ULID = "01KN8N38ADHNP3VQTYV8RC3YEA"
HISTORY_ULID = "01KN8N38ADHNP3VQTYV8RC3YEB"


class FakePage:
    def __init__(
        self,
        items,
        *,
        page: int = 1,
        per_page: int = 25,
        total: int | None = None,
    ):
        self.items = list(items)
        self.page = page
        self.per_page = per_page
        self.total = len(self.items) if total is None else total
        self.pages = 1
        self.has_prev = False
        self.has_next = False
        self.prev_num = None
        self.next_num = None

    def map(self, f):
        return FakePage(
            [f(x) for x in self.items],
            page=self.page,
            per_page=self.per_page,
            total=self.total,
        )


class _DummyField:
    def __eq__(self, other):
        return self

    def desc(self):
        return self


class _DummyStmt:
    def where(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self


class FakeHistory:
    entity_ulid = _DummyField()
    happened_at_iso = _DummyField()
    has_admin_tags = _DummyField()

    def __init__(
        self,
        *,
        ulid: str,
        entity_ulid: str,
        kind: str,
        happened_at_iso: str,
        severity: str,
        title: str,
        summary: str,
        source_slice: str,
        source_ref_ulid: str,
        public_tags_csv: str | None,
        admin_tags_csv: str | None,
    ):
        self.ulid = ulid
        self.entity_ulid = entity_ulid
        self.kind = kind
        self.happened_at_iso = happened_at_iso
        self.severity = severity
        self.title = title
        self.summary = summary
        self.source_slice = source_slice
        self.source_ref_ulid = source_ref_ulid
        self.public_tags_csv = public_tags_csv
        self.admin_tags_csv = admin_tags_csv


class FakeCustomer:
    entity_ulid = _DummyField()

    def __init__(
        self,
        *,
        entity_ulid: str,
        status: str,
        watchlist: bool,
        tier1_min: int | None,
        flag_tier1_immediate: bool,
    ):
        self.entity_ulid = entity_ulid
        self.status = status
        self.watchlist = watchlist
        self.tier1_min = tier1_min
        self.flag_tier1_immediate = flag_tier1_immediate


def _patch_query_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "CustomerHistory", FakeHistory)
    monkeypatch.setattr(svc, "Customer", FakeCustomer)
    monkeypatch.setattr(svc, "select", lambda *args, **kwargs: _DummyStmt())
    monkeypatch.setattr(svc, "ensure_entity_ulid", lambda value: value)


def _make_history(*, with_admin_tags: bool = False) -> FakeHistory:
    return FakeHistory(
        ulid=HISTORY_ULID,
        entity_ulid=ENTITY_ULID,
        kind="assessment.initial",
        happened_at_iso="2026-04-05T04:50:50.343000Z",
        severity="info",
        title="Initial assessment completed",
        summary=(
            "Eligibility resolved and initial customer assessment recorded."
        ),
        source_slice="customers",
        source_ref_ulid=ENTITY_ULID,
        public_tags_csv="assessment",
        admin_tags_csv="followup" if with_admin_tags else None,
    )


def _make_customer() -> FakeCustomer:
    return FakeCustomer(
        entity_ulid=ENTITY_ULID,
        status="active",
        watchlist=True,
        tier1_min=1,
        flag_tier1_immediate=True,
    )


def test_list_customer_history_items_unwraps_paginated_row_shape(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_query_env(monkeypatch)
    history = _make_history()

    def fake_paginate(stmt, *, page: int, per_page: int):
        return FakePage([(history,)], page=page, per_page=per_page, total=1)

    monkeypatch.setattr(svc, "paginate", fake_paginate)

    page = svc.list_customer_history_items(
        entity_ulid=ENTITY_ULID,
        page=1,
        per_page=25,
    )

    assert len(page.items) == 1
    row = page.items[0]
    assert row.ulid == HISTORY_ULID
    assert row.entity_ulid == ENTITY_ULID
    assert row.kind == "assessment.initial"
    assert row.title == "Initial assessment completed"
    assert row.public_tags == ("assessment",)


def test_list_customer_history_items_rejects_unexpected_paginate_shape(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_query_env(monkeypatch)

    def fake_paginate(stmt, *, page: int, per_page: int):
        return FakePage([object()], page=page, per_page=per_page, total=1)

    monkeypatch.setattr(svc, "paginate", fake_paginate)

    with pytest.raises(TypeError, match="expected CustomerHistory row"):
        svc.list_customer_history_items(
            entity_ulid=ENTITY_ULID,
            page=1,
            per_page=25,
        )
