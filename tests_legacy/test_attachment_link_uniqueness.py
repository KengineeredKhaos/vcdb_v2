def test_attachment_link_uniqueness(app):
    from app.slices.attachments import services as att

    a = att.ensure_attachment(
        sha256="x" * 64, size=1, mime="text/plain", storage_key="k"
    )
    att.link(
        attachment_ulid=a["ulid"],
        slice="resources",
        domain="capability",
        target_ulid="01T",
    )
    with app.pytest.raises(Exception):
        att.link(
            attachment_ulid=a["ulid"],
            slice="resources",
            domain="capability",
            target_ulid="01T",
        )
