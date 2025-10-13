# app/utils/paging.py
from __future__ import annotations

from math import ceil


def pagination_args(
    request, extra: dict | None = None, exclude=("page",)
) -> dict:
    """Return a dict of current query params (excluding 'page') merged with extra."""
    args = request.args.to_dict(flat=True)
    for k in exclude:
        args.pop(k, None)
    if extra:
        args.update(extra)
    return args


class Pager:
    """Lightweight pager if you aren't using a built-in Pagination object."""

    def __init__(self, total: int, page: int, per_page: int):
        self.total = int(total)
        self.page = max(1, int(page))
        self.per_page = max(1, int(per_page))
        self.pages = max(1, ceil(self.total / self.per_page))

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def prev_num(self):
        return self.page - 1 if self.has_prev else 1

    @property
    def next_num(self):
        return self.page + 1 if self.has_next else self.pages
