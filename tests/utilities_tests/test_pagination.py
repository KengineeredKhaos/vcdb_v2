from app.lib.pagination import Page


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
