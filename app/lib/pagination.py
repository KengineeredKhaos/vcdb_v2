# app/lib/pagination.py
# VCDB CANON — DO NOT MODIFY WITHOUT EXPLICIT APPROVAL
# File: <relative path>
# Purpose: Stable library primitive for VCDB.
# Canon API: lib-core v1.0.0 (frozen)

"""
Generic pagination helpers (in-memory and SQLAlchemy).

This module provides a small, slice-agnostic pagination layer:

- Page[T]: immutable pagination result with items, total, page, per_page,
  next/prev_page, and a to_dict() helper for DTOs.
- paginate_list(): paginate in-memory sequences.
- paginate_sa(): paginate SQLAlchemy Query or Select objects.
- paginate(): unified entry point that dispatches to list vs SQLAlchemy
  depending on the source type.

Routes and services should use these helpers instead of hand-rolling
offset/limit logic, so pagination behavior and DTO shapes stay
consistent across slices.

see implementation notes below.
"""
# @TODO(app/lib/pagination.py)
# SQLite test warning: DISTINCT ON style query is tolerated today but
# deprecated for non-PostgreSQL backends. Rework pagination/count path so
# SQLite and future SQLAlchemy versions do not break.

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import ceil
from typing import Any, TypeVar, overload

U = TypeVar("U")

# Optional SQLAlchemy support (works whether SA is present or not)
try:
    from sqlalchemy.orm import Query
    from sqlalchemy.sql import Select

    _HAS_SA = True
except Exception:  # pragma: no cover
    Query = Any  # type: ignore
    Select = Any  # type: ignore
    _HAS_SA = False


@dataclass(frozen=True)
class Page[T]:
    """Immutable pagination result.

    items: the items for *this* page
    total: total number of items across all pages
    page:  1-based page number
    per_page: page size requested
    next_page / prev_page: 1-based page numbers or None at edges
    """

    items: Sequence[T]
    total: int
    page: int
    per_page: int
    next_page: int | None
    prev_page: int | None

    @property
    def pages(self) -> int:
        return ceil(self.total / self.per_page) if self.per_page > 0 else 1

    @property
    def has_prev(self) -> bool:
        return self.prev_page is not None

    @property
    def has_next(self) -> bool:
        return self.next_page is not None

    @property
    def prev_num(self) -> int:
        return self.prev_page or 1

    @property
    def next_num(self) -> int:
        return self.next_page or max(1, self.pages)

    def map(self, f: Callable[[T], U]) -> Page[U]:
        """Transform items, preserve metadata."""
        return Page(
            items=[f(x) for x in self.items],
            total=self.total,
            page=self.page,
            per_page=self.per_page,
            next_page=self.next_page,
            prev_page=self.prev_page,
        )

    def to_dict(self, map_item: Callable[[T], Any] | None = None) -> dict:
        """DTO-friendly shape for contracts/responses."""
        data_items = (
            [map_item(x) for x in self.items]
            if map_item
            else list(self.items)
        )
        return {
            "items": data_items,
            "meta": {
                "page": self.page,
                "per_page": self.per_page,
                "total": self.total,
                "pages": self.pages,
                "next_page": self.next_page,
                "prev_page": self.prev_page,
            },
        }


def _normalize(
    page: int, per_page: int, max_per_page: int | None
) -> tuple[int, int]:
    p = 1 if page is None or page < 1 else int(page)
    pp = 10 if per_page is None or per_page < 1 else int(per_page)
    if max_per_page and pp > max_per_page:
        pp = max_per_page
    return p, pp


def _edges(
    page: int, per_page: int, total: int
) -> tuple[int | None, int | None]:
    pages = ceil(total / per_page) if per_page else 1
    prev_page = page - 1 if page > 1 else None
    next_page = page + 1 if page < pages else None
    return next_page, prev_page


def rewrap_page[T, U](page: Page[T], items: Sequence[U]) -> Page[U]:
    """Reuse paging metadata but replace items."""
    return Page(
        items=items,
        total=page.total,
        page=page.page,
        per_page=page.per_page,
        next_page=page.next_page,
        prev_page=page.prev_page,
    )


# ----------------------------
# Sequence / in-memory sources
# ----------------------------


def paginate_list[
    T
](
    items: Sequence[T],
    *,
    page: int = 1,
    per_page: int = 10,
    max_per_page: int | None = 100,
) -> Page[T]:
    """Paginate an in-memory list/sequence."""
    page, per_page = _normalize(page, per_page, max_per_page)
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    page_items = items[start:end]
    next_page, prev_page = _edges(page, per_page, total)
    return Page(page_items, total, page, per_page, next_page, prev_page)


# ----------------------------
# SQLAlchemy helpers (optional)
# ----------------------------


@overload
def paginate_sa(
    source: Query,
    *,
    page: int = 1,
    per_page: int = 10,
    max_per_page: int | None = 100,
) -> Page[Any]:
    ...


@overload
def paginate_sa(
    source: Select,
    *,
    page: int = 1,
    per_page: int = 10,
    max_per_page: int | None = 100,
) -> Page[Any]:
    ...


def paginate_sa(
    source: Query | Select,
    *,
    page: int = 1,
    per_page: int = 10,
    max_per_page: int | None = 100,
    scalar: bool = False,
) -> Page[Any]:
    """Paginate a SQLAlchemy Query/Select.

    If scalar=True, return a flat list for single-column Query/Select.
    """
    if not _HAS_SA:
        raise RuntimeError(
            "SQLAlchemy is not available; cannot paginate this source."
        )

    from flask import current_app
    from flask_sqlalchemy import SQLAlchemy

    ext = current_app.extensions.get("sqlalchemy")
    if ext is None:
        raise RuntimeError("Flask-SQLAlchemy extension not initialized")
    # Flask-SQLAlchemy 3.x stores the SQLAlchemy instance directly in
    # current_app.extensions["sqlalchemy"]. Older code sometimes wraps
    # it and exposes the instance as .db.
    db: SQLAlchemy = getattr(ext, "db", ext)  # type: ignore[assignment]

    page, per_page = _normalize(page, per_page, max_per_page)

    if isinstance(source, Query):
        total = source.order_by(None).count()
        rows = source.limit(per_page).offset((page - 1) * per_page).all()
        if scalar:
            items = [r[0] if isinstance(r, tuple) else r for r in rows]
        else:
            items = rows
    else:
        count_stmt = db.select(db.func.count()).select_from(
            source.order_by(None).subquery()
        )
        total = db.session.execute(count_stmt).scalar_one()

        stmt = source.limit(per_page).offset((page - 1) * per_page)
        result = db.session.execute(stmt)
        items = list(result.scalars()) if scalar else list(result.all())

    next_page, prev_page = _edges(page, per_page, total)
    return Page(items, total, page, per_page, next_page, prev_page)


# ----------------------------
# Unified entry point
# ----------------------------


def paginate[
    T
](
    source: Sequence[T] | Query | Select,
    *,
    page: int = 1,
    per_page: int = 10,
    max_per_page: int | None = 100,
) -> Page[T]:
    """Smart paginate: works for sequences or SQLAlchemy sources."""
    if _HAS_SA and isinstance(source, (Query, Select)):  # type: ignore[arg-type]
        return paginate_sa(
            source, page=page, per_page=per_page, max_per_page=max_per_page
        )  # type: ignore[return-value]
    if isinstance(source, Sequence):
        return paginate_list(
            source, page=page, per_page=per_page, max_per_page=max_per_page
        )
    raise TypeError(
        "Unsupported source for paginate(). Pass a Sequence, Query, or Select."
    )


__all__ = [
    "Page",
    "paginate_list",
    "paginate_sa",
    "paginate",
    "U",
    "rewrap_page",
]


"""
Routes / contracts usage

If your route/contract wants a JSON-ish response,
Route (or contract) just calls to_dict():

page_obj = entity_services.list_people(page=page, per_page=per_page)
return page_obj.to_dict()

That keeps response shape uniform across slices.
That yields:

{
  "items": [...],
  "meta": {
    "page": 1,
    "per_page": 20,
    "total": 123,
    "pages": 7,
    "next_page": 2,
    "prev_page": null
  }
}

(That’s exactly what to_dict() builds.)


Alternate pattern (sometimes handy):
If you ever want services to return raw ORM rows and let the caller pick
the mapping shape:

page_obj = paginate_sa(q, page=page, per_page=per_page)
return page_obj.to_dict(map_item=map_person_view)

That uses the optional map_item hook in to_dict().
"""
