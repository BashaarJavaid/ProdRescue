"""MCP call-site scoping and the GitHub dry-run fallback."""
import pytest
from services.agents.mcp_clients import (
    AGENT_MCP_SERVERS,
    ScopeError,
    mcp_call,
    resolve_path,
)

REPO = ["src/payments/processor.py", "src/payments/__init__.py", "tests/test_x.py"]


def test_resolve_path_exact():
    assert resolve_path("src/payments/processor.py", REPO) == "src/payments/processor.py"


def test_resolve_path_strips_leading_segment():
    # Triage kept a leading 'app/' from the stacktrace.
    assert resolve_path("app/src/payments/processor.py", REPO) == "src/payments/processor.py"


def test_resolve_path_unique_basename():
    # Triage dropped the 'src/' prefix entirely → fall back to basename match.
    assert resolve_path("payments/processor.py", REPO) == "src/payments/processor.py"


def test_resolve_path_gives_up_on_unknown():
    assert resolve_path("does/not/exist.py", REPO) is None


def test_scope_map_is_least_privilege():
    assert AGENT_MCP_SERVERS["triage"] == ["logs_db"]
    assert AGENT_MCP_SERVERS["dev"] == ["github"]
    assert AGENT_MCP_SERVERS["qa"] == ["harness"]
    assert AGENT_MCP_SERVERS["pr"] == ["github"]


@pytest.mark.parametrize(
    "agent,server",
    [("triage", "github"), ("triage", "harness"), ("dev", "harness"),
     ("qa", "github"), ("pr", "logs_db")],
)
async def test_out_of_scope_blocked(agent, server):
    with pytest.raises(ScopeError):
        await mcp_call(agent, server, "any_tool", {})


async def test_github_dryrun_get_file_contents(monkeypatch):
    # No token → dry-run path reads the local target checkout.
    from services.agents import mcp_clients
    monkeypatch.setattr(mcp_clients.settings, "github_token", "")
    out = await mcp_call("dev", "github", "get_file_contents",
                         {"path": "src/payments/processor.py"})
    assert "def charge" in out["content"]


async def test_github_dryrun_pull_request(monkeypatch, tmp_path):
    from services.agents import mcp_clients
    monkeypatch.setattr(mcp_clients.settings, "github_token", "")
    monkeypatch.setattr(mcp_clients, "_DRYRUN_DIR", tmp_path / "dryrun")
    pr = await mcp_call("pr", "github", "create_pull_request",
                        {"title": "t", "body": "b", "branch": "prodrescue/x", "patch_diff": "d"})
    assert pr["dry_run"] is True
    assert (tmp_path / "dryrun" / "prodrescue_x.md").exists()


async def test_github_dryrun_pull_request_idempotent(monkeypatch, tmp_path):
    # A re-run of the same incident branch must not write/return a second PR.
    from services.agents import mcp_clients
    monkeypatch.setattr(mcp_clients.settings, "github_token", "")
    monkeypatch.setattr(mcp_clients, "_DRYRUN_DIR", tmp_path / "dryrun")
    args = {"title": "t", "body": "b", "branch": "prodrescue/x", "patch_diff": "d"}
    await mcp_call("pr", "github", "create_pull_request", args)
    second = await mcp_call("pr", "github", "create_pull_request", args)
    assert second["deduplicated"] is True


# ── Real GitHub path (B2 draft+reviewers, B3 SHA-conflict) with a fake PyGithub ──
def _patch_github(monkeypatch, repo):
    import github
    from services.agents import mcp_clients
    monkeypatch.setattr(mcp_clients.settings, "github_token", "tok")
    monkeypatch.setattr(mcp_clients.settings, "repo_full_name", "o/r")
    monkeypatch.setattr(github, "Github", lambda *a, **k: type("GH", (), {"get_repo": lambda s, n: repo})())


async def test_real_pr_is_draft_and_requests_reviewers(monkeypatch):
    pytest.importorskip("github")
    from services.agents import mcp_clients
    monkeypatch.setattr(mcp_clients.settings, "auto_pr_draft", True)
    monkeypatch.setattr(mcp_clients.settings, "pr_reviewers", "alice, bob")
    seen = {}

    class FakePR:
        html_url = "https://github.com/o/r/pull/7"
        number = 7

        def create_review_request(self, reviewers):
            seen["reviewers"] = reviewers

    class FakeRepo:
        owner = type("O", (), {"login": "o"})()
        default_branch = "main"

        def get_pulls(self, state, head):
            return []

        def create_pull(self, title, body, head, base, draft):
            seen["draft"] = draft
            return FakePR()

    _patch_github(monkeypatch, FakeRepo())
    out = await mcp_call("pr", "github", "create_pull_request",
                         {"title": "t", "body": "b", "branch": "prodrescue/x"})
    assert out["draft"] is True and seen["draft"] is True
    assert seen["reviewers"] == ["alice", "bob"]


async def test_put_file_raises_on_conflict(monkeypatch):
    pytest.importorskip("github")
    from github import GithubException

    class FakeRepo:
        def get_contents(self, path, ref):
            raise GithubException(409, {"message": "conflict"}, {})

        def create_file(self, *a, **k):
            raise AssertionError("must not silently create on a real conflict")

    _patch_github(monkeypatch, FakeRepo())
    with pytest.raises(GithubException):
        await mcp_call("pr", "github", "put_file",
                       {"branch": "b", "path": "p", "content": "c"})


async def test_put_file_creates_when_absent(monkeypatch):
    pytest.importorskip("github")
    from github import GithubException
    seen = {}

    class FakeRepo:
        def get_contents(self, path, ref):
            raise GithubException(404, {"message": "not found"}, {})

        def create_file(self, path, message, content, branch):
            seen["created"] = True

    _patch_github(monkeypatch, FakeRepo())
    out = await mcp_call("pr", "github", "put_file",
                         {"branch": "b", "path": "p", "content": "c"})
    assert out["created"] is True and seen["created"] is True
