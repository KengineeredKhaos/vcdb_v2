from __future__ import annotations

from app.extensions.contracts import entity_v2


def test_entity_v2_create_operator_core_uses_preferred_name(app):
    with app.app_context():
        created = entity_v2.create_operator_core(
            first_name="Michael",
            last_name="Shaw",
            preferred_name="Mike",
            actor_ulid="01ACTORACTORACTORACTORACT",
            request_id="01REQREQREQREQREQREQREQRE",
        )

        assert created.entity_kind == "person"
        assert created.display_name == "Mike Shaw"
