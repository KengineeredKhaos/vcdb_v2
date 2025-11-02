import inspect
from app.lib import security


def _params(fn):
    return list(inspect.signature(fn).parameters.keys())


def test_require_roles_any_signature():
    assert _params(security.require_roles_any) == ["*need_codes"]


def test_require_roles_all_signature():
    assert _params(security.require_roles_all) == ["*need_codes"]


def test_require_permission_signature():
    assert _params(security.require_permission) == ["permission"]


def test_helpers_present():
    assert callable(security.current_user_ulid)
    assert callable(security.current_user_roles)
    assert callable(security.user_has_any_roles)
    assert callable(security.user_has_all_roles)
    assert callable(security.user_has_permission)
    assert callable(security.require_feature)
