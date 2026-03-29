from __future__ import annotations

from app.slices.admin import services as svc


def test_policy_index_page_maps_contract_data(monkeypatch):
    monkeypatch.setattr(
        svc.governance_v2,
        "list_policies",
        lambda validate=False: {
            "ok": True,
            "policies": [
                {
                    "key": "policy_sample",
                    "title": "Sample Policy",
                    "status": "active",
                    "version": "1.2.3",
                    "focus": "sample",
                    "has_schema": True,
                    "schema_ok": True,
                    "semantic_ok": True,
                    "semantic_warning_count": 0,
                    "semantic_error_count": 0,
                    "issue_count": 0,
                }
            ],
        },
    )

    page = svc.get_policy_index_page()

    assert page.health.policy_count == 1
    assert page.health.valid_count == 1
    assert page.items[0].key == "policy_sample"
    assert page.items[0].review_route == "/admin/policy/policy_sample/"


def test_policy_detail_page_maps_validation_and_text(monkeypatch):
    monkeypatch.setattr(
        svc.governance_v2,
        "get_policy",
        lambda **kwargs: {
            "ok": True,
            "key": "policy_sample",
            "meta": {
                "title": "Sample Policy",
                "policy_key": "sample",
                "status": "draft",
                "version": "1.0.0",
                "schema_version": "2020-12",
                "effective_on": "2026-03-29",
            },
            "current_hash": "abc123",
            "normalized_text": '{\n  "flag": true\n}\n',
            "has_schema": True,
            "schema_ok": True,
            "semantic_ok": False,
            "issues": [
                {
                    "source": "semantic",
                    "severity": "warning",
                    "path": "meta.notes",
                    "message": "Expected meta.notes to be a list.",
                }
            ],
        },
    )

    page = svc.get_policy_detail_page("policy_sample")

    assert page.policy_key == "policy_sample"
    assert page.current_hash == "abc123"
    assert page.current_text.startswith("{")
    assert page.issues[0].source == "semantic"
    assert page.preview_route == "/admin/policy/policy_sample/preview"


def test_policy_preview_page_uses_contract_preview(monkeypatch):
    monkeypatch.setattr(
        svc.governance_v2,
        "preview_policy_update",
        lambda **kwargs: {
            "ok": True,
            "current_hash": "oldhash",
            "proposed_hash": "newhash",
            "normalized_text": '{\n  "flag": false\n}\n',
            "diff_lines": ["--- current", "+++ proposed"],
            "issues": [],
            "change_summary": ["Changed top-level keys: flag"],
            "commit_allowed": True,
        },
    )

    page = svc.build_policy_preview_page(
        policy_key="policy_sample",
        new_policy={"flag": False},
        base_hash="oldhash",
    )

    assert page.current_hash == "oldhash"
    assert page.proposed_hash == "newhash"
    assert page.commit_allowed is True
    assert page.diff_lines[0] == "--- current"
