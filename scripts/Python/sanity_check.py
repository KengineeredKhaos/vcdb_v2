# sanity_check.py
from app import create_app

app = create_app("config.DevConfig")
with app.app_context():
    from app.extensions import entity_read

    rows, total = entity_read.list_people_with_role("customer", 1, 5)
    assert isinstance(rows, list)
    if rows:
        r = rows[0]
        for k in [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "is_customer",
            "updated_at_utc",
        ]:
            assert k in r
    print("OK")
