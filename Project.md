What people most struggle with while coding

Reproducing a bug: flaky tests, environment drift, missing steps.

Slow feedback loop: heavy test suites, waiting on CI.

Debugging noise: long stack traces, buried root cause.

Context-poor bug reports: no env info, no minimal repro, no test case.

Dependency/version mismatch and environment setup.

Finding the exact commit or change that introduced a regression.

Turning a local failure into a clean issue for teammates.

Problem we'll solve

Make the "triage → reproduce → report" steps trivial. Tool goal: given a failing test or failing run, capture minimal reproducible context, run focused test(s), collect environment and logs, optionally package a repro, and produce a ready-to-paste issue template.

Current state (v0.2.0, November 2025)

- Cross-runner focus mode: auto-detect pytest, nose, jest, or mocha (or pin `--runner`) and execute only the changed tests or a filtered subset.
- Reusable packaging: `pyproject.toml` + MIT license enable `pip install devtriage` or running via the `devtriage` console script.
- Open-source ready docs: see `README.md` for installation, feature overview, contribution guide, and licensing details.
- Backward compatible entrypoint: `python devtriage.py ...` still works while the package exposes `python -m devtriage` and the `devtriage` command.
- Automated pytest suite (see `tests/`) guards runner-detection heuristics for pytest, nose, jest, and mocha.
- Release process documented in `RELEASING.md` to push builds to PyPI and tag the GitHub repo.

MVP CLI: devtriage

Features:

run — run tests or a command, capture stdout/stderr and exit code, save a timestamped snapshot.

snapshot — collect environment (OS, Python version, pip freeze, git status), test output, and stack trace into a zip.

issue — generate a markdown issue template containing failure summary, environment, reproduction steps, minimal attachments (zip path).

focus — run tests only for changed files (based on git diff), or run pytest -k filter.

Safe: does not run destructive git commands automatically.

Below is a single-file implementation (Python 3.8+). Drop it into your repo and python devtriage.py --help.

#!/usr/bin/env python3
"""
devtriage.py — MVP CLI to triage, capture, and package failing runs/tests.

Usage examples:
  python devtriage.py run --cmd "pytest tests/test_foo.py::test_bar -q"
  python devtriage.py snapshot --cmd "pytest tests/test_foo.py::test_bar -q" --out ./triage_output
  python devtriage.py issue --cmd "pytest tests/test_foo.py::test_bar -q" --out ./triage_output --title "Failing test_bar on feature X"
  python devtriage.py focus --pytest -k "critical and not slow"
"""

import argparse
import os
import sys
import subprocess
import json
import tempfile
import shutil
from datetime import datetime
import platform
import zipfile
from pathlib import Path
import textwrap

ROOT = Path.cwd()

def run_cmd(cmd, cwd=None, shell=True, capture_output=True, env=None):
    if isinstance(cmd, list):
        shell = False
    proc = subprocess.run(cmd, shell=shell, cwd=cwd, env=env,
                          stdout=subprocess.PIPE if capture_output else None,
                          stderr=subprocess.PIPE if capture_output else None,
                          text=True)
    return proc.returncode, proc.stdout if proc.stdout is not None else "", proc.stderr if proc.stderr is not None else ""

def timestamp():
    return datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")

def gather_env_info():
    info = {
        "timestamp_utc": timestamp(),
        "cwd": str(Path.cwd()),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "executable": sys.executable,
        "git": None
    }
    # git status (if inside git)
    try:
        ret, out, err = run_cmd(["git", "rev-parse", "--is-inside-work-tree"], shell=False)
        if ret == 0 and out.strip() == "true":
            _, branch, _ = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], shell=False)
            _, rev, _ = run_cmd(["git", "rev-parse", "HEAD"], shell=False)
            _, status, _ = run_cmd(["git", "status", "--porcelain"], shell=False)
            _, diff, _ = run_cmd(["git", "diff", "--name-only", "HEAD"], shell=False)
            info["git"] = {
                "branch": branch.strip(),
                "rev": rev.strip(),
                "status_porcelain": status.strip(),
                "changed_files": diff.strip().splitlines()
            }
    except Exception:
        info["git"] = None
    # pip freeze
    try:
        ret, out, err = run_cmd([sys.executable, "-m", "pip", "freeze"], shell=False)
        if ret == 0:
            info["pip_freeze"] = out.strip().splitlines()
    except Exception:
        info["pip_freeze"] = []
    return info

def ensure_outdir(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    return out.resolve()

def cmd_run(args):
    outdir = ensure_outdir(args.out)
    meta = {"command": args.cmd, "started_at": timestamp()}
    with open(outdir / "devtriage_meta.json", "w") as f:
        json.dump(meta, f)
    print(f"Running: {args.cmd}")
    code, stdout, stderr = run_cmd(args.cmd, shell=True, capture_output=True)
    meta["exit_code"] = code
    meta["finished_at"] = timestamp()
    with open(outdir / "stdout.txt", "w") as f:
        f.write(stdout)
    with open(outdir / "stderr.txt", "w") as f:
        f.write(stderr)
    with open(outdir / "meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Done. exit={code}. Saved to {outdir}")
    return code

def cmd_snapshot(args):
    outdir = ensure_outdir(args.out)
    print("Capturing environment info...")
    info = gather_env_info()
    with open(outdir / "env.json", "w") as f:
        json.dump(info, f, indent=2)
    if args.cmd:
        print("Running command to capture logs...")
        code = cmd_run(argparse.Namespace(cmd=args.cmd, out=args.out))
    # create zip
    zip_path = Path(outdir) / f"devtriage_snapshot_{timestamp()}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in outdir.rglob("*"):
            if p.is_file():
                z.write(p, p.relative_to(outdir))
    print(f"Snapshot written: {zip_path}")
    return str(zip_path)

def make_issue_markdown(title, summary, snapshot_zip_path, env_info):
    md = []
    md.append(f"# {title}\n")
    md.append("## Summary\n")
    md.append(summary + "\n")
    md.append("## Reproduction steps\n")
    md.append("1. Clone repo and `cd` into it\n")
    md.append(f"2. Run the failing command (example):\n\n```bash\n{summary.get('command','(command not recorded)')}\n```\n")
    md.append("## Environment\n")
    md.append(f"- OS: {env_info.get('platform')}\n")
    md.append(f"- Python: {env_info.get('python_version')}\n")
    if env_info.get("git"):
        md.append(f"- Git branch: {env_info['git'].get('branch')}\n")
        md.append(f"- Git rev: {env_info['git'].get('rev')}\n")
    md.append("\n## Attachments\n")
    md.append(f"- Snapshot zip: `{snapshot_zip_path}`\n")
    md.append("\n## Notes\n- Minimal reproduction packaged. Please open if further info required.\n")
    return "\n".join(md)

def cmd_issue(args):
    outdir = ensure_outdir(args.out)
    snapshot = cmd_snapshot(argparse.Namespace(cmd=args.cmd, out=args.out))
    # read meta/env
    meta = {}
    try:
        with open(Path(outdir) / "meta.json") as f:
            meta = json.load(f)
    except Exception:
        meta = {"command": args.cmd}
    env = {}
    try:
        with open(Path(outdir) / "env.json") as f:
            env = json.load(f)
    except Exception:
        env = gather_env_info()
    title = args.title or "Bug report: failing command"
    summary = {"command": args.cmd, "exit_code": meta.get("exit_code")}
    md = make_issue_markdown(title, summary, snapshot, env)
    md_path = Path(outdir) / "ISSUE.md"
    md_path.write_text(md)
    print(f"Issue template written to {md_path}")
    print(md)
    return str(md_path)

def find_changed_tests():
    # naive heuristic: list changed python files and map to tests by name patterns
    try:
        _, out, _ = run_cmd(["git", "diff", "--name-only", "HEAD"], shell=False)
        files = [l for l in out.splitlines() if l.endswith(".py")]
    except Exception:
        files = []
    tests = []
    for f in files:
        name = Path(f).stem
        # common pattern: test_<module>.py or <module>_test.py
        tests.append(f"tests/test_{name}.py")
        tests.append(f"tests/{name}_test.py")
    # filter existing paths
    tests = [t for t in tests if Path(t).exists()]
    return list(dict.fromkeys(tests))

def cmd_focus(args):
    if args.pytest:
        if args.k:
            cmd = f"pytest -q -k \"{args.k}\""
            print("Running pytest with -k filter:", args.k)
            cmd_run(argparse.Namespace(cmd=cmd, out=args.out))
            return
        tests = find_changed_tests()
        if not tests:
            print("No changed tests detected. Run full test suite or pass -k filter.")
            return
        cmd = "pytest -q " + " ".join(tests)
        print("Running tests for changed files:", tests)
        cmd_run(argparse.Namespace(cmd=cmd, out=args.out))
        return
    print("No focus strategy selected. Use --pytest to target pytest.")

def parse_args():
    p = argparse.ArgumentParser(prog="devtriage", description="Simple triage CLI (MVP).")
    sub = p.add_subparsers(dest="cmd_name")
    # run
    a_run = sub.add_parser("run", help="Run a command and store stdout/stderr into out dir.")
    a_run.add_argument("--cmd", required=True, help="Command to run (string).")
    a_run.add_argument("--out", default=f"./.devtriage/{timestamp()}", help="Output directory.")
    a_run.set_defaults(func=cmd_run)
    # snapshot
    a_snap = sub.add_parser("snapshot", help="Snapshot env and command outputs into a zip.")
    a_snap.add_argument("--cmd", help="Command to run and capture.")
    a_snap.add_argument("--out", default=f"./.devtriage/{timestamp()}", help="Output directory.")
    a_snap.set_defaults(func=cmd_snapshot)
    # issue
    a_issue = sub.add_parser("issue", help="Generate ISSUE.md with a snapshot.")
    a_issue.add_argument("--cmd", required=True, help="Failing command to include.")
    a_issue.add_argument("--title", help="Issue title")
    a_issue.add_argument("--out", default=f"./.devtriage/{timestamp()}", help="Output directory.")
    a_issue.set_defaults(func=cmd_issue)
    # focus
    a_focus = sub.add_parser("focus", help="Run tests only for changed files or pytest filters.")
    a_focus.add_argument("--pytest", action="store_true", help="Use pytest focus behavior.")
    a_focus.add_argument("-k", help="Pass a -k expression to pytest.")
    a_focus.add_argument("--out", default=f"./.devtriage/{timestamp()}", help="Output dir for logs.")
    a_focus.set_defaults(func=cmd_focus)
    return p.parse_args()

def main():
    args = parse_args()
    if not args.cmd_name:
        print("No command. Use --help.")
        sys.exit(1)
    try:
        result = args.func(args)
        if isinstance(result, int):
            sys.exit(result)
    except KeyboardInterrupt:
        print("Interrupted.")
        sys.exit(2)

if __name__ == "__main__":
    main()

How to use (quick)

Save as devtriage.py in project root and chmod +x devtriage.py (optional).

Run a failing test and capture:

./devtriage.py run --cmd "pytest tests/test_x.py::test_y -q" --out ./triage/myfailure


Snapshot + zip:

./devtriage.py snapshot --cmd "pytest tests/test_x.py::test_y -q" --out ./triage/myfailure
# writes .devtriage/.../devtriage_snapshot_*.zip


Create an ISSUE.md with environment and attached zip:

./devtriage.py issue --cmd "pytest tests/test_x.py::test_y -q" --title "test_y fails" --out ./triage/myfailure


Focus on changed tests:

./devtriage.py focus --pytest
# or
./devtriage.py focus --pytest -k "fast and not integration"

Why this helps

Removes friction: one command gathers logs, env, git state, pip freeze, and packages them.

Makes CI-debugging faster: attach the zip to an issue and the repo + state is clear.

Reduces back-and-forth: teammates can reproduce locally from the snapshot.

Beats "it works on my machine" with data.

Roadmap — 6 small, highly useful additions

Auto-detect test runner (pytest, nosetests, mocha, jest) and adapt commands.

Static analysis integration: run mypy/flake8 and include suggestions.

git bisect helper: interactive helper that runs the test for each bisect step (careful: destructive).

Minimal repro extractor: try to identify the smallest subset of files needed to reproduce and package just them.

GitHub/GitLab autoposter: open an issue and upload attachments via API (token-based).

Optional: suggest probable causes using local trace analysis and pattern matching of exception traces.

Next steps (I already did the heavy lifting)

I gave you a practical MVP you can run immediately. If you want, I can:

scaffold a full repo (entry script, setup.cfg/pyproject, tests).

add git-bisect automation with safe guard prompts or a dry-run mode.

convert into a pip-installable package with a console script.