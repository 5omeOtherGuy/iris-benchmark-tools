#!/usr/bin/env python3
"""Inspect and persist non-secret benchmark checkout configuration."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HARNESSES = ("iris", "claude-code", "codex", "pi")
COMMANDS = ("docker", "harbor", "uv", "iris", "claude", "codex", "pi", "cargo", "git")
VERSION_ARGS = {
    "docker": ("--version",),
    "harbor": ("--version",),
    "uv": ("--version",),
    "iris": ("--version",),
    "claude": ("--version",),
    "codex": ("--version",),
    "pi": ("--version",),
    "cargo": ("--version",),
    "git": ("--version",),
}
IRIS_BUILD_CHOICES = ("latest-release", "installed", "local-source", "custom")


def first_line(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0] if output else None


def command_report(name: str) -> dict[str, str | None]:
    path = shutil.which(name)
    return {
        "path": path,
        "version": first_line([path, *VERSION_ARGS[name]]) if path else None,
    }


def git_value(repo: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", repo, *args],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    value = result.stdout.strip()
    return value or None if result.returncode == 0 else None


def local_iris_sources(repo: Path) -> list[dict[str, object]]:
    candidates: list[Path] = []
    configured = os.environ.get("IRIS_SOURCE_DIR")
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            repo.parent / "iris-agent",
            Path.home() / "projects" / "iris-agent",
        ]
    )
    found: list[dict[str, object]] = []
    seen: set[Path] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen or not (candidate / "Cargo.toml").is_file():
            continue
        seen.add(candidate)
        status = git_value(candidate, "status", "--porcelain")
        found.append(
            {
                "path": str(candidate),
                "commit": git_value(candidate, "rev-parse", "HEAD"),
                "dirty": bool(status),
                "release_binary": str(candidate / "target" / "release" / "iris"),
                "release_binary_exists": (candidate / "target" / "release" / "iris").is_file(),
            }
        )
    return found


def configured_file(env_name: str, default: Path) -> bool:
    configured = os.environ.get(env_name)
    path = Path(configured).expanduser() if configured else default
    return path.is_file()


def inspect(repo: Path) -> dict[str, object]:
    commands = {name: command_report(name) for name in COMMANDS}
    docker_daemon = None
    if commands["docker"]["path"]:
        docker_daemon = first_line(
            [commands["docker"]["path"], "info", "--format", "{{.ServerVersion}}"]
        )
    return {
        "repo": str(repo),
        "commands": commands,
        "docker_daemon_version": docker_daemon,
        "harnesses": {
            "iris": {
                "harbor_agent": "agents.iris_installed:Iris",
                "host_cli": commands["iris"],
            },
            "claude-code": {
                "harbor_agent": "claude-code",
                "host_cli": commands["claude"],
            },
            "codex": {"harbor_agent": "codex", "host_cli": commands["codex"]},
            "pi": {"harbor_agent": "pi", "host_cli": commands["pi"]},
        },
        "credential_presence": {
            "claude_credentials": configured_file(
                "IRIS_CLAUDE_CREDENTIALS_PATH",
                Path.home() / ".claude" / ".credentials.json",
            ),
            "iris_auth": configured_file(
                "IRIS_AUTH_JSON_PATH", Path.home() / ".iris" / "auth.json"
            ),
            "codex_auth": configured_file(
                "CODEX_AUTH_JSON_PATH", Path.home() / ".codex" / "auth.json"
            ),
            "claude_code_oauth_env": bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")),
        },
        "local_iris_sources": local_iris_sources(repo),
    }


def clean_value(name: str, value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError(f"{name} cannot contain a newline")
    return value


def absolute_path(repo: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def configure(args: argparse.Namespace) -> Path:
    repo = args.repo.resolve()
    if not repo.is_dir():
        raise ValueError(f"repository is not a directory: {repo}")
    harnesses = list(dict.fromkeys(args.harness))
    if not harnesses:
        raise ValueError("select at least one harness")

    jobs_dir = absolute_path(repo, args.jobs_dir or "jobs")
    harbor_dir = absolute_path(repo, args.harbor_dir) if args.harbor_dir else None
    if harbor_dir is not None and not harbor_dir.is_dir():
        raise ValueError(f"Harbor directory is not a directory: {harbor_dir}")

    iris_binary = absolute_path(repo, args.iris_binary) if args.iris_binary else None
    if "iris" in harnesses and args.iris_build != "latest-release":
        if iris_binary is None or not iris_binary.is_file():
            raise ValueError("iris binary is not a file; build or select it before configuring")
    if args.iris_build == "latest-release" and iris_binary is not None:
        raise ValueError("latest-release must not set an iris binary path")

    values = {
        "version": "1",
        "harnesses": ",".join(harnesses),
        "iris_build": args.iris_build,
        "jobs_dir": str(jobs_dir),
        "concurrency": str(args.concurrency),
        "harbor_dir": str(harbor_dir) if harbor_dir else "",
        "iris_binary_path": str(iris_binary) if iris_binary else "",
    }
    for key, value in values.items():
        clean_value(key, value)

    marker = repo / ".benchmark-setup"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=repo, prefix=".benchmark-setup.", delete=False
        ) as temporary:
            temporary_name = temporary.name
            for key, value in values.items():
                temporary.write(f"{key}={value}\n")
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, marker)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return marker


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser("inspect", help="print safe local capability JSON")
    inspect_parser.add_argument("--repo", type=Path, default=Path.cwd())

    configure_parser = commands.add_parser(
        "configure", help="write the ignored non-secret setup marker"
    )
    configure_parser.add_argument("--repo", type=Path, default=Path.cwd())
    configure_parser.add_argument(
        "--harness", action="append", choices=HARNESSES, required=True
    )
    configure_parser.add_argument(
        "--iris-build", choices=IRIS_BUILD_CHOICES, default="latest-release"
    )
    configure_parser.add_argument("--iris-binary")
    configure_parser.add_argument("--jobs-dir")
    configure_parser.add_argument("--harbor-dir")
    configure_parser.add_argument("--concurrency", type=int, choices=range(1, 65), default=1)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "inspect":
            print(json.dumps(inspect(args.repo.resolve()), indent=2, sort_keys=True))
        else:
            marker = configure(args)
            print(marker)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        print(f"benchmark onboarding: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
