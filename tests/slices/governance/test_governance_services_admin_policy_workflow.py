from __future__ import annotations

import json
from pathlib import Path

from app.slices.governance import services_admin as svc


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _make_policy_files(tmp_path: Path) -> tuple[Path, Path]:
    data_dir = tmp_path / "data"
    schema_dir = data_dir / "schemas"
    schema_dir.mkdir(parents=True)

    policy = {
        "meta": {
            "policy_key": "sample",
            "title": "Sample Policy",
            "status": "draft",
            "version": "1.0.0",
            "schema_version": "2020-12",
            "effective_on": "2026-03-29",
            "notes": [],
        },
        "flag": True,
    }
    schema = {
        "type": "object",
        "required": ["meta", "flag"],
        "properties": {
            "meta": {
                "type": "object",
                "required": [
                    "policy_key",
                    "title",
                    "status",
                    "version",
                    "schema_version",
                    "effective_on",
                ],
                "properties": {
                    "policy_key": {"type": "string"},
                    "title": {"type": "string"},
                    "status": {"type": "string"},
                    "version": {"type": "string"},
                    "schema_version": {"type": "string"},
                    "effective_on": {"type": "string"},
                    "notes": {"type": "array"},
                },
            },
            "flag": {"type": "boolean"},
        },
    }

    _write_json(data_dir / "policy_sample.json", policy)
    _write_json(schema_dir / "policy_sample.schema.json", schema)
    return data_dir, schema_dir


def test_preview_update_reports_hashes_and_diff(app, monkeypatch, tmp_path):
    with app.app_context():
        data_dir, schema_dir = _make_policy_files(tmp_path)
        monkeypatch.setattr(svc, "_gov_data_dir", lambda: data_dir)
        monkeypatch.setattr(svc, "_schemas_dir", lambda: schema_dir)

        current = svc.get_policy_impl("policy_sample", validate=True)
        result = svc.preview_update_impl(
            key="policy_sample",
            new_policy={
                "meta": {
                    "policy_key": "sample",
                    "title": "Sample Policy",
                    "status": "active",
                    "version": "1.0.1",
                    "schema_version": "2020-12",
                    "effective_on": "2026-03-29",
                    "notes": [],
                },
                "flag": False,
            },
            base_hash=current["current_hash"],
        )

        assert result["ok"] is True
        assert result["commit_allowed"] is True
        assert result["current_hash"] == current["current_hash"]
        assert result["proposed_hash"]
        assert result["diff_summary"]["changed_keys"] == ["flag", "meta"]
        assert result["diff_lines"]


def test_preview_update_rejects_stale_base_hash(app, monkeypatch, tmp_path):
    with app.app_context():
        data_dir, schema_dir = _make_policy_files(tmp_path)
        monkeypatch.setattr(svc, "_gov_data_dir", lambda: data_dir)
        monkeypatch.setattr(svc, "_schemas_dir", lambda: schema_dir)

        result = svc.preview_update_impl(
            key="policy_sample",
            new_policy={
                "meta": {
                    "policy_key": "sample",
                    "title": "Sample Policy",
                    "status": "draft",
                    "version": "1.0.0",
                    "schema_version": "2020-12",
                    "effective_on": "2026-03-29",
                    "notes": [],
                },
                "flag": True,
            },
            base_hash="not-the-current-hash",
        )

        assert result["ok"] is True
        assert result["commit_allowed"] is False
        assert result["base_hash_matches"] is False
        assert any(
            issue["source"] == "stale_preview" for issue in result["issues"]
        )


def test_commit_update_writes_backup_and_emits_event(
    app,
    monkeypatch,
    tmp_path,
):
    with app.app_context():
        data_dir, schema_dir = _make_policy_files(tmp_path)
        monkeypatch.setattr(svc, "_gov_data_dir", lambda: data_dir)
        monkeypatch.setattr(svc, "_schemas_dir", lambda: schema_dir)

        current = svc.get_policy_impl("policy_sample", validate=True)
        preview = svc.preview_update_impl(
            key="policy_sample",
            new_policy={
                "meta": {
                    "policy_key": "sample",
                    "title": "Sample Policy",
                    "status": "active",
                    "version": "1.0.1",
                    "schema_version": "2020-12",
                    "effective_on": "2026-03-29",
                    "notes": [],
                },
                "flag": False,
            },
            base_hash=current["current_hash"],
        )

        events: list[dict] = []
        monkeypatch.setattr(
            svc.event_bus,
            "emit",
            lambda **kwargs: events.append(kwargs),
        )

        result = svc.commit_update_impl(
            key="policy_sample",
            new_policy=json.loads(preview["normalized_text"]),
            actor_ulid="01H00000000000000000000000",
            reason="Test commit",
            base_hash=current["current_hash"],
            proposed_hash=preview["proposed_hash"],
        )

        assert result["ok"] is True
        assert result["committed"] is True
        assert result["backup_ref"]
        assert Path(result["backup_ref"]).exists()
        assert events
        assert events[0]["refs"]["reason"] == "Test commit"

        saved = json.loads((data_dir / "policy_sample.json").read_text())
        assert saved["flag"] is False
