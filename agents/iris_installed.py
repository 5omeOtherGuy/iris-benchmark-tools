"""Harbor installed-agent adapter for iris-agent.

Runs iris in headless print mode (`iris -p <instruction> --approve
--dangerously-skip-permissions`) inside the task container.

Host-side configuration (environment variables, all optional):
  IRIS_BINARY_PATH            Path to a local x86_64-linux-gnu `iris` binary to
                              upload into the container. If unset, the adapter
                              downloads the latest GitHub release in the container.
  IRIS_CLAUDE_CREDENTIALS_PATH  Claude Code credentials file to upload; iris
                              bootstraps its Anthropic OAuth from it. Default:
                              ~/.claude/.credentials.json
  IRIS_AUTH_JSON_PATH         Iris auth store (for openai-codex / antigravity
                              OAuth). Default: ~/.iris/auth.json

Usage:
  harbor run -d terminal-bench@2.0 \
    --agent agents.iris_installed:Iris \
    --model anthropic/claude-fable-5 ...
"""

import json
import os
import shlex
from pathlib import Path, PurePosixPath
from typing import override

from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.paths import EnvironmentPaths

_RELEASE_URL = (
    "https://github.com/5omeOtherGuy/iris-agent/releases/latest/download/"
    "iris-agent-x86_64-unknown-linux-gnu.tar.gz"
)
_OUTPUT_FILENAME = "iris.txt"
# End-of-run token/cache/tool accounting emitted by iris `-p` when
# IRIS_USAGE_JSON is set. Written into the preserved agent dir so it survives
# container teardown and can be parsed alongside the transcript.
_USAGE_FILENAME = "iris_usage.json"
# iris session-transcript root, placed inside the agent dir so the per-turn
# tool-call history is downloaded to the host with the rest of the agent logs.
_SESSIONS_DIRNAME = "iris-sessions"


class Iris(BaseInstalledAgent):
    """iris-agent driven through its headless `--print` mode."""

    @staticmethod
    @override
    def name() -> str:
        return "iris"

    @override
    def get_version_command(self) -> str | None:
        return "iris --version 2>/dev/null || true"

    def _host_binary(self) -> Path | None:
        configured = self._get_env("IRIS_BINARY_PATH")
        if not configured:
            return None
        path = Path(configured).expanduser()
        if not path.is_file():
            raise ValueError(f"IRIS_BINARY_PATH is not a file: {path}")
        return path

    @override
    async def install(self, environment: BaseEnvironment) -> None:
        binary = self._host_binary()
        if binary is not None:
            await environment.upload_file(binary, "/usr/local/bin/iris")
            await self.exec_as_root(
                environment, command="chmod 755 /usr/local/bin/iris"
            )
        else:
            await self.exec_as_root(
                environment,
                command=(
                    "if command -v apt-get >/dev/null 2>&1; then"
                    "  apt-get update && apt-get install -y curl ca-certificates;"
                    " fi"
                ),
                env={"DEBIAN_FRONTEND": "noninteractive"},
            )
            await self.exec_as_root(
                environment,
                command=(
                    "set -euo pipefail; "
                    f"curl -fsSL {shlex.quote(_RELEASE_URL)} | tar -xz -C /tmp && "
                    "install -m 755 "
                    "/tmp/iris-agent-x86_64-unknown-linux-gnu/iris "
                    "/usr/local/bin/iris"
                ),
            )
        # The gnu binary needs glibc; fail the install fast on musl images so
        # the trial is marked as an agent-setup error, not a silent zero.
        await self.exec_as_agent(environment, command="iris --version")

    def _credential_uploads(self) -> list[tuple[Path, str, str]]:
        """(host_path, container_tmp_path, container_dest) for each credential."""
        uploads: list[tuple[Path, str, str]] = []
        claude_creds = Path(
            self._get_env("IRIS_CLAUDE_CREDENTIALS_PATH")
            or Path.home() / ".claude" / ".credentials.json"
        ).expanduser()
        if claude_creds.is_file():
            uploads.append(
                (claude_creds, "/tmp/iris-claude-creds.json",
                 "$HOME/.claude/.credentials.json")
            )
        iris_auth = Path(
            self._get_env("IRIS_AUTH_JSON_PATH")
            or Path.home() / ".iris" / "auth.json"
        ).expanduser()
        if iris_auth.is_file():
            uploads.append(
                (iris_auth, "/tmp/iris-auth.json", "$HOME/.iris/auth.json")
            )
        return uploads

    @with_prompt_template
    @override
    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        if not self.model_name:
            raise ValueError("Model name is required (e.g. anthropic/claude-fable-5)")
        provider, _, model = self.model_name.partition("/")
        if not model:
            provider, model = "anthropic", provider

        settings = json.dumps(
            {
                "defaultProvider": provider,
                "defaultModel": model,
                "defaultApproval": "dangerously-skip-permissions",
            }
        )

        uploads = self._credential_uploads()
        if not uploads:
            raise ValueError(
                "No credentials found to upload "
                "(IRIS_CLAUDE_CREDENTIALS_PATH / IRIS_AUTH_JSON_PATH)"
            )
        for host_path, tmp_path, _ in uploads:
            await environment.upload_file(host_path, tmp_path)
            await self.exec_as_root(
                environment, command=f"chmod 600 {shlex.quote(tmp_path)}"
            )

        setup = "mkdir -p $HOME/.iris $HOME/.claude\n"
        for _, tmp_path, dest in uploads:
            setup += (
                f"cp {shlex.quote(tmp_path)} {dest} && chmod 600 {dest}\n"
            )
        setup += f"cat > $HOME/.iris/settings.json <<'EOF'\n{settings}\nEOF\n"
        setup += f"mkdir -p {EnvironmentPaths.agent_dir.as_posix()}"
        await self.exec_as_agent(environment, command=setup)

        output_path = PurePosixPath(EnvironmentPaths.agent_dir) / _OUTPUT_FILENAME
        usage_path = PurePosixPath(EnvironmentPaths.agent_dir) / _USAGE_FILENAME
        # Persist the session transcript into the preserved agent dir too, so a
        # run's full tool-call history (commands, results) survives container
        # teardown -- including after an agent-timeout kill, since iris appends
        # each entry as it happens.
        sessions_dir = PurePosixPath(EnvironmentPaths.agent_dir) / _SESSIONS_DIRNAME
        try:
            await self.exec_as_agent(
                environment,
                command=(
                    # Env assignments bind to `iris` only (before the pipe), so
                    # the usage JSON + session transcript land in the preserved
                    # agent dir while stdout still carries only the final answer.
                    f"IRIS_USAGE_JSON={shlex.quote(usage_path.as_posix())} "
                    f"IRIS_SESSION_DIR={shlex.quote(sessions_dir.as_posix())} "
                    "iris -p "
                    f"{shlex.quote(instruction)} "
                    "--approve --dangerously-skip-permissions "
                    f"2>&1 </dev/null | tee {output_path.as_posix()}"
                ),
            )
        finally:
            # Best effort: don't leave credentials in shared tmp.
            try:
                await self.exec_as_root(
                    environment,
                    command="rm -f /tmp/iris-claude-creds.json /tmp/iris-auth.json",
                )
            except Exception:
                pass
