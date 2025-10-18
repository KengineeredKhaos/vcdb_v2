def test_create_project_and_task(app):
    from app.slices.calendar import services as cal

    p = cal.create_project(title="Pilot", owner_ulid="01OWNER")
    t = cal.create_task(project_ulid=p["ulid"], title="Kickoff")
    assert t["project_ulid"] == p["ulid"]
