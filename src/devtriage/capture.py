"""Core capture, snapshot, and issue logic for devtriage."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple, Union

from . import __version__

ROOT = Path.cwd()
SENSITIVE_KEYS = ("KEY", "SECRET", "TOKEN", "PASSWORD")


def run_cmd(
    cmd: Union[str, Sequence[str]],
    cwd: Path | None = None,
    capture_output: bool = True,
    env: Dict[str, str] | None = None,
) -> Tuple[int, str, str]:
    """Run a shell command and return (code, stdout, stderr)."""
    shell = not isinstance(cmd, (list, tuple))
    result = subprocess.run(
        cmd,
        shell=shell,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=True,
    )
    stdout = result.stdout if result.stdout is not None else ""
    stderr = result.stderr if result.stderr is not None else ""
    return result.returncode, stdout, stderr


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_outdir() -> str:
    return f"./.devtriage/{timestamp()}"


def sanitize_value(value: Any) -> Any:
    if isinstance(value, str):
        upper = value.upper()
        if any(token in upper for token in SENSITIVE_KEYS):
            return "***REDACTED***"
        return value
    if isinstance(value, dict):
        return {k: sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(v) for v in value]
    return value


def sanitize_env(env: Dict[str, str]) -> Dict[str, str]:
    sanitized = {}
    for key, val in env.items():
        if any(token in key.upper() for token in SENSITIVE_KEYS):
            sanitized[key] = "***REDACTED***"
        else:
            sanitized[key] = sanitize_value(val)
    return sanitized


def gather_env_info() -> Dict[str, Any]:
    info: Dict[str, Any] = {
        "timestamp_utc": timestamp(),
        "cwd": str(Path.cwd()),
        "platform": sys.platform,
        "machine": os.uname().machine if hasattr(os, "uname") else None,
        "python_version": sys.version,
        "executable": sys.executable,
        "version": __version__,
        "git": None,
        "env": sanitize_env(dict(os.environ)),
    }
    # git status (if inside git)
    try:
        ret, out, _ = run_cmd(["git", "rev-parse", "--is-inside-work-tree"])
        if ret == 0 and out.strip() == "true":
            _, branch, _ = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
            _, rev, _ = run_cmd(["git", "rev-parse", "HEAD"])
            _, status, _ = run_cmd(["git", "status", "--porcelain"])
            _, diff, _ = run_cmd(["git", "diff", "--name-only", "HEAD"])
            info["git"] = {
                "branch": branch.strip(),
                "rev": rev.strip(),
                "status_porcelain": status.strip(),
                "changed_files": diff.strip().splitlines(),
            }
    except Exception:
        info["git"] = None
    # pip freeze
    try:
        ret, out, _ = run_cmd([sys.executable, "-m", "pip", "freeze"])
        if ret == 0:
            info["pip_freeze"] = sanitize_value(out.strip().splitlines())
    except Exception:
        info["pip_freeze"] = []
    return info


def ensure_outdir(outdir: str) -> Path:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    return out.resolve()


def cmd_run(cmd: Union[str, Sequence[str]], out: str) -> int:
    outdir = ensure_outdir(out)
    display_cmd = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
    meta = {"command": display_cmd, "started_at": timestamp()}
    (outdir / "devtriage_meta.json").write_text(json.dumps(meta))
    print(f"Running: {display_cmd}")
    code, stdout, stderr = run_cmd(cmd)
    meta["exit_code"] = code
    meta["finished_at"] = timestamp()
    (outdir / "stdout.txt").write_text(stdout)
    (outdir / "stderr.txt").write_text(stderr)
    (outdir / "meta.json").write_text(json.dumps(meta, indent=2))
    print(f"Done. exit={code}. Saved to {outdir}")
    return code


def make_issue_markdown(title: str, summary: Dict[str, Any], snapshot_zip: str, env_info: Dict[str, Any]) -> str:
    lines = [
        f"# {title}\n",
        "## Summary\n",
    ]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "\n## Reproduction steps\n",
            "1. Clone repo and `cd` into it\n",
            "2. Run the failing command (example):\n",
            "```bash",
            summary.get("command", "(command not recorded)"),
            "```\n",
            "## Environment\n",
            f"- OS: {env_info.get('platform')}",
            f"- Python: {env_info.get('python_version')}",
        ]
    )
    git_info = env_info.get("git")
    if git_info:
        lines.append(f"- Git branch: {git_info.get('branch')}")
        lines.append(f"- Git rev: {git_info.get('rev')}")
    lines.extend(
        [
            "\n## Attachments\n",
            f"- Snapshot zip: `{snapshot_zip}`\n",
            "## Notes\n- Minimal reproduction packaged. Please open if further info required.\n",
        ]
    )
    return "\n".join(lines)


def create_zip(outdir: Path) -> str:
    zip_path = outdir / f"devtriage_snapshot_{timestamp()}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in outdir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(outdir))
    return str(zip_path)


def cmd_snapshot(cmd: str | None, out: str) -> str:
    outdir = ensure_outdir(out)
    print("Capturing environment info...")
    info = gather_env_info()
    (outdir / "env.json").write_text(json.dumps(info, indent=2))
    if cmd:
        print("Running command to capture logs...")
        cmd_run(cmd, out)
    zip_path = create_zip(outdir)
    print(f"Snapshot written: {zip_path}")
    return zip_path


def open_issue_with_gh(title: str, issue_path: Path, repo: str | None) -> None:
    command: List[str] = ["gh", "issue", "create", "--title", title, "--body-file", str(issue_path)]
    if repo:
        command += ["--repo", repo]
    code, _, stderr = run_cmd(command)
    if code != 0:
        print("Failed to open GitHub issue via gh CLI:")
        print(stderr)


def cmd_issue(cmd: str, out: str, title: str | None, gh: bool = False, gh_repo: str | None = None) -> str:
    outdir = ensure_outdir(out)
    snapshot = cmd_snapshot(cmd, out)
    meta_path = outdir / "meta.json"
    try:
        meta = json.loads(meta_path.read_text())
    except Exception:
        meta = {"command": cmd}
    try:
        env = json.loads((outdir / "env.json").read_text())
    except Exception:
        env = gather_env_info()
    issue_title = title or "Bug report: failing command"
    summary = {"command": cmd, "exit_code": meta.get("exit_code")}
    issue_markdown = make_issue_markdown(issue_title, summary, snapshot, env)
    issue_path = outdir / "ISSUE.md"
    issue_path.write_text(issue_markdown)
    print(f"Issue template written to {issue_path}")
    if gh:
        open_issue_with_gh(issue_title, issue_path, gh_repo)
    return str(issue_path)



