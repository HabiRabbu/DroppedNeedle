#!/usr/bin/env python3
"""AI-powered pull request review using DeepSeek (or any OpenAI-compatible API).

Security: this script runs under pull_request_target in the base-repository
context.  It fetches PR diffs exclusively through the GitHub REST API - the
PR code is never checked out, cloned, or executed.  Secrets are injected via
environment variables and never interpolated into shell commands.
"""

from __future__ import annotations

import asyncio, json, logging, os, re, shlex, textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from openai import OpenAI

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _load_env_file(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False

    for raw_line in path.read_text(errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            continue

        value = raw_value.strip()
        try:
            parsed = shlex.split(value, comments=False, posix=True)
            if parsed:
                value = parsed[0]
        except ValueError:
            value = value.strip("\"'")

        if value:
            os.environ.setdefault(key, value)

    return True


def _candidate_hermes_paths(file_env: str, default_name: str) -> list[Path]:
    paths: list[Path] = []
    explicit = os.getenv(file_env)
    if explicit:
        paths.append(Path(explicit).expanduser())

    hermes_home = Path(os.getenv("HERMES_HOME") or "~/.hermes").expanduser()
    paths.append(hermes_home / default_name)
    paths.append(Path.home() / ".hermes" / default_name)

    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(path)
    return deduped


def _load_hermes_env() -> None:
    if not _env_bool("AI_REVIEW_LOAD_HERMES_ENV", default=True):
        return
    for path in _candidate_hermes_paths("HERMES_ENV_FILE", ".env"):
        if _load_env_file(path):
            return


def _load_hermes_config_defaults() -> None:
    if not _env_bool("AI_REVIEW_LOAD_HERMES_ENV", default=True):
        return

    for path in _candidate_hermes_paths("HERMES_CONFIG_FILE", "config.yaml"):
        if not path.exists() or not path.is_file():
            continue
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(path.read_text()) or {}
        except Exception:
            return

        providers = data.get("providers") or {}
        if not isinstance(providers, dict):
            return

        _set_provider_api_default(
            providers,
            ("ai-router", "local-ai", "local_ai"),
            ("AI_ROUTER_BASE_URL", "LOCAL_AI_BASE_URL"),
        )
        _set_provider_api_default(
            providers,
            ("opencode-zen", "opencode", "opencode_zen", "zen"),
            ("OPENCODE_BASE_URL", "OPENCODE_ZEN_BASE_URL"),
        )
        _set_provider_api_default(
            providers,
            ("opencode-go", "opencode_go", "go", "opencode-go-sub"),
            ("OPENCODE_GO_BASE_URL",),
        )
        _set_provider_api_default(
            providers,
            ("nous", "nous-portal", "nousresearch"),
            ("NOUS_BASE_URL", "NOUS_INFERENCE_BASE_URL"),
        )
        return


def _set_provider_api_default(
    providers: dict[str, Any],
    aliases: tuple[str, ...],
    env_names: tuple[str, ...],
) -> None:
    alias_set = {alias.lower() for alias in aliases}
    for name, provider in providers.items():
        if str(name).lower() not in alias_set or not isinstance(provider, dict):
            continue
        api = provider.get("api") or provider.get("base_url") or provider.get("url")
        if not isinstance(api, str) or not api.strip():
            return
        for env_name in env_names:
            os.environ.setdefault(env_name, api.strip())
        return


def _local_ai_base_url() -> str:
    raw = (
        os.getenv("LOCAL_AI_BASE_URL")
        or os.getenv("AI_ROUTER_BASE_URL")
        or ""
    ).strip().rstrip("/")
    if not raw:
        return ""
    if re.search(r"/v\d+$", raw):
        return raw
    return f"{raw}/v1"


_load_hermes_env()
_load_hermes_config_defaults()

AI_REVIEW_PROVIDER_ORDER = os.getenv(
    "AI_REVIEW_PROVIDER_ORDER",
    "local-ai,nous,opencode,opencode-go,deepseek,openrouter,openai",
)
AI_REVIEW_FALLBACK_ROUTE = os.getenv(
    "AI_REVIEW_FALLBACK_ROUTE",
    "Route this PR to another configured reviewer lane, then rerun `/ai-review`.",
)

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_REASONING_EFFORT = os.getenv("DEEPSEEK_REASONING_EFFORT", "max")

LOCAL_AI_BASE_URL = _local_ai_base_url()
LOCAL_AI_MODEL = (
    os.getenv("LOCAL_AI_MODEL")
    or os.getenv("AI_ROUTER_MODEL")
    or "qwen3.6-27b"
)

NOUS_BASE_URL = (
    os.getenv("NOUS_INFERENCE_BASE_URL")
    or os.getenv("NOUS_BASE_URL")
    or "https://inference.nousresearch.com/v1"
)
NOUS_MODEL = (
    os.getenv("NOUS_MODEL")
    or os.getenv("NOUS_PORTAL_MODEL")
    or "hermes-3-70b"
)

OPENCODE_BASE_URL = (
    os.getenv("OPENCODE_BASE_URL")
    or os.getenv("OPENCODE_ZEN_BASE_URL")
    or "https://opencode.ai/zen/v1"
)
OPENCODE_MODEL = (
    os.getenv("OPENCODE_MODEL")
    or os.getenv("OPENCODE_ZEN_MODEL")
    or "gemini-3-flash"
)
OPENCODE_GO_BASE_URL = os.getenv(
    "OPENCODE_GO_BASE_URL",
    "https://opencode.ai/zen/go/v1",
)
OPENCODE_GO_MODEL = os.getenv("OPENCODE_GO_MODEL", "glm-5")

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-5-mini")

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
REVIEWER_NAME = "musicseerr-ai-reviewer[bot]"

GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_API = "https://api.github.com"

GITHUB_EVENT_PATH = os.environ.get("GITHUB_EVENT_PATH", "")
GUIDELINES_PATH = os.environ.get("GUIDELINES_PATH", ".github/review_guidelines.md")

# Max context window: leave headroom for response (1M - 100K safety)
MAX_INPUT_TOKENS = 900_000

log = logging.getLogger("ai_review")


@dataclass(frozen=True)
class ReviewProvider:
    name: str
    api_key_envs: tuple[str, ...]
    base_url: str
    model: str
    requires_api_key: bool = True
    requires_base_url: bool = False
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] | None = None
    default_headers: dict[str, str] | None = None


@dataclass(frozen=True)
class LLMReview:
    provider: ReviewProvider
    data: dict[str, Any]


class NoReviewProviderError(RuntimeError):
    def __init__(self, skipped: list[str], failures: list[str]) -> None:
        self.skipped = skipped
        self.failures = failures
        super().__init__(str(self))

    def __str__(self) -> str:
        parts: list[str] = []
        if self.skipped:
            parts.append("skipped " + "; ".join(self.skipped))
        if self.failures:
            parts.append("failed " + "; ".join(self.failures))
        return "; ".join(parts) or "no review providers were configured"

# ---------------------------------------------------------------------------
# Helpers: GitHub REST API
# ---------------------------------------------------------------------------

def _gh_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": REVIEWER_NAME,
    }


def _gh_diff_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": REVIEWER_NAME,
    }


async def gh_get(url: str, **kwargs: Any) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_gh_headers(), **kwargs)
        resp.raise_for_status()
        return resp


async def gh_get_diff(url: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url, headers=_gh_diff_headers())
        resp.raise_for_status()
        return resp.text


async def gh_post(url: str, body: dict[str, Any]) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=_gh_headers(), json=body)
        resp.raise_for_status()
        return resp


# ---------------------------------------------------------------------------
# Event helpers
# ---------------------------------------------------------------------------

def _load_event() -> dict[str, Any]:
    with open(GITHUB_EVENT_PATH) as fh:
        return json.load(fh)


def _find_pr_number(event: dict[str, Any]) -> int | None:
    if "pull_request" in event and event["pull_request"] is not None:
        return event["pull_request"]["number"]
    if "issue" in event and event.get("issue", {}).get("pull_request"):
        return event["issue"]["number"]
    return None


def _comment_body(event: dict[str, Any]) -> str:
    return (event.get("comment") or {}).get("body", "")


def _extract_review_mode(comment: str) -> str:
    """Parse manual review mode from a /ai-review comment."""
    text = comment.strip()
    if re.search(r"/ai-review\s+security", text, re.IGNORECASE):
        return "security"
    if re.search(r"/ai-review\s+performance", text, re.IGNORECASE):
        return "performance"
    if re.search(r"/ai-review\s+architecture", text, re.IGNORECASE):
        return "architecture"
    return "full"


# ---------------------------------------------------------------------------
# Guidelines
# ---------------------------------------------------------------------------

def load_guidelines() -> str:
    path = Path(GUIDELINES_PATH)
    if not path.exists():
        log.warning("Guidelines file not found at %s, using built-in defaults", GUIDELINES_PATH)
        return _builtin_guidelines()
    return path.read_text()


def _builtin_guidelines() -> str:
    return textwrap.dedent("""\
    Review this code for:
    - Security vulnerabilities (injection, exposed secrets, unsafe input handling)
    - Architectural issues (layer violations, tight coupling, missing abstractions)
    - Error handling gaps (missing timeouts, swallowed exceptions, unhandled edge cases)
    - Type safety problems
    - Performance issues (N+1 queries, missing caching, blocking I/O)
    - Missing tests for new logic

    Do not comment on formatting, style, or import ordering.
    Categorise findings as must_fix, should_fix, or suggestion.
    """)


# ---------------------------------------------------------------------------
# Diff fetching
# ---------------------------------------------------------------------------

async def fetch_pr_diff(pr_number: int) -> str:
    url = f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}/pulls/{pr_number}"
    return await gh_get_diff(url)


async def get_pr_info(pr_number: int) -> dict[str, Any]:
    url = f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}/pulls/{pr_number}"
    resp = await gh_get(url)
    data = resp.json()
    return {
        "title": data.get("title", ""),
        "body": data.get("body") or "",
        "author": data.get("user", {}).get("login", "unknown"),
        "head_label": data.get("head", {}).get("label", ""),
        "base_sha": data.get("base", {}).get("sha", ""),
        "head_sha": data.get("head", {}).get("sha", ""),
        "files_url": data.get("_links", {}).get("self", {}).get("href", ""),
    }


async def get_pr_files(pr_number: int) -> list[str]:
    url = f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}/pulls/{pr_number}/files"
    resp = await gh_get(url, params={"per_page": 100})
    files: list[str] = []
    for item in resp.json():
        files.append(item.get("filename", ""))
    return files


async def get_last_reviewed_commit(pr_number: int) -> str | None:
    """Find the most recent bot review on this PR and return its commit SHA."""
    url = f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}/pulls/{pr_number}/reviews"
    resp = await gh_get(url, params={"per_page": 100})
    for review in reversed(resp.json()):
        if review.get("user", {}).get("login") == "github-actions[bot]":
            return review.get("commit_id")
    return None


async def get_incremental_files(
    last_commit: str, head_sha: str
) -> list[str]:
    """Return files changed between last_commit and head_sha."""
    url = (
        f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}/compare"
        f"/{last_commit}...{head_sha}"
    )
    resp = await gh_get(url)
    data = resp.json()
    return [f["filename"] for f in (data.get("files") or [])]


def filter_diff_by_files(diff_text: str, file_list: list[str]) -> str:
    """Keep only diff hunks for the given files, preserving order."""
    if not diff_text or not file_list:
        return diff_text
    file_set = set(file_list)
    parts = diff_text.split("diff --git ")
    kept: list[str] = []
    for part in parts:
        if not part.strip():
            continue
        m = re.match(r"a/(.+?)\s+b/(.+)", part)
        if m and (m.group(1) in file_set or m.group(2) in file_set):
            kept.append("diff --git " + part)
    return "".join(kept)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------

def build_system_prompt(guidelines: str, mode: str) -> str:
    base = textwrap.dedent(f"""\
    You are an AI code reviewer for the **Musicseerr** project, a self-hosted music
    request and discovery web application built with FastAPI (Python backend) and
    SvelteKit (TypeScript frontend).

    Review mode: **{mode}**.

    Follow these review guidelines when evaluating the pull request:
    """)

    if mode == "security":
        focus = textwrap.dedent("""\
        Focus on security: authentication, authorisation, secrets handling,
        injection risks, token leakage, crypto usage, input validation,
        and CORS/middleware changes.
        """)
        return f"{base}\n\n{focus}\n\n{guidelines}"

    if mode == "performance":
        focus = textwrap.dedent("""\
        Focus on performance: N+1 queries, missing caching, blocking I/O in async
        code, large list rendering without virtualisation, and inefficient data
        fetching patterns.
        """)
        return f"{base}\n\n{focus}\n\n{guidelines}"

    if mode == "architecture":
        focus = textwrap.dedent("""\
        Focus on architecture: layer violations (routes doing business logic,
        services doing I/O), serialization (msgspec only), dependency injection
        patterns, and code organisation.
        """)
        return f"{base}\n\n{focus}\n\n{guidelines}"

    return f"{base}\n\n{guidelines}"


def build_user_prompt(
    pr_info: dict[str, Any],
    files: list[str],
    diff: str,
    incremental: bool = False,
) -> str:
    file_list = "\n".join(f"  - {f}" for f in files[:100])
    truncation = (
        f"\n  ... and {len(files) - 100} more files" if len(files) > 100 else ""
    )

    incremental_note = ""
    if incremental:
        incremental_note = textwrap.dedent("""\

        This is an **incremental review**. Only review the files listed above.
        Files that were previously reviewed but have not changed in these new
        commits should be ignored entirely. Do not re-review them.
        """)

    return textwrap.dedent(f"""\
    ## Pull Request

    **Title:** {pr_info['title']}
    **Author:** {pr_info['author']}
    **Branch:** {pr_info['head_label']}

    **Description:**
    {pr_info['body'] or '(no description provided)'}

    **Changed files ({len(files)}):**
    {file_list}{truncation}{incremental_note}

    ## Diff
    ```diff
    {diff}
    ```

    ## Instructions

    Produce a structured review in **valid JSON** matching this schema:

    ```json
    {{
      "summary": "string (concise summary of what changed and why)",
      "findings": [
        {{
          "severity": "must_fix | should_fix | suggestion",
          "file": "string (relative path, or null for PR-level findings)",
          "line": "number | null (the new-side line number the comment applies to)",
          "title": "string (short, one-line description)",
          "body": "string (detailed explanation with reasoning and suggested fix)"
        }}
      ],
      "conclusion": "REQUEST_CHANGES | COMMENT"
    }}
    ```

    Rules:
    - Set `line` to `null` for findings that are about the overall PR or a whole file
      rather than a specific changed line.
    - If any finding has severity `must_fix`, conclusion must be `REQUEST_CHANGES`.
    - If there are no findings at all, set `findings` to `[]` and conclusion to
      `COMMENT`.
    - Attach inline comments ONLY to lines that actually changed in the diff.
    - Be specific and actionable. Include the reasoning behind each finding.
    - Do NOT comment on formatting, whitespace, or import ordering.
    - Do not give generic positive feedback.
    - Review only the changed lines in the diff. Do not nitpick unchanged code.
    """)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 characters per token."""
    return len(text) // 4


# ---------------------------------------------------------------------------
# OpenAI-compatible provider routing
# ---------------------------------------------------------------------------

def _review_providers() -> list[ReviewProvider]:
    local_ai = ReviewProvider(
        name="local-ai",
        api_key_envs=("LOCAL_AI_API_KEY", "AI_ROUTER_API_KEY"),
        base_url=LOCAL_AI_BASE_URL,
        model=LOCAL_AI_MODEL,
        requires_api_key=False,
        requires_base_url=True,
    )
    nous = ReviewProvider(
        name="nous",
        api_key_envs=("NOUS_API_KEY", "NOUS_PORTAL_API_KEY"),
        base_url=NOUS_BASE_URL,
        model=NOUS_MODEL,
    )
    opencode = ReviewProvider(
        name="opencode",
        api_key_envs=("OPENCODE_API_KEY", "OPENCODE_ZEN_API_KEY"),
        base_url=OPENCODE_BASE_URL,
        model=OPENCODE_MODEL,
    )
    opencode_go = ReviewProvider(
        name="opencode-go",
        api_key_envs=("OPENCODE_GO_API_KEY",),
        base_url=OPENCODE_GO_BASE_URL,
        model=OPENCODE_GO_MODEL,
    )
    providers = {
        "local-ai": local_ai,
        "local_ai": local_ai,
        "ai-router": local_ai,
        "ai_router": local_ai,
        "nous": nous,
        "nous-portal": nous,
        "nous_portal": nous,
        "nousresearch": nous,
        "nous-research": nous,
        "opencode": opencode,
        "opencode-zen": opencode,
        "opencode_zen": opencode,
        "zen": opencode,
        "opencode-go": opencode_go,
        "opencode_go": opencode_go,
        "opencode-go-sub": opencode_go,
        "go": opencode_go,
        "deepseek": ReviewProvider(
            name="deepseek",
            api_key_envs=("DEEPSEEK_API_KEY",),
            base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL,
            reasoning_effort=DEEPSEEK_REASONING_EFFORT,
            extra_body={"thinking": {"type": "enabled"}},
        ),
        "openrouter": ReviewProvider(
            name="openrouter",
            api_key_envs=("OPENROUTER_API_KEY",),
            base_url=OPENROUTER_BASE_URL,
            model=OPENROUTER_MODEL,
            default_headers={
                "HTTP-Referer": os.getenv(
                    "OPENROUTER_HTTP_REFERER",
                    f"https://github.com/{GITHUB_REPOSITORY}",
                ),
                "X-Title": os.getenv("OPENROUTER_X_TITLE", "MusicSeerr AI Review"),
            },
        ),
        "openai": ReviewProvider(
            name="openai",
            api_key_envs=("OPENAI_API_KEY",),
            base_url=OPENAI_BASE_URL,
            model=OPENAI_MODEL,
        ),
    }

    ordered: list[ReviewProvider] = []
    for raw_name in AI_REVIEW_PROVIDER_ORDER.split(","):
        name = raw_name.strip().lower()
        if not name:
            continue
        provider = providers.get(name)
        if provider is None:
            log.warning("Unknown AI review provider in order: %s", name)
            continue
        ordered.append(provider)
    return ordered


async def call_llm(system: str, user: str) -> LLMReview:
    skipped: list[str] = []
    failures: list[str] = []

    for provider in _review_providers():
        if provider.requires_base_url and not provider.base_url:
            skipped.append(f"{provider.name} (base URL is not configured)")
            continue

        api_key = _provider_api_key(provider)
        if not api_key and provider.requires_api_key:
            envs = " or ".join(provider.api_key_envs)
            skipped.append(f"{provider.name} ({envs} is not set)")
            continue

        if not provider.model:
            skipped.append(f"{provider.name} (model is not configured)")
            continue

        try:
            data = await _call_provider(provider, api_key or "not-needed", system, user)
            return LLMReview(provider=provider, data=data)
        except Exception as exc:
            log.exception("AI review provider failed: %s", provider.name)
            failures.append(f"{provider.name}: {exc}")

    raise NoReviewProviderError(skipped, failures)


def _provider_api_key(provider: ReviewProvider) -> str:
    for env_name in provider.api_key_envs:
        value = os.environ.get(env_name, "")
        if value:
            return value
    return ""


async def _call_provider(
    provider: ReviewProvider,
    api_key: str,
    system: str,
    user: str,
) -> dict[str, Any]:
    client_args: dict[str, Any] = {
        "api_key": api_key,
        "timeout": httpx.Timeout(120.0, connect=10.0),
    }
    if provider.base_url:
        client_args["base_url"] = provider.base_url
    if provider.default_headers:
        client_args["default_headers"] = provider.default_headers

    client = OpenAI(**client_args)

    total_tokens = _estimate_tokens(system) + _estimate_tokens(user)
    log.info(
        "Sending prompt (~%d estimated tokens) to %s/%s",
        total_tokens,
        provider.name,
        provider.model,
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    request: dict[str, Any] = {
        "model": provider.model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if provider.reasoning_effort:
        request["reasoning_effort"] = provider.reasoning_effort
    if provider.extra_body:
        request["extra_body"] = provider.extra_body

    response = client.chat.completions.create(**request)

    usage = response.usage
    if usage:
        log.info(
            "Tokens: prompt=%d completion=%d total=%d",
            usage.prompt_tokens,
            usage.completion_tokens,
            usage.total_tokens,
        )

    content = response.choices[0].message.content or "{}"
    return json.loads(content)


# ---------------------------------------------------------------------------
# Review posting
# ---------------------------------------------------------------------------

async def post_review(
    pr_number: int,
    commit_id: str,
    summary: str,
    findings: list[dict[str, Any]],
    conclusion: str,
    provider_name: str,
) -> None:
    url = f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}/pulls/{pr_number}/reviews"

    inline_comments: list[dict[str, Any]] = []
    for f in findings:
        if f.get("line") is None or f.get("file") is None:
            continue
        inline_comments.append({
            "path": f["file"],
            "line": f["line"],
            "side": "RIGHT",
            "body": f"**{f['title']}** ({f['severity']})\n\n{f['body']}",
        })

    findings_summary = _format_findings_for_body(findings)

    body = (
        f"{summary}\n\n"
        f"{findings_summary}\n\n"
        f"---\n"
        f"*Automated review by MusicSeerr AI Reviewer via `{provider_name}`. "
        f"See `.github/review_guidelines.md` for review criteria.*"
    )

    payload: dict[str, Any] = {
        "commit_id": commit_id,
        "body": body,
        "event": conclusion,
        "comments": inline_comments,
    }

    log.info(
        "Posting review: %d inline comments, event=%s",
        len(inline_comments),
        conclusion,
    )
    await gh_post(url, payload)


def _format_findings_for_body(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return ""

    must_fix = [f for f in findings if f["severity"] == "must_fix"]
    should_fix = [f for f in findings if f["severity"] == "should_fix"]
    suggestions = [f for f in findings if f["severity"] == "suggestion"]

    parts: list[str] = []

    if must_fix:
        parts.append("## Must Fix")
        for f in must_fix:
            location = f" (`{f['file']}` line {f['line']})" if f.get("line") else ""
            parts.append(f"- **{f['title']}**{location}\n  {f['body']}")

    if should_fix:
        parts.append("## Should Fix")
        for f in should_fix:
            location = f" (`{f['file']}` line {f['line']})" if f.get("line") else ""
            parts.append(f"- **{f['title']}**{location}\n  {f['body']}")

    if suggestions:
        parts.append("## Suggestions")
        for f in suggestions:
            location = f" (`{f['file']}` line {f['line']})" if f.get("line") else ""
            parts.append(f"- **{f['title']}**{location}\n  {f['body']}")

    return "\n\n".join(parts)


async def post_failure_comment(pr_number: int, reason: str) -> None:
    """Post a comment when the AI review itself fails."""
    url = (
        f"{GITHUB_API}/repos/{GITHUB_REPOSITORY}/issues/{pr_number}/comments"
    )
    body = (
        f"AI review could not be routed to an available provider.\n\n"
        f"Reason: {reason}\n\n"
        f"Next route:\n"
        f"- Configure the local/Hermes route with `HERMES_HOME`, "
        f"`HERMES_ENV_FILE`, `LOCAL_AI_BASE_URL`, or `AI_ROUTER_BASE_URL`; "
        f"or configure one fallback provider credential "
        f"(`NOUS_API_KEY`, `OPENCODE_ZEN_API_KEY`, `OPENCODE_GO_API_KEY`, "
        f"`DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`, or `OPENAI_API_KEY`).\n"
        f"- Then rerun `/ai-review`.\n"
        f"- {AI_REVIEW_FALLBACK_ROUTE}\n\n"
        f"<!-- ai-review:route-needed -->"
    )
    await gh_post(url, {"body": body})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_response(data: dict[str, Any]) -> None:
    valid_severities = {"must_fix", "should_fix", "suggestion"}
    valid_conclusions = {"REQUEST_CHANGES", "COMMENT"}

    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("Response missing valid 'summary' field")

    conclusion = data.get("conclusion", "COMMENT")
    if conclusion not in valid_conclusions:
        raise ValueError(f"Invalid conclusion: {conclusion}")

    findings = data.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("'findings' must be a list")

    has_must_fix = False
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            raise ValueError(f"Finding {i} is not an object")
        sev = f.get("severity", "")
        if sev not in valid_severities:
            raise ValueError(f"Finding {i} has invalid severity: {sev}")
        if sev == "must_fix":
            has_must_fix = True
        if f.get("file") and not isinstance(f["file"], str):
            raise ValueError(f"Finding {i} 'file' must be a string or null")
        if f.get("line") is not None:
            if not isinstance(f["line"], int):
                raise ValueError(
                    f"Finding {i} 'line' must be an integer or null"
                )

    if has_must_fix and conclusion != "REQUEST_CHANGES":
        raise ValueError(
            "Must Fix items present but conclusion is not REQUEST_CHANGES"
        )


# ---------------------------------------------------------------------------
# Orquestration
# ---------------------------------------------------------------------------

async def run() -> None:
    event = _load_event()

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_action = os.environ.get("GITHUB_EVENT_ACTION", "")
    mode_from_env = os.environ.get("REVIEW_MODE", "full")

    pr_number = _find_pr_number(event)
    if pr_number is None:
        log.error("Could not determine PR number from event payload")
        return

    comment = _comment_body(event)
    if event_name == "issue_comment" and comment:
        mode_from_env = _extract_review_mode(comment)
    if event_name == "pull_request_target" and event_action == "labeled":
        label_name = (event.get("label") or {}).get("name", "")
        mode_from_env = _extract_review_mode(f"/ai-review {label_name}")

    log.info(
        "Review mode: %s   PR: #%d   event: %s/%s",
        mode_from_env,
        pr_number,
        event_name,
        event_action,
    )

    guidelines = load_guidelines()
    pr_info = await get_pr_info(pr_number)
    commit_id = pr_info["head_sha"]

    # --- incremental review on synchronize ---
    is_incremental = False
    if event_name == "pull_request_target" and event_action == "synchronize":
        last_commit = await get_last_reviewed_commit(pr_number)
        if last_commit:
            inc_files = await get_incremental_files(
                last_commit, commit_id
            )
            if inc_files:
                is_incremental = True
                log.info(
                    "Incremental: %d files changed since last review at %s",
                    len(inc_files),
                    last_commit[:8],
                )

    diff = await fetch_pr_diff(pr_number)
    files = await get_pr_files(pr_number)

    if is_incremental:
        inc_set = set(inc_files)
        diff = filter_diff_by_files(diff, inc_files)
        files = [f for f in files if f in inc_set]

    diff_tokens = _estimate_tokens(diff)
    if diff_tokens > MAX_INPUT_TOKENS:
        log.warning(
            "Diff too large (%d estimated tokens), reviewing first %d tokens",
            diff_tokens,
            MAX_INPUT_TOKENS,
        )
        diff = diff[: MAX_INPUT_TOKENS * 4]

    system = build_system_prompt(guidelines, mode_from_env)
    user = build_user_prompt(pr_info, files, diff, incremental=is_incremental)

    try:
        review = await call_llm(system, user)
        result = review.data
    except Exception as exc:
        log.exception("AI review provider routing failed")
        await post_failure_comment(pr_number, str(exc))
        return

    try:
        validate_response(result)
    except ValueError as exc:
        log.warning("Response validation failed: %s  retrying once...", exc)
        retry_user = user + f"\n\nYour previous response was invalid: {exc}\nPlease fix and return valid JSON."
        try:
            review = await call_llm(system, retry_user)
            result = review.data
            validate_response(result)
        except Exception as exc2:
            log.exception("Retry also failed")
            await post_failure_comment(
                pr_number,
                f"AI review produced an invalid response and the retry also failed: {exc2}",
            )
            return

    summary = result["summary"]
    findings = result["findings"]
    conclusion = result["conclusion"]

    await post_review(
        pr_number,
        commit_id,
        summary,
        findings,
        conclusion,
        review.provider.name,
    )
    log.info(
        "Review posted successfully via %s: %d findings, conclusion=%s",
        review.provider.name,
        len(findings),
        conclusion,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("DEBUG") else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    if not GITHUB_EVENT_PATH:
        log.error("GITHUB_EVENT_PATH is not set, cannot determine event context")
        return
    asyncio.run(run())


if __name__ == "__main__":
    main()
