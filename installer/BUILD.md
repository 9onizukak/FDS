# Windows build

Requires Windows x64, Python 3.11, and Inno Setup 6.7.3.

From the project directory:

```powershell
python -m venv .build-venv
.\.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

Install Inno Setup's compiler in `build-tools\InnoSetup`, then run:

```powershell
.\build-windows.ps1
```

The application version lives in `unz/app_version.py`. Outputs for 1.0.4:
`dist\FDH\FDH.exe`, `release\FDH-Setup-1.0.4.exe`,
`release\FDH-Portable-1.0.4.zip`, and `release\SHA256SUMS-1.0.4.txt`.
The build passes that same version to Inno Setup and uses it for package names.

## GitHub releases and automatic updates

Updates use the public repository `9onizukak/FDS`. The packaged Windows app
checks the latest stable GitHub Release at startup and every hour while automatic
updates are enabled (the default). The bottom bar displays the installed version,
offers a manual check, and lets users disable automatic updates. That preference
is saved in `%LOCALAPPDATA%\FDH\update-settings.json`.

The release must have a stable tag such as `v1.0.5` and an uploaded installer
named exactly `FDH-Setup-1.0.5.exe`. Its GitHub asset metadata must include a
SHA-256 digest. Drafts, prereleases, equal versions, and older versions are not
installed. Network failures leave the current app usable and retry on the next
hourly check; manual failures show an error. Source checkouts only check manually
and do not install executable updates.

Downloads are staged in `%LOCALAPPDATA%\FDH\updates`, checked against GitHub's
published size and SHA-256 digest, and installed after active search/send/check
jobs finish and the API settings window closes. A detached helper waits for the
app process to exit, runs Inno Setup silently in the current application directory,
and restarts FDH after setup succeeds. Installation failures show a message and
leave a log in that updates directory. Settings and history in the separate user
data directory are preserved. Portable apps use the same installer in their
existing folder; this registers the folder as an installed app. The folder must
be writable by the current user.

To publish the next version:

1. Change `APP_VERSION` in `unz/app_version.py`, for example to `1.0.5`.
2. Update the version shown in `release/README-TH.txt`.
3. Commit and push the source and `.github/workflows/release.yml` to `9onizukak/FDS`.
4. Push a matching tag, for example `git tag v1.0.5` then `git push origin v1.0.5`.

The workflow tests, builds, and publishes the installer, portable archive, and
checksums. A source commit alone does not trigger an executable update. If a
workflow build fails, fix the build before publishing the release. Alternatively,
build locally and attach the exact matching installer to a stable GitHub Release.
Existing 1.0.3 installations need a one-time manual installation of 1.0.4 to gain
the updater.

## Update integration test

Run `.\.build-venv\Scripts\python.exe tests/run_update_integration.py` on Windows
with Inno Setup available. This opt-in test builds isolated 1.0.4 and 1.0.5 app
fixtures using the real GUI and updater, simulates only GitHub HTTP responses,
and runs an actual Inno installer and automatic process restart. It verifies
version display, resource replacement, active-job deferral, data preservation,
and that the updated app does not reinstall the same version. All test data and
logs stay under `.update-test`; the fixture installer creates no shortcuts or
uninstall registration. No release is published by the test.

The packaged updater clears the bundled Windows DLL search path before launching
PowerShell, resets PyInstaller environment state for the restarted app, and waits
for a helper startup marker before closing FDH. Helper startup diagnostics are
saved in `updates/install-helper.log`.

The build includes `.env.example` with hospital connection defaults and blank password fields. Existing `.env`, visit payloads, and patient history are excluded. Installed and portable apps store configuration and history in `%LOCALAPPDATA%\FDH`. New configuration variables are added on startup without replacing existing values. Uninstall leaves this directory available for reinstall.

The package is unsigned. Offline API routing, token URL, configuration persistence, history separation, search responsiveness, and UI startup checks were performed; live hospital database and FDH submission were not exercised during packaging.

API modes use `FDH_ENV=UAT` or `PRODUCTION`, `FDH_UAT_BASE_URL`, `FDH_PRODUCTION_BASE_URL`, and `FDH_TOKEN_URL`. UAT is the default. Production's host follows the [official FDH documentation](https://r8way.moph.go.th/r8wayNewadmin/page/upload_file/20250424024001.pdf). A domain-only Base URL uses the project's `/fdh_api/v1/dataset/` API structure. An explicit Base URL path is used directly as the dataset base, allowing other routes supplied by FDH. Each send/check job holds one immutable settings snapshot. History without an environment tag belongs to UAT.

Unauthenticated GET checks during this build returned 401 for UAT's dataset import and 404 (`default backend - 404`) for the documented Production host. The user chose to retain the documented host as an editable default. Production submission has not been verified; enter an updated full dataset Base URL when FDH provides it.
