from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.slices.admin import routes


class _Field:
    def __init__(self, data=""):
        self.data = data
        self.errors = []
        self.id = "field"
        self.label = SimpleNamespace(text="Field")


class _FakeForm:
    def __init__(
        self,
        *,
        valid: bool = True,
        policy_text: str = "",
        base_hash: str = "",
        proposed_hash: str = "",
        reason: str = "",
    ):
        self._valid = valid
        self.policy_text = _Field(policy_text)
        self.base_hash = _Field(base_hash)
        self.proposed_hash = _Field(proposed_hash)
        self.reason = _Field(reason)

    def validate_on_submit(self) -> bool:
        return self._valid


def _unwrap(view):
    while hasattr(view, "__wrapped__"):
        view = view.__wrapped__
    return view


def _capture_render(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_render(template_name, **context):
        calls.append((template_name, context))
        return {
            "template": template_name,
            "context": context,
        }

    monkeypatch.setattr(routes, "render_template", fake_render)
    return calls


def _capture_flash(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_flash(message, category="message"):
        calls.append((message, category))

    monkeypatch.setattr(routes, "flash", fake_flash)
    return calls


def _capture_redirects(monkeypatch):
    calls: list[str] = []

    def fake_redirect(target):
        calls.append(target)
        return SimpleNamespace(status_code=302, location=target)

    monkeypatch.setattr(routes, "redirect", fake_redirect)
    return calls


def _capture_url_for(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_url_for(endpoint, **values):
        calls.append((endpoint, values))
        if endpoint == "admin.policy_detail":
            return f"/admin/policy/{values['policy_key']}/"
        return f"/{endpoint}"

    monkeypatch.setattr(routes, "url_for", fake_url_for)
    return calls


def test_policy_index_renders_index_template(app, monkeypatch):
    view = _unwrap(routes.policy_index)
    render_calls = _capture_render(monkeypatch)

    page = SimpleNamespace(title="Policy Workflow Surface")
    monkeypatch.setattr(
        routes.svc,
        "get_policy_index_page",
        lambda: page,
    )

    with app.test_request_context("/admin/policy/", method="GET"):
        result = view()

    assert result["template"] == "admin/policy/index.html"
    assert render_calls[0][1]["page"] is page


def test_policy_detail_seeds_form_from_page(app, monkeypatch):
    view = _unwrap(routes.policy_detail)
    render_calls = _capture_render(monkeypatch)

    page = SimpleNamespace(
        title="Policy Detail",
        current_text='{"flag": true}',
        current_hash="abc123",
    )
    form = _FakeForm()
    monkeypatch.setattr(
        routes.svc,
        "get_policy_detail_page",
        lambda policy_key: page,
    )
    monkeypatch.setattr(routes, "PolicyEditForm", lambda: form)

    with app.test_request_context(
        "/admin/policy/policy_sample/",
        method="GET",
    ):
        result = view("policy_sample")

    assert result["template"] == "admin/policy/detail.html"
    assert form.policy_text.data == page.current_text
    assert form.base_hash.data == page.current_hash
    assert render_calls[0][1]["page"] is page
    assert render_calls[0][1]["form"] is form


def test_policy_preview_parse_error_renders_preview_page(app, monkeypatch):
    view = _unwrap(routes.policy_preview)
    render_calls = _capture_render(monkeypatch)

    detail_page = SimpleNamespace(title="Detail")
    preview_page = SimpleNamespace(
        title="Preview",
        normalized_text='{"flag": true}',
        current_hash="hash-old",
        proposed_hash="",
    )
    form = _FakeForm(
        valid=True,
        policy_text='{"flag": ',
        base_hash="hash-old",
    )

    monkeypatch.setattr(
        routes.svc,
        "get_policy_detail_page",
        lambda policy_key: detail_page,
    )
    monkeypatch.setattr(
        routes.svc,
        "build_policy_preview_page_from_parse_error",
        lambda **kwargs: preview_page,
    )
    monkeypatch.setattr(routes, "PolicyEditForm", lambda: form)

    with app.test_request_context(
        "/admin/policy/policy_sample/preview",
        method="POST",
    ):
        result = view("policy_sample")

    assert result["template"] == "admin/policy/preview.html"
    assert render_calls[0][1]["page"] is preview_page
    assert render_calls[0][1]["form"] is form


def test_policy_preview_valid_json_builds_preview_page(app, monkeypatch):
    view = _unwrap(routes.policy_preview)
    render_calls = _capture_render(monkeypatch)

    detail_page = SimpleNamespace(title="Detail")
    preview_page = SimpleNamespace(
        title="Preview",
        normalized_text='{"flag": true}',
        current_hash="hash-current",
        proposed_hash="hash-proposed",
    )
    form = _FakeForm(
        valid=True,
        policy_text='{"flag": true}',
        base_hash="hash-current",
    )

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        routes.svc,
        "get_policy_detail_page",
        lambda policy_key: detail_page,
    )

    def fake_build_preview_page(*, policy_key, new_policy, base_hash):
        captured["policy_key"] = policy_key
        captured["new_policy"] = new_policy
        captured["base_hash"] = base_hash
        return preview_page

    monkeypatch.setattr(
        routes.svc,
        "build_policy_preview_page",
        fake_build_preview_page,
    )
    monkeypatch.setattr(routes, "PolicyEditForm", lambda: form)

    with app.test_request_context(
        "/admin/policy/policy_sample/preview",
        method="POST",
    ):
        result = view("policy_sample")

    assert result["template"] == "admin/policy/preview.html"
    assert captured == {
        "policy_key": "policy_sample",
        "new_policy": {"flag": True},
        "base_hash": "hash-current",
    }
    assert form.policy_text.data == preview_page.normalized_text
    assert form.base_hash.data == preview_page.current_hash
    assert form.proposed_hash.data == preview_page.proposed_hash
    assert render_calls[0][1]["page"] is preview_page


def test_policy_commit_success_commits_and_redirects(app, monkeypatch):
    view = _unwrap(routes.policy_commit)
    flash_calls = _capture_flash(monkeypatch)
    redirect_calls = _capture_redirects(monkeypatch)
    url_for_calls = _capture_url_for(monkeypatch)

    form = _FakeForm(
        valid=True,
        policy_text='{"flag": true}',
        base_hash="hash-current",
        proposed_hash="hash-proposed",
        reason="operator note",
    )

    captured: dict[str, object] = {}
    committed = {"count": 0}

    monkeypatch.setattr(routes, "PolicyEditForm", lambda: form)
    monkeypatch.setattr(routes, "_actor_ulid", lambda: "01TESTACTORULID")

    def fake_commit_policy_update(**kwargs):
        captured.update(kwargs)
        return {"new_hash": "hash-new"}

    monkeypatch.setattr(
        routes.svc,
        "commit_policy_update",
        fake_commit_policy_update,
    )
    monkeypatch.setattr(
        routes.db.session,
        "commit",
        lambda: committed.__setitem__("count", committed["count"] + 1),
    )

    with app.test_request_context(
        "/admin/policy/policy_sample/commit",
        method="POST",
    ):
        result = view("policy_sample")

    assert result.status_code == 302
    assert redirect_calls == ["/admin/policy/policy_sample/"]
    assert url_for_calls == [
        ("admin.policy_detail", {"policy_key": "policy_sample"})
    ]
    assert committed["count"] == 1
    assert captured == {
        "policy_key": "policy_sample",
        "new_policy": {"flag": True},
        "actor_ulid": "01TESTACTORULID",
        "reason": "operator note",
        "base_hash": "hash-current",
        "proposed_hash": "hash-proposed",
    }
    assert flash_calls == [
        ("Policy policy_sample committed: hash-new", "success")
    ]


def test_policy_commit_exception_rolls_back_and_rerenders_preview(
    app,
    monkeypatch,
):
    view = _unwrap(routes.policy_commit)
    flash_calls = _capture_flash(monkeypatch)

    form = _FakeForm(
        valid=True,
        policy_text='{"flag": true}',
        base_hash="hash-current",
        proposed_hash="hash-proposed",
        reason="operator note",
    )

    rolled_back = {"count": 0}
    helper_calls: list[dict[str, object]] = []
    sentinel = object()

    monkeypatch.setattr(routes, "PolicyEditForm", lambda: form)
    monkeypatch.setattr(routes, "_actor_ulid", lambda: "01TESTACTORULID")

    def boom(**kwargs):
        raise RuntimeError("stale preview")

    def fake_render_preview(*, policy_key, form, extra_error=None):
        helper_calls.append(
            {
                "policy_key": policy_key,
                "form": form,
                "extra_error": extra_error,
            }
        )
        return sentinel

    monkeypatch.setattr(routes.svc, "commit_policy_update", boom)
    monkeypatch.setattr(
        routes.db.session,
        "rollback",
        lambda: rolled_back.__setitem__("count", rolled_back["count"] + 1),
    )
    monkeypatch.setattr(
        routes,
        "_render_policy_preview_from_form",
        fake_render_preview,
        raising=False,
    )

    with app.test_request_context(
        "/admin/policy/policy_sample/commit",
        method="POST",
    ):
        result = view("policy_sample")

    assert result is sentinel
    assert rolled_back["count"] == 1
    assert helper_calls == [
        {
            "policy_key": "policy_sample",
            "form": form,
            "extra_error": "stale preview",
        }
    ]
    assert flash_calls == []
