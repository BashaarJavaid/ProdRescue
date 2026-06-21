"""Apply a unified diff to a single file's text (used by the PR node).

Shells out to ``git apply`` inside a throwaway temp repo so standard
``--- a/path / +++ b/path`` diffs apply cleanly without a local checkout.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

_DIFF_TARGET = re.compile(r"^\+\+\+ b/(.+)$", re.M)


def check_patch_scope(
    file_path: str,
    patched_file: str,
    original_len: int,
    patch_diff: str,
    max_growth: float,
) -> str | None:
    """Return a rejection reason if the patch is out of scope, else None.

    Cheap guards before we spend a Docker stack on QA. The applied artifacts are
    structurally scoped (full file → ``file_path``, fixture → ``conftest.py``), so
    this mainly catches: (a) the LLM ballooning the file, and (b) a diff (PR body /
    fallback apply) that edits other files or existing tests.

    ponytail: a malicious conftest can still neutralize tests at runtime; detecting
    that needs more than a static check. Upgrade path = run the pristine suite under
    the patched conftest and require the same test ids to execute.
    """
    if original_len and len(patched_file) > original_len * max_growth:
        ratio = len(patched_file) / original_len
        return f"patched file grew {ratio:.1f}x (limit {max_growth}x)"

    for target in _DIFF_TARGET.findall(patch_diff):
        t = target.strip()
        if t == file_path or t.endswith("conftest.py"):
            continue
        return f"diff touches out-of-scope path '{t}' (allowed: {file_path}, conftest.py)"
    return None


def apply_unified_diff(original: str, diff: str, rel_path: str) -> str:
    """Return the patched contents of ``rel_path`` after applying ``diff``."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(original)

        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        diff_text = diff if diff.endswith("\n") else diff + "\n"

        git = subprocess.run(
            ["git", "apply", "--unsafe-paths", "-p1", "-"],
            cwd=root, input=diff_text, text=True, capture_output=True,
        )
        if git.returncode == 0:
            return target.read_text()

        # LLM diffs often have wrong line numbers/context; --fuzz tolerates drift.
        patch = subprocess.run(
            ["patch", "-p1", "--fuzz=3", "--no-backup-if-mismatch"],
            cwd=root, input=diff_text, text=True, capture_output=True,
        )
        if patch.returncode != 0:
            raise ValueError(
                f"diff did not apply (git: {git.stderr.strip()}; "
                f"patch: {patch.stderr.strip()})"
            )
        return target.read_text()
