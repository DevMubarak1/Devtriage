"""Focus-mode and test runner detection utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .capture import cmd_run, run_cmd

SUPPORTED_RUNNERS = ("pytest", "nose", "jest", "mocha")
PYTHON_TEST_EXTENSIONS = {".py"}
JS_TEST_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}


def read_package_json() -> Dict:
    pkg_path = Path("package.json")
    if not pkg_path.exists():
        return {}
    try:
        return json.loads(pkg_path.read_text())
    except Exception:
        return {}


def file_contains(path: Path, needle: str) -> bool:
    try:
        return needle in path.read_text()
    except Exception:
        return False


def detect_test_runner() -> str:
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
        Path("pytest.ini"),
        Path("conftest.py"),
        Path("tox.ini"),
        Path("setup.cfg"),
        Path("pyproject.toml"),
    ]
    for marker in pytest_markers:
        if marker.exists():
            if marker.name in {"setup.cfg", "tox.ini", "pyproject.toml"}:
                if file_contains(marker, "pytest"):
                    return "pytest"
            else:
                return "pytest"
    nose_markers = [Path("nose.cfg"), Path("setup.cfg"), Path("tox.ini")]
    for marker in nose_markers:
        if marker.exists() and file_contains(marker, "nosetests"):
            return "nose"
    return "pytest"


def get_git_changed_files() -> List[Path]:
    try:
        _, out, _ = run_cmd(["git", "diff", "--name-only", "HEAD"])
        return [Path(line.strip()) for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def find_changed_python_tests() -> List[str]:
    files = [f for f in get_git_changed_files() if f.suffix in PYTHON_TEST_EXTENSIONS]
    tests: List[str] = []
    for file in files:
        stem = file.stem
        if "tests" in file.parts or stem.startswith("test_") or stem.endswith("_test"):
            tests.append(str(file))
            continue
        candidates = [
            Path("tests") / f"test_{stem}.py",
            Path("tests") / f"{stem}_test.py",
        ]
        for candidate in candidates:
            if candidate.exists():
                tests.append(str(candidate))
    return list(dict.fromkeys(tests))


def find_changed_js_tests() -> List[str]:
    files = [f for f in get_git_changed_files() if f.suffix in JS_TEST_EXTENSIONS]
    tests: List[str] = []
    for file in files:
        if (
            ".test." in file.name
            or file.stem.startswith("test_")
            or file.stem.endswith("_test")
            or "__tests__" in file.parts
            or "tests" in file.parts
        ):
            tests.append(str(file))
            continue
        candidate = Path("tests") / f"{file.stem}.test{file.suffix}"
        if candidate.exists():
            tests.append(str(candidate))
    return list(dict.fromkeys(tests))


def build_runner_command(runner: str, tests: List[str], expression: str | None) -> List[str] | None:
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


def focus_command(args) -> None:
    runner = args.runner
    if args.pytest:
        runner = "pytest"
    if args.auto or not runner:
        runner = detect_test_runner()
        print(f"Auto-detected test runner: {runner}")
    if runner not in SUPPORTED_RUNNERS:
        print("No focus strategy selected. Use --runner/--pytest or enable --auto.")
        return
    tests = (
        find_changed_python_tests()
        if runner in {"pytest", "nose"}
        else find_changed_js_tests()
    )
    if not tests and not args.k:
        print("No changed tests detected. Run full suite or pass -k/--runner.")
        return
    command = build_runner_command(runner, tests, args.k)
    if not command:
        print(f"No focus strategy implemented for runner '{runner}'.")
        return
    target_label = tests if tests else ["<full-suite>"]
    print(f"Running {runner} with focus targets: {target_label}")
    cmd_run(command, args.out)

