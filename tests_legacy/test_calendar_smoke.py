# tests/test_calendar_smoke.py
from app.slices.calendar.models import Project


def test_project_seeded(app):
    assert Project.query.count() >= 1
