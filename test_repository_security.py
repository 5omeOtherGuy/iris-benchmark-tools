import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCANNER = ROOT / "scripts" / "check-no-secrets.sh"


class RepositorySecurityTests(unittest.TestCase):
    def make_repo(self):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        subprocess.run(["git", "init", "-q", root], check=True)
        return temporary, root

    def run_scanner(self, root):
        env = os.environ.copy()
        env["SECRET_SCAN_ROOT"] = str(root)
        return subprocess.run(
            [SCANNER],
            text=True,
            capture_output=True,
            env=env,
            check=False,
        )

    def test_scanner_accepts_publishable_source(self):
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        (root / "tool.py").write_text("print('synthetic fixture')\n")
        subprocess.run(["git", "-C", root, "add", "tool.py"], check=True)

        result = self.run_scanner(root)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("secret scan: clean", result.stdout)

    def test_scanner_rejects_benchmark_payload_paths(self):
        for relative in ("jobs/trial/result.json", ".benchmark-setup"):
            with self.subTest(relative=relative):
                temporary, root = self.make_repo()
                try:
                    payload = root / relative
                    payload.parent.mkdir(parents=True, exist_ok=True)
                    payload.write_text("{}\n")
                    subprocess.run(["git", "-C", root, "add", relative], check=True)

                    result = self.run_scanner(root)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("forbidden tracked paths", result.stderr)
                finally:
                    temporary.cleanup()

    def test_scanner_rejects_credential_content(self):
        temporary, root = self.make_repo()
        self.addCleanup(temporary.cleanup)
        key_prefix = "s" + "k-proj-"
        (root / "config.txt").write_text(
            "OPENAI_API_KEY=" + key_prefix + "abcdefghijklmnopqrstuvwxyz012345\n"
        )
        subprocess.run(["git", "-C", root, "add", "config.txt"], check=True)

        result = self.run_scanner(root)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("possible credential content", result.stderr)

    def test_claude_skill_links_resolve_to_canonical_skills(self):
        canonical = ROOT / ".agents" / "skills"
        claude = ROOT / ".claude" / "skills"
        expected = {
            "benchmark-onboarding",
            "harness-benchmark",
            "harness-telemetry",
            "benchmark-telemetry-report",
        }
        self.assertEqual({path.name for path in canonical.iterdir()}, expected)
        self.assertEqual({path.name for path in claude.iterdir()}, expected)
        for name in expected:
            self.assertTrue((claude / name).is_symlink())
            self.assertEqual((claude / name).resolve(), (canonical / name).resolve())

    def test_runner_and_skills_are_machine_portable(self):
        paths = [
            ROOT / "run-bench.sh",
            *(ROOT / ".agents" / "skills").glob("*/SKILL.md"),
        ]
        for path in paths:
            with self.subTest(path=path):
                content = path.read_text()
                self.assertNotIn("/mnt/bench", content)
                self.assertNotIn("/home/someotherguy", content)
                self.assertNotIn("source secrets.env", content)


if __name__ == "__main__":
    unittest.main()
