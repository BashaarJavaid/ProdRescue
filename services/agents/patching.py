"""Apply a unified diff to a single file's text (used by the PR node).

Shells out to ``git apply`` inside a throwaway temp repo so standard
``--- a/path / +++ b/path`` diffs apply cleanly without a local checkout.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


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
