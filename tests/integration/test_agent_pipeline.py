"""Integration: the harness lifecycle against sample_target via real Docker.

Requires Docker. Run with: RUN_INTEGRATION=1 pytest tests/integration -m integration
"""
import difflib
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION") != "1", reason="integration stack not running"
)

REL = "src/payments/processor.py"


def _fix_diff() -> str:
    src = (Path("sample_target") / REL).read_text()
    fixed = src.replace(
        "    # BUG: no None-guard — `order.total` explodes when order is None.\n"
        "    amount = order.total * 100\n",
        "    if order is None:\n        raise PaymentError('no order provided')\n"
        "    amount = order.total * 100\n",
    )
    return "".join(difflib.unified_diff(
        src.splitlines(keepends=True), fixed.splitlines(keepends=True),
        fromfile=f"a/{REL}", tofile=f"b/{REL}",
    ))


async def test_harness_patch_flips_red_to_green():
    from services.mcp_servers.harness import server

    spin = await server.spin_up_stack({"file_path": REL, "timeout_seconds": 120})
    stack_id = spin["stack_id"]
    try:
        before = await server.run_pytest(stack_id)
        assert before["passed"] is False
        applied = await server.apply_patch(stack_id, _fix_diff(), conftest="")
        assert applied["applied"], applied["stderr"]
        after = await server.run_pytest(stack_id)
        assert after["passed"] is True
        assert after["coverage_delta"] >= 0
    finally:
        await server.teardown_stack(stack_id)

    leaked = [n for n in subprocess.run(
        ["docker", "network", "ls", "--format", "{{.Name}}"],
        capture_output=True, text=True).stdout.split() if stack_id in n]
    assert not leaked
