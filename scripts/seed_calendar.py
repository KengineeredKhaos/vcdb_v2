# scripts/seed_calendar.py
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from app.extensions import db
from app.lib.chrono import now_iso8601_ms, parse_iso8601, to_iso8601
from app.slices.calendar.models import Calendar, Project

# ---- helpers ---------------------------------------------------------------


def _iso_day_window(anchor_iso: Optional[str] = None) -> tuple[str, str]:
    """
    Return a same-day window [00:00:00, 23:59:59.999] in ISO-8601 Z strings.
    If anchor_iso is None, uses 'today' from now_iso8601_ms().
    """
    # anchor "now"
    anchor = parse_iso8601(anchor_iso or now_iso8601_ms())
    # normalize to midnight UTC
    day_start = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1, microseconds=-1)
    return to_iso8601(day_start), to_iso8601(day_end)


# ---- seeds -----------------------------------------------------------------


def seed_project() -> Project:
    """
    Create or fetch a simple dev project with no owner/fund.
    """
    title = "Sample Dev Project"
    p = Project.query.filter_by(project_title=title).one_or_none()
    if p:
        return p

    p = Project(
        project_title=title,
        status="planning",  # free-form status; consistent with our model
        owner_ulid=None,  # intentionally not assigned
        fund_ulid=None,  # intentionally not funded
        # created_at_utc / updated_at_utc come from IsoTimestamps defaults
    )
    db.session.add(p)
    db.session.commit()
    return p


def seed_holiday() -> Calendar:
    """
    Create or fetch a benign “holiday” event with no assignments, no links.
    """
    event_title = "Office Closed (Sample Holiday)"
    starts_iso, ends_iso = _iso_day_window()  # all-day window

    existing = Calendar.query.filter_by(
        event_title=event_title,
        status="holiday",
        starts_at_utc=starts_iso,
        ends_at_utc=ends_iso,
    ).one_or_none()
    if existing:
        return existing

    c = Calendar(
        status="holiday",
        event_title=event_title,
        starts_at_utc=starts_iso,
        ends_at_utc=ends_iso,
        owner_ulid=None,
        assigned_to_ulid=None,
        project_ulid=None,
        task_ulid=None,
        # created_at_utc / updated_at_utc via IsoTimestamps
    )
    db.session.add(c)
    db.session.commit()
    return c


def run() -> None:
    """
    Safe to run multiple times.
    """
    proj = seed_project()
    hol = seed_holiday()
    print("✓ calendar seeded")
    print(f"  - project: {proj.project_title} [{proj.ulid}]")
    print(
        f"  - holiday: {hol.event_title} {hol.starts_at_utc} → {hol.ends_at_utc}"
    )


if __name__ == "__main__":
    # Run with: FLASK_ENV=development flask --app manage_vcdb.py shell -c "import scripts.seed_calendar as s; s.run()"
    run()
