"""Schema contract tests for the Pydantic models shared across agents."""
from uuid import uuid4

from services.schemas.models import (
    ErrorLog,
    HarnessResult,
    HarnessSpec,
    PatchOutput,
    TriageOutput,
)


def test_harness_spec_defaults():
    spec = HarnessSpec(file_path="src/payments/processor.py")
    assert spec.env_vars == {}
    assert spec.mocked_services == []
    assert spec.timeout_seconds == 120
    assert spec.expected_exit_code == 0


def test_harness_spec_roundtrip():
    spec = HarnessSpec(
        file_path="a.py", env_vars={"X": "1"}, db_seed_sql="SELECT 1",
        mocked_services=["redis"], timeout_seconds=60,
    )
    assert HarnessSpec(**spec.model_dump()) == spec


def test_harness_result_requires_coverage_delta():
    r = HarnessResult(run_id=uuid4(), passed=True, coverage_delta=1.5, duration_ms=10)
    assert r.failed_assertions == []
    assert r.teardown_clean is True
    assert r.recorded_at is not None


def test_error_log_optional_stacktrace():
    log = ErrorLog(service="s", message="m", occurred_at="2026-06-16T10:30:00Z")
    assert log.stacktrace == ""
    assert log.metadata == {}


def test_triage_and_patch_outputs():
    t = TriageOutput(
        root_cause="rc", affected_file="f.py",
        harness_spec=HarnessSpec(file_path="f.py"),
    )
    assert t.harness_spec.file_path == "f.py"
    p = PatchOutput(patched_file="full", patch_diff="d", conftest="c", explanation="e")
    assert p.patch_diff == "d"
    assert p.patched_file == "full"
