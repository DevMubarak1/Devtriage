"""Command-line interface for devtriage."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .capture import cmd_issue, cmd_run, cmd_snapshot, default_outdir
from .runners import SUPPORTED_RUNNERS, focus_command


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="devtriage",
        description="Capture failing runs/tests and generate reproducible reports.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd_name")

    run_cmd = sub.add_parser("run", help="Run a command and store stdout/stderr.")
    run_cmd.add_argument("--cmd", required=True, help="Command to run (string).")
    run_cmd.add_argument(
        "--out",
        default=default_outdir(),
        help="Output directory (default: timestamped ./.devtriage/<UTC>).",
    )
    run_cmd.set_defaults(func=lambda args: cmd_run(args.cmd, args.out))

    snap_cmd = sub.add_parser("snapshot", help="Snapshot env + command outputs.")
    snap_cmd.add_argument("--cmd", help="Command to run and capture.")
    snap_cmd.add_argument(
        "--out",
        default=default_outdir(),
        help="Output directory (default: timestamped ./.devtriage/<UTC>).",
    )
    snap_cmd.set_defaults(func=lambda args: cmd_snapshot(args.cmd, args.out))

    issue_cmd = sub.add_parser("issue", help="Generate ISSUE.md with a snapshot.")
    issue_cmd.add_argument("--cmd", required=True, help="Failing command to include.")
    issue_cmd.add_argument("--title", help="Issue title.")
    issue_cmd.add_argument(
        "--gh",
        action="store_true",
        help="Use GitHub CLI (gh) to open an issue with the generated template.",
    )
    issue_cmd.add_argument(
        "--gh-repo",
        help="Override the GitHub repository (owner/repo) when using --gh.",
    )
    issue_cmd.add_argument(
        "--out",
        default=default_outdir(),
        help="Output directory (default: timestamped ./.devtriage/<UTC>).",
    )
    issue_cmd.set_defaults(
        func=lambda args: cmd_issue(args.cmd, args.out, args.title, args.gh, args.gh_repo)
    )

    focus_cmd = sub.add_parser("focus", help="Run tests only for changed files.")
    focus_cmd.add_argument(
        "--pytest",
        action="store_true",
        help="Shortcut for --runner pytest (deprecated).",
    )
    focus_cmd.add_argument(
        "--runner",
        choices=SUPPORTED_RUNNERS,
        help="Force a specific test runner.",
    )
    focus_cmd.add_argument(
        "--auto",
        action="store_true",
        help="Auto-detect the runner (default when no --runner/--pytest).",
    )
    focus_cmd.add_argument(
        "-k",
        help="Expression/pattern filter (-k/--grep/--testNamePattern depending on runner).",
    )
    focus_cmd.add_argument(
        "--out",
        default=default_outdir(),
        help="Output dir for logs (default: timestamped ./.devtriage/<UTC>).",
    )
    focus_cmd.set_defaults(func=focus_command)

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if not args.cmd_name:
        print("No command. Use --help.")
        return 1
    result = args.func(args)
    if isinstance(result, int):
        return result
    return 0


if __name__ == "__main__":
    sys.exit(main())

