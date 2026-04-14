# tests/utilities_tests/test_pagination.py

from sqlalchemy import literal, select, union_all

from app.lib.pagination import Page, paginate


def test_page_exposes_template_compat_properties():
    page = Page(
        items=[1, 2, 3],
        total=30,
        page=2,
        per_page=10,
        next_page=3,
        prev_page=1,
    )

    assert page.pages == 3
    assert page.has_prev is True
    assert page.has_next is True
    assert page.prev_num == 1
    assert page.next_num == 3


def test_paginate_dispatches_sequence_source():
    page = paginate(list(range(1, 26)), page=2, per_page=10)

    assert page.page == 2
    assert page.per_page == 10
    assert page.total == 25
    assert page.pages == 3
    assert list(page.items) == list(range(11, 21))
    assert page.has_prev is True
    assert page.has_next is True


def test_paginate_sqlalchemy_select_smoke(app):
    with app.app_context():
        values = union_all(
            select(literal("alpha").label("value")),
            select(literal("bravo").label("value")),
            select(literal("charlie").label("value")),
        ).subquery()

        stmt = select(values.c.value).order_by(values.c.value)

        page = paginate(stmt, page=1, per_page=2)

        assert page.page == 1
        assert page.per_page == 2
        assert page.total == 3
        assert page.pages == 2
        assert page.has_prev is False
        assert page.has_next is True
        assert len(page.items) == 2
