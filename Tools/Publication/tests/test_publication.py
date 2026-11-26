# SPDX-License-Identifier: GPL-3.0-only
"""Publication gates use synthetic fixtures; no owned game files are needed."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_repository import content_issues, current_report, history_report, path_issues
from export_source import export_source


class PublicationTests(unittest.TestCase):
    def test_binary_and_original_payload_extensions_are_rejected(self):
        for path in ["NativeRenderer/game.exe", "NativeRenderer/music.bin", "wrappers/screamer/artwork/loading.png",
                     "NativeRenderer/build-release/Game.app/Contents/Info.plist", "Archives/checkpoint.zip"]:
            with self.subTest(path=path):
                self.assertTrue(path_issues(path))
        self.assertIn("binary-content", content_issues(b"hello\0world"))

    def test_text_can_still_contain_a_payload_or_secret(self):
        self.assertIn("embedded-payload-review-required", content_issues(('"' + 'A' * 2048 + '"').encode()))
        token = ("gh" + "p_" + "a" * 36).encode()
        self.assertIn("github-token", content_issues(token))
        self.assertIn("personal-absolute-path", content_issues(("/Users/" + "example/private/file").encode()))
        self.assertFalse(content_issues(b'"small_config_base64": "QzpcCUQ6CUM6XAlj"'))

    def test_path_and_symlink_escape(self):
        for path in ["../README.md", "/README.md", "Tools/../../secret.py", "Tools\\secret.py"]:
            self.assertIn("unsafe-path", path_issues(path))
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp)
            (root / "Tools/link.py").symlink_to(root / "README.md")
            report = current_report(root)
            self.assertFalse(report["passed"])
            self.assertIn("symlink-not-allowed", report["findings"][0]["issues"])

    def repo(self, tmp):
        root = Path(tmp) / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
        (root / "README.md").write_text("Synthetic source fixture.\n")
        (root / "Tools").mkdir()
        (root / "Tools/tool.py").write_text("print('source')\n")
        (root / ".gitignore").write_text("*.app/\nNativeRenderer/build-*/\n")
        self.commit(root)
        return root

    def commit(self, root):
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "Fixture"], check=True)

    def test_deleted_game_binary_in_history_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp)
            game = root / "Tools/original.exe"
            game.write_bytes(b"MZ\0synthetic fixture")
            self.commit(root)
            game.unlink()
            self.commit(root)
            self.assertTrue(current_report(root)["passed"])
            history = history_report(root)
            self.assertFalse(history["passed"])
            self.assertEqual(history["findings"][0]["path"], "Tools/original.exe")

    def test_historical_rename_of_same_blob_is_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp)
            (root / "Tools/tool.py").rename(root / "Tools/original.exe")
            self.commit(root)
            (root / "Tools/original.exe").unlink()
            self.commit(root)
            report = history_report(root)
            self.assertFalse(report["passed"])
            self.assertEqual(report["findings"][0]["path"], "Tools/original.exe")

    def test_historical_machine_paths_are_reported_without_forcing_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp)
            (root / "README.md").write_text("Local path " + "/Users/" + "example/private/file")
            self.commit(root)
            (root / "README.md").write_text("Portable path <owned-game>/file")
            self.commit(root)
            history = history_report(root)
            self.assertTrue(history["passed"])
            self.assertEqual(history["warnings"][0]["issue"], "historical-personal-path")

    def test_export_contains_current_source_new_files_and_hashes_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp)
            ignored = root / "Private.app"
            ignored.mkdir()
            (ignored / "original.exe").write_bytes(b"MZ\0original")
            (root / "Tools/new.py").write_text("# new source\n")
            output = Path(tmp) / "source.tar.gz"
            result = export_source(root, output)
            self.assertTrue(result["working_tree_changes"])
            with tarfile.open(output) as bundle:
                names = bundle.getnames()
                self.assertIn("ScreamerTrilogy/Tools/new.py", names)
                self.assertFalse(any(".git/" in name or ".app/" in name for name in names))
                manifest = json.load(bundle.extractfile("ScreamerTrilogy/SOURCE-MANIFEST.json"))
                for name, digest in manifest["files"].items():
                    self.assertEqual(hashlib.sha256(bundle.extractfile("ScreamerTrilogy/" + name).read()).hexdigest(), digest)
            with self.assertRaises(FileExistsError):
                export_source(root, output)

    def test_exported_snapshot_passes_new_repository_checks_and_reexports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp)
            output = Path(tmp) / "source.tar.gz"
            export_source(root, output)
            unpacked = Path(tmp) / "unpacked"
            with tarfile.open(output) as bundle:
                for member in bundle.getmembers():
                    self.assertTrue(member.isfile())
                    target = unpacked / member.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.extractfile(member).read())
            fresh = unpacked / "ScreamerTrilogy"
            subprocess.run(["git", "init", "-q", str(fresh)], check=True)
            subprocess.run(["git", "-C", str(fresh), "config", "user.name", "Fixture"], check=True)
            subprocess.run(["git", "-C", str(fresh), "config", "user.email", "fixture@example.invalid"], check=True)
            self.commit(fresh)
            self.assertTrue(current_report(fresh)["passed"])
            self.assertTrue(history_report(fresh)["passed"])
            second = Path(tmp) / "second-source.tar.gz"
            export_source(fresh, second)
            with tarfile.open(second) as bundle:
                names = bundle.getnames()
                self.assertEqual(len(names), len(set(names)))
                manifest = json.load(bundle.extractfile("ScreamerTrilogy/SOURCE-MANIFEST.json"))
                self.assertNotIn("SOURCE-MANIFEST.json", manifest["files"])
                for name, digest in manifest["files"].items():
                    self.assertEqual(hashlib.sha256(bundle.extractfile("ScreamerTrilogy/" + name).read()).hexdigest(), digest)

    def test_export_refuses_nonignored_game_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.repo(tmp)
            (root / "Tools/original.exe").write_bytes(b"MZ\0fixture")
            output = Path(tmp) / "source.tar.gz"
            with self.assertRaises(ValueError):
                export_source(root, output)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
