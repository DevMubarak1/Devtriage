#!/usr/bin/env python3
"""
devtriage.py — CLI to triage, capture, and package failing runs/tests.

Usage examples:
  python devtriage.py run --cmd "pytest tests/test_foo.py::test_bar -q"
  python devtriage.py snapshot --cmd "pytest tests/test_foo.py::test_bar -q" --out ./triage_output
  python devtriage.py issue --cmd "pytest tests/test_foo.py::test_bar -q" --out ./triage_output --title "Failing test_bar on feature X"
  python devtriage.py focus --auto -k "critical and not slow"
"""

import argparse
import sys
import subprocess
import json
from datetime import datetime, timezone
import platform
import zipfile
from pathlib import Path

ROOT = Path.cwd()
__version__ = "0.2.0"
SUPPORTED_RUNNERS = ("pytest", "nose", "jest", "mocha")
PYTHON_TEST_EXTENSIONS = {".py"}
JS_TEST_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}


def run_cmd(cmd, cwd=None, shell=True, capture_output=True, env=None):
    if isinstance(cmd, list):
        shell = False
    proc = subprocess.run(
        cmd,
        shell=shell,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=True,
    )
    return (
        proc.returncode,
        proc.stdout if proc.stdout is not None else "",
        proc.stderr if proc.stderr is not None else "",
    )


def timestamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def gather_env_info():
    info = {
        "timestamp_utc": timestamp(),
        "cwd": str(Path.cwd()),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "executable": sys.executable,
        "git": None,
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
                "changed_files": diff.strip().splitlines(),
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


def read_package_json():
    pkg_path = Path("package.json")
    if not pkg_path.exists():
        return {}
    try:
        return json.loads(pkg_path.read_text())
    except Exception:
        return {}


def file_contains(path, needle):
    try:
        return needle in Path(path).read_text()
    except Exception:
        return False


def detect_test_runner():
    package_json = read_package_json()
    if package_json:
        scripts = package_json.get("scripts") or {}
        dependencies = {
            **(package_json.get("dependencies") or {}),
            **(package_json.get("devDependencies") or {}),
        }
        script_blob = " ".join(scripts.values())
        if "jest" in dependencies or "jest" in script_blob:
            return "jest"
        if "mocha" in dependencies or "mocha" in script_blob:
            return "mocha"
    pytest_markers = [
        "pytest.ini",
        "conftest.py",
        "tox.ini",
        "setup.cfg",
        "pyproject.toml",
    ]
    for marker in pytest_markers:
        path = Path(marker)
        if path.exists():
            if path.name in {"setup.cfg", "tox.ini", "pyproject.toml"}:
                if file_contains(path, "pytest"):
                    return "pytest"
            else:
                return "pytest"
    nose_markers = ["nose.cfg", "setup.cfg", "tox.ini"]
    for marker in nose_markers:
        path = Path(marker)
        if path.exists() and file_contains(path, "nosetests"):
            return "nose"
    return "pytest"


def get_git_changed_files():
    try:
        _, out, _ = run_cmd(["git", "diff", "--name-only", "HEAD"], shell=False)
        return [Path(line.strip()) for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def find_changed_python_tests():
    files = [f for f in get_git_changed_files() if f.suffix in PYTHON_TEST_EXTENSIONS]
    tests = []
    for f in files:
        name = f.stem
        if "tests" in f.parts or name.startswith("test_") or name.endswith("_test"):
            tests.append(str(f))
            continue
        candidates = [
            Path("tests") / f"test_{name}.py",
            Path("tests") / f"{name}_test.py",
        ]
        for candidate in candidates:
            if candidate.exists():
                tests.append(str(candidate))
    return list(dict.fromkeys(tests))


def find_changed_js_tests():
    files = [f for f in get_git_changed_files() if f.suffix in JS_TEST_EXTENSIONS]
    tests = []
    for f in files:
        if (
            ".test." in f.name
            or f.stem.startswith("test_")
            or f.stem.endswith("_test")
            or "__tests__" in f.parts
            or "tests" in f.parts
        ):
            tests.append(str(f))
            continue
        candidate = Path("tests") / f"{f.stem}.test{f.suffix}"
        if candidate.exists():
            tests.append(str(candidate))
    return list(dict.fromkeys(tests))


def build_runner_command(runner, tests, expression):
    if runner == "pytest":
        cmd = ["pytest", "-q"]
        if expression:
            cmd += ["-k", expression]
        if tests:
            cmd += tests
        return cmd
    if runner == "nose":
        cmd = ["nosetests"]
        if expression:
            cmd += ["-m", expression]
        if tests:
            cmd += tests
        return cmd
    if runner == "jest":
        cmd = ["npx", "jest"]
        if expression:
            cmd += ["--testNamePattern", expression]
        if tests:
            cmd += tests
        return cmd
    if runner == "mocha":
        cmd = ["npx", "mocha"]
        if expression:
            cmd += ["--grep", expression]
        if tests:
            cmd += tests
        return cmd
    return None


def ensure_outdir(outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    return out.resolve()


def cmd_run(args):
    outdir = ensure_outdir(args.out)
    command_to_run = args.cmd
    if isinstance(command_to_run, list):
        display_cmd = " ".join(str(part) for part in command_to_run)
    else:
        display_cmd = command_to_run
    meta = {"command": display_cmd, "started_at": timestamp()}
    with open(outdir / "devtriage_meta.json", "w") as f:
        json.dump(meta, f)
    print(f"Running: {display_cmd}")
    code, stdout, stderr = run_cmd(command_to_run, capture_output=True)
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
    if isinstance(summary, dict):
        summary_lines = [f"- {key}: {value}" for key, value in summary.items()]
        md.append("\n".join(summary_lines) + "\n")
    else:
        md.append(f"{summary}\n")
    md.append("## Reproduction steps\n")
    md.append("1. Clone repo and `cd` into it\n")
    md.append(
        "2. Run the failing command (example):\n\n```bash\n"
        f"{summary.get('command','(command not recorded)')}\n```\n"
    )
    md.append("## Environment\n")
    md.append(f"- OS: {env_info.get('platform')}\n")
    md.append(f"- Python: {env_info.get('python_version')}\n")
    if env_info.get("git"):
        md.append(f"- Git branch: {env_info['git'].get('branch')}\n")
        md.append(f"- Git rev: {env_info['git'].get('rev')}\n")
    md.append("\n## Attachments\n")
    md.append(f"- Snapshot zip: `{snapshot_zip_path}`\n")
    md.append(
        "\n## Notes\n- Minimal reproduction packaged. Please open if further info required.\n"
    )
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


def cmd_focus(args):
    runner = None
    if args.runner:
        runner = args.runner
    elif args.pytest:
        runner = "pytest"
    else:
        if args.auto or not args.runner:
            runner = detect_test_runner()
            print(f"Auto-detected test runner: {runner}")
    if runner not in SUPPORTED_RUNNERS:
        print(
            "No focus strategy selected. Use --runner, --pytest, or allow auto-detection."
        )
        return
    if runner in {"pytest", "nose"}:
        tests = find_changed_python_tests()
    else:
        tests = find_changed_js_tests()
    if not tests and not args.k:
        print("No changed tests detected. Run full suite or pass -k/--runner.")
        return
    command = build_runner_command(runner, tests, args.k)
    if not command:
        print(f"No focus strategy implemented for runner '{runner}'.")
        return
    display_tests = tests if tests else ["<full-suite>"]
    print(f"Running {runner} with focus targets: {display_tests}")
    cmd_run(argparse.Namespace(cmd=command, out=args.out))


def parse_args():
    p = argparse.ArgumentParser(prog="devtriage", description="Simple triage CLI (MVP).")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
    a_focus = sub.add_parser(
        "focus", help="Run tests only for changed files or pytest filters."
    )
    a_focus.add_argument(
        "--pytest",
        action="store_true",
        help="Shortcut for --runner pytest (deprecated, will be removed).",
    )
    a_focus.add_argument(
        "--runner",
        choices=SUPPORTED_RUNNERS,
        help="Force a specific test runner (pytest, nose, jest, mocha).",
    )
    a_focus.add_argument(
        "--auto",
        action="store_true",
        help="Auto-detect the runner (default when no --runner/--pytest).",
    )
    a_focus.add_argument(
        "-k",
        help="Expression/pattern to filter tests (-k/--grep/--testNamePattern depending on runner).",
    )
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

