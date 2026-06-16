"""The coverage-delta gate / retry routing (the heart of the self-healing loop)."""
from langgraph.graph import END
from services.agents.graph import route_after_qa


def test_pass_with_nonneg_coverage_opens_pr():
    assert route_after_qa({"harness_result": {"passed": True, "coverage_delta": 0.0}}) == "pr"
    assert route_after_qa({"harness_result": {"passed": True, "coverage_delta": 5.0}}) == "pr"


def test_pass_but_coverage_regression_blocks_pr():
    # Deleting tests to "fix" the bug must NOT open a PR — it retries instead.
    assert route_after_qa(
        {"harness_result": {"passed": True, "coverage_delta": -1.0}, "retry_count": 0}
    ) == "dev"


def test_fail_retries_until_limit():
    for rc in (0, 1, 2):
        assert route_after_qa(
            {"harness_result": {"passed": False, "coverage_delta": 1.0}, "retry_count": rc}
        ) == "dev"


def test_fail_gives_up_at_limit():
    assert route_after_qa(
        {"harness_result": {"passed": False, "coverage_delta": 1.0}, "retry_count": 3}
    ) == END


def test_missing_result_treated_as_failure():
    assert route_after_qa({"retry_count": 0}) == "dev"
    assert route_after_qa({"retry_count": 3}) == END
