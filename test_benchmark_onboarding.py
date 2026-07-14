import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SETUP = ROOT / ".agents" / "skills" / "benchmark-onboarding" / "scripts" / "setup.py"


class BenchmarkOnboardingTests(unittest.TestCase):
    def run_setup(self, *args, env=None):
        return subprocess.run(
            ["python3", SETUP, *map(str, args)],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_inspect_reports_harnesses_without_reading_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_setup("inspect", "--repo", directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["repo"], str(Path(directory).resolve()))
        self.assertEqual(
            set(report["harnesses"]), {"iris", "claude-code", "codex", "pi"}
        )
        self.assertIn("docker", report["commands"])
        self.assertIn("harbor", report["commands"])
        self.assertIn("claude_credentials", report["credential_presence"])
        self.assertIsInstance(report["credential_presence"]["claude_credentials"], bool)

    def test_configure_writes_non_secret_marker_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            jobs = repo / "private jobs"
            result = self.run_setup(
                "configure",
                "--repo",
                repo,
                "--harness",
                "iris",
                "--harness",
                "claude-code",
                "--iris-build",
                "latest-release",
                "--jobs-dir",
                jobs,
                "--concurrency",
                "2",
            )
            marker = repo / ".benchmark-setup"
            content = marker.read_text()
            mode = stat.S_IMODE(marker.stat().st_mode)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(mode, 0o600)
        self.assertIn("version=1\n", content)
        self.assertIn("harnesses=iris,claude-code\n", content)
        self.assertIn("iris_build=latest-release\n", content)
        self.assertIn(f"jobs_dir={jobs.resolve()}\n", content)
        self.assertIn("concurrency=2\n", content)
        self.assertNotIn("TOKEN", content.upper())
        self.assertNotIn("KEY", content.upper())

    def test_configure_rejects_binary_mode_without_real_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_setup(
                "configure",
                "--repo",
                directory,
                "--harness",
                "iris",
                "--iris-build",
                "local-source",
                "--iris-binary",
                Path(directory) / "missing-iris",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("iris binary is not a file", result.stderr)
            self.assertFalse((Path(directory) / ".benchmark-setup").exists())

    def test_runner_reads_marker_without_executing_values(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            fake_bin = temp / "bin"
            fake_bin.mkdir()
            capture = temp / "capture.txt"
            fake_harbor = fake_bin / "harbor"
            fake_harbor.write_text(
                "#!/bin/sh\n"
                "printf 'IRIS_BINARY_PATH=%s\\n' \"${IRIS_BINARY_PATH:-}\" > \"$CAPTURE\"\n"
                "printf '%s\\n' \"$@\" >> \"$CAPTURE\"\n"
            )
            fake_harbor.chmod(0o755)
            iris_binary = temp / "iris"
            iris_binary.write_text("binary")
            jobs = temp / "jobs $(touch should-not-exist)"
            marker = temp / "setup"
            marker.write_text(
                "version=1\n"
                "harnesses=iris\n"
                "iris_build=local-source\n"
                f"jobs_dir={jobs}\n"
                "concurrency=3\n"
                "harbor_dir=\n"
                f"iris_binary_path={iris_binary}\n"
            )
            env = os.environ.copy()
            env.update(
                {
                    "BENCH_SETUP_FILE": str(marker),
                    "CAPTURE": str(capture),
                    "HOME": str(temp / "home"),
                    "PATH": f"{fake_bin}:{env['PATH']}",
                }
            )
            result = subprocess.run(
                [ROOT / "run-bench.sh", "iris", "anthropic/test", "-l", "1"],
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            recorded = capture.read_text()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"IRIS_BINARY_PATH={iris_binary}\n", recorded)
        self.assertIn(f"--jobs-dir\n{jobs}\n", recorded)
        self.assertIn("--n-concurrent\n3\n", recorded)
        self.assertFalse((temp / "should-not-exist").exists())

    def test_skill_wiring_and_first_run_trigger_are_present(self):
        skill = ROOT / ".agents" / "skills" / "benchmark-onboarding" / "SKILL.md"
        link = ROOT / ".claude" / "skills" / "benchmark-onboarding"
        agents = (ROOT / "AGENTS.md").read_text()
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), skill.parent.resolve())
        self.assertIn(".benchmark-setup", skill.read_text())
        self.assertIn(".benchmark-setup", agents)
        self.assertIn("benchmark-onboarding", agents)


if __name__ == "__main__":
    unittest.main()
