"""Opt-in Windows update integration test; never publishes a GitHub release.

Builds two isolated packaged apps using the real GUI/updater and an Inno Setup
installer with no shortcuts or uninstall registration. Only GitHub HTTP responses
are simulated. Configuration, history, and all program files stay in .update-test.

Run with the build environment: python tests/run_update_integration.py
"""
import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
ENTRY = r'''
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import tkinter as tk
import traceback

TEST_VERSION = "__TEST_VERSION__"
test_root = Path(os.environ["FDH_UPDATE_TEST_ROOT"]).resolve()
local_data = Path(os.environ["LOCALAPPDATA"]).resolve()
if not local_data.is_relative_to(test_root):
    raise RuntimeError("Integration data must stay within the isolated test directory")

def record(event, **values):
    with (test_root / "events.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(dict(event=event, version=TEST_VERSION, pid=os.getpid(), **values)) + "\n")

def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

try:
    import app_version
    app_version.APP_VERSION = TEST_VERSION
    import software_update as updater
    from runtime_paths import DATA_DIR, ENV_PATH, HISTORY_PATH
    from send_gui import App

    installer = test_root / "packages" / "FDH-Setup-1.0.5.exe"
    installer_url = "https://github.com/9onizukak/FDS/releases/download/v1.0.5/FDH-Setup-1.0.5.exe"
    metadata = {"tag_name": "v1.0.5", "draft": False, "prerelease": False, "assets": [{
        "name": "FDH-Setup-1.0.5.exe", "state": "uploaded",
        "browser_download_url": installer_url, "size": installer.stat().st_size,
        "digest": "sha256:" + fingerprint(installer),
    }]}

    class FixtureResponse:
        def __init__(self, content, url):
            self.stream = io.BytesIO(content)
            self.url = url
        def read(self, size=-1):
            return self.stream.read(size)
        def geturl(self):
            return self.url
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()

    def fixture_urlopen(request, timeout):
        if request.full_url == updater.LATEST_URL:
            record("github_version_check", timeout=timeout)
            return FixtureResponse(json.dumps(metadata).encode(), request.full_url)
        if request.full_url == installer_url:
            record("installer_download", bytes=installer.stat().st_size)
            return FixtureResponse(installer.read_bytes(), "https://release-assets.githubusercontent.com/test")
        raise RuntimeError("Unexpected external request blocked by isolated integration test")

    updater.urllib.request.urlopen = fixture_urlopen
    original_start = updater.start_installer
    def start_installer(path, directory):
        record("real_installer_handoff", installer=str(path), verified_sha256=fingerprint(path))
        return original_start(path, directory)
    updater.start_installer = start_installer

    root = tk.Tk()
    root.withdraw()
    app = App(root)
    record("app_started", title=root.title(), executable=sys.executable)
    expected = json.loads((test_root / "expected.json").read_text(encoding="utf-8"))

    if TEST_VERSION == "1.0.4":
        app.searching = True  # Simulate an active hospital job without accessing a DB.
        ready_since = None
        def wait_for_verified_download():
            global ready_since
            if app.updater.pending is not None:
                if ready_since is None:
                    ready_since = time.monotonic()
                if time.monotonic() - ready_since >= 0.75:
                    assert not app.updating, "Updater started installation during an active job"
                    assert app.searching, "Test job flag was unexpectedly cleared"
                    record("busy_job_deferral_verified")
                    app.searching = False
                    record("hospital_job_finished")
                    return
            root.after(100, wait_for_verified_download)
        root.after(100, wait_for_verified_download)
        def timeout():
            (test_root / "failure.txt").write_text("Old app did not hand off in time: " + app.updater.status.get(), encoding="utf-8")
            root.destroy()
        root.after(30000, timeout)
    else:
        def verify_restarted_app():
            checks = {
                "installed_version": app_version.APP_VERSION == "1.0.5",
                "title_shows_new_version": "FDH 1.0.5" in root.title(),
                "same_install_directory": Path(sys.executable).resolve().parent == Path(expected["install_directory"]),
                "config_preserved": fingerprint(ENV_PATH) == expected["config_sha256"],
                "history_preserved": fingerprint(HISTORY_PATH) == expected["history_sha256"],
                "no_repeat_update": updater.check_latest() is None,
                "auto_update_still_enabled": app.updater.automatic.get(),
                "program_resources_replaced": (Path(__file__).resolve().parent / "test-version.txt").read_text() == "1.0.5",
            }
            events = [json.loads(line) for line in (test_root / "events.jsonl").read_text().splitlines()]
            checks["active_job_was_respected"] = any(event["event"] == "busy_job_deferral_verified" for event in events)
            checks["process_restarted"] = any(event["event"] == "app_started" and event["version"] == "1.0.4" and event["pid"] != os.getpid() for event in events)
            result = dict(passed=all(checks.values()), checks=checks, tested_versions=["1.0.4", "1.0.5"],
                          github_network="simulated", installer="real Inno Setup", app="real packaged Tkinter GUI",
                          actual_data_directory=str(DATA_DIR))
            (test_root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            record("restarted_app_verified", passed=result["passed"])
            root.destroy()
        root.after(500, verify_restarted_app)
    root.mainloop()
    record("app_exited")
except Exception:
    (test_root / "failure.txt").write_text(traceback.format_exc(), encoding="utf-8")
    raise
'''


def main():
    if sys.platform != "win32":
        raise SystemExit("This integration test requires Windows and Inno Setup")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    test_root = (ROOT / ".update-test" / stamp).resolve()
    if not test_root.is_relative_to(ROOT):
        raise SystemExit("Test directory must stay in the project")
    test_root.mkdir(parents=True)
    compiler = ROOT / "build-tools/InnoSetup/ISCC.exe"
    if not compiler.exists():
        compiler = Path(os.environ["ProgramFiles(x86)"]) / "Inno Setup 6/ISCC.exe"
    if not compiler.exists():
        raise SystemExit("Inno Setup compiler not found")
    template = test_root / ".env.example"
    template.write_text("FDH_USER=TEST_ONLY\nFDH_HOSPITAL_CODE=00000\nFDH_HOSPITAL_NAME=Update Integration Test\n"
                        "FDH_PASSWORD=\nFDH_PASSWORD_HASH=\nHOSXP_HOST=\nHOSXP_PORT=3306\nHOSXP_DB=\n"
                        "HOSXP_USER=\nHOSXP_PASSWORD=\nHOSXP_CHARSET=tis620\nFDH_ENV=UAT\n", encoding="utf-8")

    def command(arguments, name):
        print(name, flush=True)
        log = test_root / f"{name}.log"
        with log.open("w", encoding="utf-8") as output:
            completed = subprocess.run([str(arg) for arg in arguments], cwd=ROOT, stdout=output,
                                       stderr=subprocess.STDOUT, timeout=180)
        if completed.returncode:
            raise RuntimeError(f"{name} failed ({completed.returncode}); see {log}")

    for version in ("1.0.4", "1.0.5"):
        stage = test_root / version
        stage.mkdir()
        entry = stage / "entry.py"
        entry.write_text(ENTRY.replace("__TEST_VERSION__", version), encoding="utf-8")
        marker = stage / "test-version.txt"
        marker.write_text(version)
        command([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--onedir",
                 "--name", "FDH", "--paths", ROOT / "unz", "--distpath", stage / "dist",
                 "--workpath", stage / "build", "--specpath", stage,
                 "--add-data", f"{ROOT / 'unz/assets/moph-logo.png'};assets",
                 "--add-data", f"{template};.", "--add-data", f"{marker};.",
                 "--hidden-import", "pymysql", "--collect-all", "cryptography", entry], f"build-{version}")

    packages = test_root / "packages"
    packages.mkdir()
    install_dir = test_root / "installed app"
    shutil.copytree(test_root / "1.0.4/dist/FDH", install_dir)
    spec = test_root / "test-installer.iss"
    spec.write_text(f'''[Setup]
AppId=FDH-Isolated-Update-Test-{stamp}
AppName=FDH Isolated Update Test
AppVersion=1.0.5
DefaultDirName={install_dir}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Uninstallable=no
CreateUninstallRegKey=no
DisableProgramGroupPage=yes
OutputDir={packages}
OutputBaseFilename=FDH-Setup-1.0.5
Compression=lzma2
SolidCompression=yes
CloseApplications=yes
SetupLogging=yes

[Files]
Source: "{test_root / '1.0.5/dist/FDH'}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs
''', encoding="utf-8-sig")
    command([compiler, "/Q", spec], "build-test-installer")

    data_dir = test_root / "local-app-data/FDH"
    data_dir.mkdir(parents=True)
    shutil.copyfile(template, data_dir / ".env")
    (data_dir / "send_history.jsonl").write_text('{"vn":"TEST_ONLY","status":"submitted","environment":"UAT"}\n', encoding="utf-8")
    (data_dir / "update-settings.json").write_text('{"auto_update":true}', encoding="utf-8")
    import hashlib
    expected = dict(install_directory=str(install_dir),
                    config_sha256=hashlib.sha256((data_dir / ".env").read_bytes()).hexdigest(),
                    history_sha256=hashlib.sha256((data_dir / "send_history.jsonl").read_bytes()).hexdigest())
    (test_root / "expected.json").write_text(json.dumps(expected), encoding="utf-8")
    environment = dict(os.environ, FDH_UPDATE_TEST_ROOT=str(test_root), LOCALAPPDATA=str(test_root / "local-app-data"))
    print("Running automatic 1.0.4 -> 1.0.5 installer/restart test", flush=True)
    old_app = subprocess.Popen([str(install_dir / "FDH.exe")], cwd=install_dir, env=environment,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic() + 90
    result_path = test_root / "result.json"
    failure = test_root / "failure.txt"
    while time.monotonic() < deadline:
        if failure.exists():
            raise RuntimeError(failure.read_text(encoding="utf-8"))
        if result_path.exists():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            old_app.wait(timeout=5)
            print(json.dumps(result, indent=2), flush=True)
            print(f"Report: {result_path}", flush=True)
            if not result["passed"]:
                raise SystemExit(1)
            return
        error_log = data_dir / "updates/install-update.log.error"
        if error_log.exists():
            raise RuntimeError(error_log.read_text(encoding="utf-8-sig"))
        time.sleep(0.2)
    raise RuntimeError(f"Update timed out; inspect {test_root}")


if __name__ == "__main__":
    main()
