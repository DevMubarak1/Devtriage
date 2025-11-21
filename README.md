# devtriage

`devtriage` is a lightweight CLI that turns a failing command into a reproducible bug report. It captures stdout/stderr, environment data, git context, and produces shareable snapshots or issue templates so teammates can reproduce failures quickly.

## Features
- `run`: execute any command and capture logs plus exit metadata.
- `snapshot`: record environment info (OS, Python, pip freeze, git status) and bundle it together with command output in a zip archive.
- `issue`: run `snapshot` and emit an `ISSUE.md` template that links to the captured data.
- `focus`: auto-detect your test runner (pytest, nose, jest, mocha) or use `--runner` to pin one, then execute only the changed tests or apply a `-k`/pattern filter.
- Safe-by-default: no destructive git actions, just inspection and logging.

## Installation
- Stable release: `pip install devtriage`
- From source: clone the repo and run `pip install -e .`

Either path installs the `devtriage` console script (or run `python -m devtriage` inside the repo). Python 3.8+ is required.

## Usage
### Capture a failing test
```
devtriage run --cmd "pytest tests/test_widget.py::test_happy_path -q" --out ./triage/widget_fail
```
The target directory receives `stdout.txt`, `stderr.txt`, and `meta.json` describing the run.

### Snapshot & share
```
devtriage snapshot --cmd "pytest tests/test_widget.py::test_happy_path -q" --out ./triage/widget_fail
```
This writes `env.json` plus a timestamped `devtriage_snapshot_*.zip` with everything you need for a bug report.

### Generate an Issue
```
devtriage issue --cmd "pytest tests/test_widget.py::test_happy_path -q" --title "Widget test regression" --out ./triage/widget_fail
```
`ISSUE.md` summarizes the failure, environment, and includes the snapshot path; paste it into GitHub/GitLab.

### Focused test runs
- Auto-detect:
  `devtriage focus --auto`
- Force a runner:
  `devtriage focus --runner jest -k "critical"`
- Legacy flag:
  `devtriage focus --pytest`

`devtriage` inspects `git diff --name-only HEAD` to find relevant tests for Python and JavaScript ecosystems. When no changed tests exist, pass `-k/--runner` to run the full suite with filters.

## Contributing
1. Fork and clone the repo.
2. Create a virtual environment and install with `pip install -e .[dev]` (or `pip install -e .` + `pip install pytest` for tests).
3. Run `pytest` to execute automated checks (including runner-detection heuristics).
4. Run `python -m devtriage --help` to validate the CLI locally.
5. Open pull requests with a clear description of the bugfix/feature plus any new tests or instructions.

## Releasing
See `RELEASING.md` for the PyPI workflow (build via `python -m build` and upload with `twine`). The canonical repository is [DevMubarak1/Devtriage](https://github.com/DevMubarak1/Devtriage).

## License
MIT © 2025 devtriage contributors

