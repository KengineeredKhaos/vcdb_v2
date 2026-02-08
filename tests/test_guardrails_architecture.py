import pytest

from tools.guardrails_architecture import main


@pytest.mark.xfail(
    reason="Architecture refactor in progress; enable when guardrails are clean."
)
def test_arch_guardrails():
    assert main() == 0
