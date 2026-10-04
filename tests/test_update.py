"""Exercise updater selection without network access: python3 -m unittest discover -s tests."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def release(version, complete=True):
    return {
        "tag_name": "v" + version,
        "prerelease": "-" in version,
        "body": "Release notes for " + version,
        "html_url": "https://example.com/" + version,
        "assets": [
            {"name": f"T3-Code-{version}-{suffix}", "digest": "sha256:" + "ab" * 32}
            for suffix in (["x86_64.AppImage", "arm64.zip"] if complete else ["arm64.zip"])
        ],
    }


class UpdateTest(unittest.TestCase):
    def run_update(self, releases, fail_api=False):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "releases.json").write_text(json.dumps(releases))
            curl = work / "curl"
            curl.write_text('''#!/usr/bin/env python3
import os, pathlib, sys
root = pathlib.Path(os.environ["FIXTURES"])
if os.environ.get("FAIL_API") == "1":
    sys.exit(22)
if sys.argv[-1] != "https://api.github.com/repos/pingdotgg/t3code/releases?per_page=100":
    sys.exit(22)
print((root / "releases.json").read_text())
''')
            curl.chmod(0o755)
            result = subprocess.run(["bash", str(ROOT / "update.sh")], env={
                **os.environ, "PATH": str(work) + os.pathsep + os.environ["PATH"],
                "FIXTURES": str(work), "RELEASE_NOTES_DIR": str(work / "notes"),
                "FAIL_API": "1" if fail_api else "0",
            }, text=True, capture_output=True)
            notes = {path.name: path.read_text() for path in (work / "notes").glob("*")}
            return result, notes

    def test_selects_only_stable_and_nightly_and_writes_notes(self):
        result, notes = self.run_update([
            release("1.0.1-preview.20260923.4"),
            release("1.0.1-nightly.20260923.2"),
            release("1.0.0"),
            release("1.0.1-nightly.20260923.1"),
            release("0.9.0"),
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('version = "1.0.0";', result.stdout)
        self.assertIn('version = "1.0.1-nightly.20260923.2";', result.stdout)
        self.assertNotIn("preview", result.stdout)
        self.assertNotIn("nightly.20260923.1", result.stdout)
        self.assertNotIn('version = "0.9.0";', result.stdout)
        self.assertEqual(
            [line for line in result.stdout.splitlines() if line.startswith("  ") and not line.startswith("    ")],
            ["  stable = {", "  };", "  nightly = {", "  };"],
        )
        self.assertEqual(notes, {
            "stable.md": "Release notes for 1.0.0\n",
            "stable.url": "https://example.com/1.0.0\n",
            "nightly.md": "Release notes for 1.0.1-nightly.20260923.2\n",
            "nightly.url": "https://example.com/1.0.1-nightly.20260923.2\n",
        })

    def test_skips_incomplete_releases_and_missing_digests(self):
        for version in ("1.0.1", "1.0.1-nightly.20260923.2"):
            for invalid in ("missing_asset", "missing_digest"):
                with self.subTest(version=version, invalid=invalid):
                    candidate = release(version, complete=invalid != "missing_asset")
                    if invalid == "missing_digest":
                        candidate["assets"][0]["digest"] = None
                    result, _ = self.run_update([
                        candidate, release("1.0.0"), release("1.0.1-nightly.20260923.1")
                    ])
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn(f'version = "{version}";', result.stdout)
                    self.assertIn('version = "1.0.0";', result.stdout)
                    self.assertIn('version = "1.0.1-nightly.20260923.1";', result.stdout)
                    self.assertIn("is not ready", result.stderr)

    def test_missing_channel_aborts_without_emitting_metadata(self):
        for version in ("1.0.0", "1.0.1-nightly.20260923.1"):
            with self.subTest(version=version):
                result, notes = self.run_update([release(version)])
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertEqual(notes, {})

    def test_api_failure_aborts_without_emitting_metadata(self):
        result, _ = self.run_update([], fail_api=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
