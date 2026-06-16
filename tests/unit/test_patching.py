"""apply_unified_diff applies a real unified diff via git apply."""
import difflib

import pytest
from services.agents.patching import apply_unified_diff

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
