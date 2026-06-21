"""apply_unified_diff applies a real unified diff via git apply."""
import difflib

import pytest
from services.agents.patching import apply_unified_diff, check_patch_scope

ORIGINAL = "def charge(order):\n    amount = order.total * 100\n    return int(amount)\n"
FIXED = (
    "def charge(order):\n"
    "    if order is None:\n"
    "        raise ValueError('no order')\n"
    "    amount = order.total * 100\n"
    "    return int(amount)\n"
)
REL = "src/payments/processor.py"


def _diff(a, b):
    return "".join(
        difflib.unified_diff(
            a.splitlines(keepends=True), b.splitlines(keepends=True),
            fromfile=f"a/{REL}", tofile=f"b/{REL}",
        )
    )


def test_apply_unified_diff():
    assert apply_unified_diff(ORIGINAL, _diff(ORIGINAL, FIXED), REL) == FIXED


def test_apply_bad_diff_raises():
    with pytest.raises(ValueError):
        apply_unified_diff(ORIGINAL, "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-nope\n+yep\n", REL)


def test_scope_ok_for_affected_file_and_conftest():
    diff = f"--- a/{REL}\n+++ b/{REL}\n@@\n-x\n+y\n--- a/tests/conftest.py\n+++ b/tests/conftest.py\n@@\n+z\n"
    assert check_patch_scope(REL, FIXED, len(ORIGINAL), diff, 3.0) is None


def test_scope_rejects_other_file():
    diff = "--- a/other.py\n+++ b/other.py\n@@\n+evil\n"
    reason = check_patch_scope(REL, FIXED, len(ORIGINAL), diff, 3.0)
    assert reason and "out-of-scope" in reason


def test_scope_rejects_ballooned_file():
    reason = check_patch_scope(REL, "X" * 1000, len(ORIGINAL), "", 3.0)
    assert reason and "grew" in reason
