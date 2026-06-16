"""MCP call helpers with least-privilege scoping enforced at the call site.

Every agent node reaches external tools through ``mcp_call(agent, server, ...)``.
``AGENT_MCP_SERVERS`` is the single auditable mapping of which node may touch
which server — calling out of scope raises immediately (spec §10.4).

Transports:
* ``logs_db`` / ``harness`` — custom FastMCP servers over streamable-http.
* ``github``               — PyGithub when GITHUB_TOKEN is set, else a dry-run
                             that writes the branch/patch/PR-body to disk.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.config import settings

# ── Least-privilege scoping (audit this table) ──────────────────
AGENT_MCP_SERVERS: dict[str, list[str]] = {
    "triage": ["logs_db"],   # can only search logs
    "dev": ["github"],       # can only read source
    "qa": ["harness"],       # can only manage Docker
    "pr": ["github"],        # can only write to GitHub
}

_SERVER_URLS = {
    "logs_db": settings.logs_db_mcp_url,
    "harness": settings.harness_mcp_url,
}


class ScopeError(RuntimeError):
    """Raised when an agent calls a server outside its allow-list."""


def _assert_scope(agent: str, server: str) -> None:
    allowed = AGENT_MCP_SERVERS.get(agent, [])
    if server not in allowed:
        raise ScopeError(
            f"agent '{agent}' may not call server '{server}' (allowed: {allowed})"
        )


async def mcp_call(agent: str, server: str, tool: str, args: dict | None = None) -> Any:
    """Dispatch a scoped tool call. ``args`` keys become tool arguments."""
    _assert_scope(agent, server)
    args = args or {}
    if server in _SERVER_URLS:
        return await _streamable_http_call(_SERVER_URLS[server], tool, args)
    if server == "github":
        return await _github_call(tool, args)
    raise ValueError(f"unknown MCP server: {server}")


# ── streamable-http MCP transport (logs_db, harness) ────────────
def _parse_tool_result(result: Any) -> Any:
    structured = getattr(result, "structuredContent", None)
    if structured:
        return structured.get("result", structured)
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        if text is not None:
            try:
                return json.loads(text)
            except (ValueError, TypeError):
                return text
    return None


async def _streamable_http_call(url: str, tool: str, args: dict) -> Any:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool, args)
            return _parse_tool_result(result)


# ── GitHub (real via PyGithub, or dry-run) ──────────────────────
_DRYRUN_DIR = Path("dryrun_prs")


async def _github_call(tool: str, args: dict) -> Any:
    import asyncio

    if not settings.github_token:
        return _github_dryrun(tool, args)
    return await asyncio.to_thread(_github_real, tool, args)


def _github_dryrun(tool: str, args: dict) -> dict:
    if tool == "get_file_contents":
        # Read from the local target checkout.
        path = Path(settings.target_repo_dir) / args["path"]
        return {"path": args["path"], "content": path.read_text()}
    _DRYRUN_DIR.mkdir(exist_ok=True)
    if tool == "create_pull_request":
        branch = args.get("branch", "prodrescue-fix")
        path = _DRYRUN_DIR / f"{branch.replace('/', '_')}.md"
        path.write_text(
            f"# {args.get('title', 'ProdRescue PR')}\n\n"
            f"branch: {branch}\nbase: {args.get('base', 'main')}\n\n"
            f"{args.get('body', '')}\n\n"
            f"---\n\n```diff\n{args.get('patch_diff', '')}\n```\n"
        )
        return {"html_url": f"(dry-run) {path}", "dry_run": True}
    return {"ok": True, "dry_run": True, "tool": tool}


def _github_real(tool: str, args: dict) -> dict:
    """Real GitHub mutations via the Git data API (no local clone required)."""
    from github import Github, GithubException

    gh = Github(settings.github_token)
    repo = gh.get_repo(settings.repo_full_name)

    if tool == "get_file_contents":
        content = repo.get_contents(args["path"], ref=args.get("ref") or repo.default_branch)
        return {"path": args["path"], "content": content.decoded_content.decode()}

    if tool == "create_branch":
        base = args.get("base") or repo.default_branch
        base_ref = repo.get_branch(base)
        ref = f"refs/heads/{args['name']}"
        try:
            repo.create_git_ref(ref=ref, sha=base_ref.commit.sha)
        except GithubException:
            pass  # branch already exists — reuse it
        return {"branch": args["name"], "base": base}

    if tool == "put_file":
        # Create/update a single file's full contents on a branch.
        branch = args["branch"]
        path = args["path"]
        message = args.get("message", "ProdRescue patch")
        try:
            existing = repo.get_contents(path, ref=branch)
            repo.update_file(path, message, args["content"], existing.sha, branch=branch)
        except GithubException:
            repo.create_file(path, message, args["content"], branch=branch)
        return {"path": path, "branch": branch}

    if tool == "create_pull_request":
        pr = repo.create_pull(
            title=args["title"],
            body=args.get("body", ""),
            head=args["branch"],
            base=args.get("base") or repo.default_branch,
        )
        return {"html_url": pr.html_url, "number": pr.number, "dry_run": False}

    raise ValueError(f"unknown github tool: {tool}")
