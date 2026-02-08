# app/lib/pagination.py
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from math import ceil
from typing import (
    Any,
    Generic,
    TypeVar,
    overload,
)

T = TypeVar("T")
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
class Page(Generic[T]):
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


# ----------------------------
# Sequence / in-memory sources
# ----------------------------


def paginate_list(
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
) -> Page[Any]: ...


@overload
def paginate_sa(
    source: Select,
    *,
    page: int = 1,
    per_page: int = 10,
    max_per_page: int | None = 100,
) -> Page[Any]: ...


def paginate_sa(
    source: Query | Select,
    *,
    page: int = 1,
    per_page: int = 10,
    max_per_page: int | None = 100,
) -> Page[Any]:
    """Paginate a SQLAlchemy Query/Select. Works with ORM Query or Core Select.
    Requires SQLAlchemy to be installed and configured.
    """
    if not _HAS_SA:
        raise RuntimeError(
            "SQLAlchemy is not available; cannot paginate this source."
        )

    from flask import current_app
    from flask_sqlalchemy import (
        SQLAlchemy,
    )  # assume you're using Flask-SQLAlchemy

    db: SQLAlchemy = current_app.extensions["sqlalchemy"].db  # type: ignore

    page, per_page = _normalize(page, per_page, max_per_page)

    # Build count() safely
    if isinstance(source, Query):
        total = source.order_by(None).count()
        items = source.limit(per_page).offset((page - 1) * per_page).all()
    else:
        # Core Select
        count_stmt = db.select(db.func.count()).select_from(
            source.order_by(None).subquery()
        )
        total = db.session.execute(count_stmt).scalar_one()
        items = list(
            db.session.execute(
                source.limit(per_page).offset((page - 1) * per_page)
            ).scalars()
        )

    next_page, prev_page = _edges(page, per_page, total)
    return Page(items, total, page, per_page, next_page, prev_page)


# ----------------------------
# Unified entry point
# ----------------------------


def paginate(
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
