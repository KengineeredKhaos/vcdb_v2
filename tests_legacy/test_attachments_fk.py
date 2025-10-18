from app.slices.attachments.models import Attachment, AttachmentLink
from app.extensions import db
from app.lib.ids import new_ulid


def test_attachment_link_fk(db):
    a = Attachment(
        sha256="a" * 64,
        size_bytes=1234,
        mime="application/pdf",
        original_filename="doc.pdf",
        storage_key="sha256/aa/aa/a.../doc.pdf",
        created_by_actor=None,
    )
    db.session.add(a)
    db.session.commit()

    link = AttachmentLink(
        attachment_ulid=a.ulid,
        slice="resources",
        domain="mou",
        target_ulid=new_ulid(),
        note="test",
    )
    db.session.add(link)
    db.session.commit()

    # Relationship works both ways
    assert link.attachment.ulid == a.ulid
    assert a.links[0].ulid == link.ulid
