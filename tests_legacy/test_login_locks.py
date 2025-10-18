def test_failed_login_locks_user(client, app):
    from app.slices.auth.models import User

    u = User.query.filter_by(email="admin@example.com").one()
    for _ in range(5):
        client.post(
            "/auth/login", data={"ident": u.email, "password": "nope"}
        )
    app.db.session.refresh(u)
    assert u.is_locked is True
