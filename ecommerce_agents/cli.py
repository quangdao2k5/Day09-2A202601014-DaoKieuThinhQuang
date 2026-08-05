"""Command-line interface for running, validating and packaging submissions."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

from .coordinator import Coordinator


def _root(value: str) -> Path:
    return Path(value).resolve()


def run_command(args: argparse.Namespace) -> int:
    coordinator = Coordinator(args.root, llm_audit=args.llm_audit)
    outputs = coordinator.run(expected_count=50)
    counts = Counter(row["case_assessment"]["primary_issue"] for row in outputs)
    print(
        json.dumps(
            {
                "status": "completed",
                "case_count": len(outputs),
                "llm_audit": args.llm_audit,
                "primary_issue_counts": dict(sorted(counts.items())),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def validate_command(args: argparse.Namespace) -> int:
    coordinator = Coordinator(args.root, llm_audit=False)
    cases = coordinator._load_cases(50)
    expected = [f"EC_{index:03d}.json" for index in range(1, 51)]
    actual = sorted(path.name for path in (args.root / "output").glob("*.json"))
    errors: list[str] = []
    if actual != expected:
        errors.append("output/ must contain exactly EC_001.json through EC_050.json")
    for case in cases:
        path = args.root / "output" / f"{case['case_id']}.json"
        if not path.exists():
            continue
        try:
            output = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{path.name}: invalid JSON: {exc}")
            continue
        for error in coordinator.verifier_agent.verify(case, output, coordinator.repository):
            errors.append(f"{path.name}: {error}")
    result = {"status": "passed" if not errors else "failed", "error_count": len(errors)}
    if errors:
        result["errors"] = errors[:50]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def package_command(args: argparse.Namespace) -> int:
    dirty_source = _dirty_source_paths(args.root)
    if dirty_source and not args.allow_dirty_source:
        print(
            "Refusing to package before source/input changes are committed:\n"
            + "\n".join(f"- {path}" for path in dirty_source),
            file=sys.stderr,
        )
        return 2
    files = sorted((args.root / "output").glob("EC_*.json"))
    expected_files = [f"EC_{index:03d}.json" for index in range(1, 51)]
    if [path.name for path in files] != expected_files:
        print("output/ does not contain exactly 50 expected JSON files", file=sys.stderr)
        return 1
    expected_archive = [f"output/{name}" for name in expected_files]
    destination = args.destination.resolve()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, arcname=f"output/{path.name}")
    with zipfile.ZipFile(destination) as archive:
        names = sorted(archive.namelist())
        if names != expected_archive or archive.testzip() is not None:
            raise RuntimeError("ZIP verification failed")
    size = destination.stat().st_size
    if size > 5 * 1024 * 1024:
        raise RuntimeError(f"ZIP exceeds 5 MB: {size} bytes")
    print(json.dumps({"status": "packaged", "path": str(destination), "files": 50, "bytes": size}, indent=2))
    return 0


def _dirty_source_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    ignored_prefixes = ("output/", "logging/trace.jsonl", "logging/metadata.json")
    dirty: list[str] = []
    for line in result.stdout.splitlines():
        path = line[3:].split(" -> ")[-1]
        if path == ".DS_Store" or path.endswith(".zip") or path.startswith(ignored_prefixes):
            continue
        dirty.append(path)
    return dirty


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=_root, default=Path.cwd(), help="repository root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="process all 50 cases")
    run_parser.add_argument(
        "--llm-audit",
        action="store_true",
        help="use the configured <=10B model for read-only final audits",
    )
    run_parser.set_defaults(func=run_command)

    validate_parser = subparsers.add_parser("validate", help="validate all existing outputs")
    validate_parser.set_defaults(func=validate_command)

    package_parser = subparsers.add_parser("package", help="create the grader ZIP")
    package_parser.add_argument(
        "--destination", type=Path, default=Path("submission_output.zip")
    )
    package_parser.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help="emergency override; final submission should not use this",
    )
    package_parser.set_defaults(func=package_command)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
