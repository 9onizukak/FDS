"""Offline checks of executable update trust, handoff, and busy-job deferral."""
import hashlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "unz"))
import software_update as updater
from update_ui import UpdateController

PAYLOAD = b"test installer, never executed"


def metadata(version="1.0.5"):
    return {"tag_name": f"v{version}", "draft": False, "prerelease": False, "assets": [{
        "name": f"FDH-Setup-{version}.exe", "state": "uploaded", "size": len(PAYLOAD),
        "digest": "sha256:" + hashlib.sha256(PAYLOAD).hexdigest(),
        "browser_download_url": f"https://github.com/{updater.REPOSITORY}/releases/download/v{version}/FDH-Setup-{version}.exe",
    }]}


class UpdateTest(unittest.TestCase):
    def test_versions_are_numeric_and_do_not_downgrade(self):
        self.assertIsNotNone(updater.release_from_metadata(metadata("1.0.10"), "1.0.9"))
        self.assertIsNone(updater.release_from_metadata(metadata("1.0.9"), "1.0.10"))
        self.assertIsNone(updater.release_from_metadata(metadata("1.0.5"), "1.0.5"))
        for value in ("v1.0.5-beta", "../1.0.5", "latest", "1.2", None):
            with self.assertRaises(updater.UpdateError):
                updater.version_tuple(value)

    def test_drafts_and_prereleases_are_ignored(self):
        for key in ("draft", "prerelease"):
            release = metadata()
            release[key] = True
            self.assertIsNone(updater.release_from_metadata(release, "1.0.4"))

    def test_missing_installer_digest_and_untrusted_urls_are_rejected(self):
        for field, value in (("digest", None), ("size", 0), ("size", True),
                             ("browser_download_url", "https://evil.test/setup.exe"),
                             ("browser_download_url", "http://github.com/installer.exe"),
                             ("name", "FDH-Setup-1.0.4.exe"), ("state", "new")):
            release = metadata()
            release["assets"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(updater.UpdateError):
                updater.release_from_metadata(release, "1.0.4")

    def download(self, payload, directory, release=None):
        response = io.BytesIO(payload)
        response.geturl = lambda: "https://release-assets.githubusercontent.com/test"
        release = release or updater.release_from_metadata(metadata(), "1.0.4")
        with patch.object(updater.urllib.request, "urlopen", return_value=response):
            return updater.download_installer(release, directory)

    def test_verified_download_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.download(PAYLOAD, directory)
            self.assertEqual(path.read_bytes(), PAYLOAD)
            self.assertEqual([file.name for file in Path(directory).iterdir()], [path.name])

    def test_partial_tampered_and_oversized_downloads_are_removed(self):
        for payload in (PAYLOAD[:-1], b"X" * len(PAYLOAD), PAYLOAD + b"X"):
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(updater.UpdateError):
                    self.download(payload, directory)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_failed_download_preserves_existing_installer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "FDH-Setup-1.0.5.exe"
            path.write_bytes(PAYLOAD)
            with self.assertRaises(updater.UpdateError):
                self.download(b"bad", directory)
            self.assertEqual(path.read_bytes(), PAYLOAD)

    def test_no_release_and_network_errors_are_readable(self):
        error = updater.urllib.error.HTTPError(updater.LATEST_URL, 404, "Not Found", {}, None)
        with patch.object(updater.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(updater.UpdateError, "No public release"):
                updater.check_latest()
        with patch.object(updater.urllib.request, "urlopen", side_effect=TimeoutError("offline")):
            with self.assertRaisesRegex(updater.UpdateError, "Cannot check GitHub"):
                updater.check_latest()

    def test_helper_waits_for_exit_and_preserves_install_location(self):
        with tempfile.TemporaryDirectory(prefix="FDH user's ") as directory:
            path = Path(directory) / "setup.exe"
            path.write_bytes(PAYLOAD)
            def helper_started(*args, **kwargs):
                (Path(directory) / "install-update.started").write_text("TEST_ONLY")
                return MagicMock()
            with patch.object(updater, "can_install", return_value=True), \
                 patch.object(updater.subprocess, "Popen", side_effect=helper_started) as process:
                updater.start_installer(path, directory)
            script = (Path(directory) / "install-update.ps1").read_text(encoding="utf-8-sig")
            self.assertIn("WaitForExit(120000)", script)
            self.assertIn("/NOCLOSEAPPLICATIONS", script)
            self.assertIn("/DIR=", script)
            self.assertIn("user''s", script)
            self.assertLess(script.index("ExitCode -ne 0"), script.index("Start-Process -FilePath $appExe"))
            self.assertIn("-File", process.call_args.args[0])
            self.assertEqual(process.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_helper_startup_failure_keeps_app_from_exiting(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "setup.exe"
            path.write_bytes(PAYLOAD)
            process = MagicMock()
            process.poll.return_value = 1
            with patch.object(updater, "can_install", return_value=True), \
                 patch.object(updater.subprocess, "Popen", return_value=process):
                with self.assertRaisesRegex(updater.UpdateError, "helper did not start"):
                    updater.start_installer(path, directory)

    def test_bundled_paths_are_not_inherited_by_system_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "_internal"
            import os
            environment = {"PATH": os.pathsep.join((str(bundle), str(bundle / "bin"), str(Path(directory) / "system")))}
            with patch.object(updater.sys, "_MEIPASS", str(bundle), create=True), \
                 patch.dict(updater.os.environ, environment):
                result = updater._external_environment()
            self.assertEqual(result["PATH"], str(Path(directory) / "system"))
            self.assertEqual(result["PYINSTALLER_RESET_ENVIRONMENT"], "1")


class UpdateUITest(unittest.TestCase):
    def setUp(self):
        self.controller = UpdateController.__new__(UpdateController)
        self.controller.root = MagicMock()
        self.controller.app = SimpleNamespace(_api_busy=MagicMock(return_value=False), updating=False)
        self.controller.automatic = MagicMock()
        self.controller.automatic.get.return_value = True
        self.controller.status = MagicMock()
        self.controller.button = MagicMock()
        self.controller.pending = (Path("test-installer.exe"), False)
        self.controller.active = True

    def test_active_hospital_jobs_defer_installation(self):
        self.controller.app._api_busy.return_value = True
        with patch.object(updater, "start_installer") as start:
            self.assertFalse(self.controller.install_when_idle())
            start.assert_not_called()
            self.assertIsNotNone(self.controller.pending)
            self.controller.app._api_busy.return_value = False
            self.assertTrue(self.controller.install_when_idle())
            start.assert_called_once()
            self.controller.root.destroy.assert_called_once()

    def test_disabling_auto_update_cancels_pending_install(self):
        self.controller.automatic.get.return_value = False
        with patch.object(updater, "start_installer") as start:
            self.assertFalse(self.controller.install_when_idle())
            start.assert_not_called()
            self.assertIsNone(self.controller.pending)

    def test_failed_handoff_keeps_app_open(self):
        with patch.object(updater, "start_installer", side_effect=OSError("test failure")), \
             patch("update_ui.messagebox.showerror") as error:
            self.assertFalse(self.controller.install_when_idle())
            self.controller.root.destroy.assert_not_called()
            self.assertFalse(self.controller.app.updating)
            self.assertFalse(self.controller.active)
            error.assert_called_once()

    def test_open_settings_defer_install(self):
        self.controller.app.settings_window = MagicMock()
        with patch.object(updater, "start_installer") as start:
            self.assertFalse(self.controller.install_when_idle())
            start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
