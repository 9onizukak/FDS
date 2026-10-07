"""GitHub release checks and verified Windows installer handoff.

Only public stable releases from the configured repository are accepted.
The installer updates program files; runtime_paths keeps user data elsewhere.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from app_version import APP_VERSION

REPOSITORY = "9onizukak/FDS"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
MAX_INSTALLER_SIZE = 512 * 1024 * 1024


class UpdateError(Exception):
    """An update could not be safely checked, downloaded, or started."""


def version_tuple(value):
    """Accept stable three-part version tags, with an optional v prefix."""
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise UpdateError("Release tag must use vMAJOR.MINOR.PATCH (stable versions only)")
    return tuple(int(part) for part in value.removeprefix("v").split("."))


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int
    sha256: str


def release_from_metadata(metadata, current=APP_VERSION):
    if not isinstance(metadata, dict):
        raise UpdateError("Invalid GitHub release response")
    if metadata.get("draft") or metadata.get("prerelease"):
        return None
    tag = metadata.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(current):
        return None
    version = tag.removeprefix("v")
    filename = f"FDH-Setup-{version}.exe"
    for asset in metadata.get("assets", []):
        if asset.get("name") != filename or asset.get("state") != "uploaded":
            continue
        url = asset.get("browser_download_url", "")
        parsed = urllib.parse.urlsplit(url)
        expected_path = f"/{REPOSITORY}/releases/download/{tag}/{filename}"
        if (parsed.scheme != "https" or parsed.netloc != "github.com"
                or urllib.parse.unquote(parsed.path) != expected_path
                or parsed.query or parsed.fragment):
            raise UpdateError("Installer URL does not belong to the configured GitHub release")
        digest = asset.get("digest", "") or ""
        if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
            raise UpdateError("GitHub release installer is missing its SHA-256 digest")
        size = asset.get("size", 0)
        if type(size) is not int or not 0 < size <= MAX_INSTALLER_SIZE:
            raise UpdateError("Invalid installer size")
        return Release(version, url, size, digest.split(":", 1)[1].lower())
    raise UpdateError(f"Release {tag} has no uploaded {filename} installer")


def _request(url, accept="application/vnd.github+json"):
    return urllib.request.Request(url, headers={
        "User-Agent": f"FDH/{APP_VERSION}", "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    })


def check_latest(current=APP_VERSION):
    try:
        with urllib.request.urlopen(_request(LATEST_URL), timeout=15) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise UpdateError("GitHub release response is too large")
        return release_from_metadata(json.loads(data), current)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise UpdateError("No public release is available yet") from error
        raise UpdateError(f"GitHub update check failed (HTTP {error.code})") from error
    except (OSError, ValueError) as error:
        raise UpdateError(f"Cannot check GitHub updates: {error}") from error


def download_installer(release, directory):
    """Publish a complete verified installer atomically; discard partial files."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"FDH-Setup-{release.version}.exe"
    digest = hashlib.sha256()
    total = 0
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as output:
            temporary = Path(output.name)
            with urllib.request.urlopen(_request(release.url, "application/octet-stream"), timeout=30) as response:
                if urllib.parse.urlsplit(response.geturl()).scheme != "https":
                    raise UpdateError("Installer download must use HTTPS")
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > release.size:
                        raise UpdateError("Installer is larger than its published size")
                    digest.update(chunk)
                    output.write(chunk)
        if total != release.size or digest.hexdigest() != release.sha256:
            raise UpdateError("Installer integrity check failed; update was not installed")
        temporary.replace(destination)
        return destination
    except (OSError, ValueError) as error:
        raise UpdateError(f"Cannot download update: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def can_install():
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def _ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def start_installer(installer, directory):
    """Start a detached helper; caller exits only after successful handoff.

    Wait for our PID before touching loaded DLLs, install into the current
    installed/portable directory, then restart only after a successful setup.
    """
    if not can_install():
        raise UpdateError("Automatic installation requires the packaged Windows app")
    installer = Path(installer).resolve(strict=True)
    directory = Path(directory).resolve()
    executable = Path(sys.executable).resolve()
    script = directory / "install-update.ps1"
    log = directory / "install-update.log"
    script.write_text(f"""$ErrorActionPreference = 'Stop'
$installer = {_ps_literal(installer)}
$appExe = {_ps_literal(executable)}
$appDir = {_ps_literal(executable.parent)}
$log = {_ps_literal(log)}
try {{
    $oldProcess = Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue
    if ($oldProcess -and -not $oldProcess.WaitForExit(120000)) {{
        throw 'FDH did not close in time. Update cancelled.'
    }}
    $arguments = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', ('/DIR="' + $appDir + '"'), ('/LOG="' + $log + '"'))
    $setup = Start-Process -FilePath $installer -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru
    if ($setup.ExitCode -ne 0) {{ throw ('Installer failed with exit code ' + $setup.ExitCode) }}
    Remove-Item -LiteralPath $installer -Force
    Start-Process -FilePath $appExe -WorkingDirectory $appDir
}} catch {{
    $_.Exception.Message | Out-File -LiteralPath ($log + '.error') -Encoding utf8
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(('FDH update failed: ' + $_.Exception.Message + "`nLog: " + $log), 'FDH Update') | Out-Null
}}
""", encoding="utf-8-sig")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-WindowStyle", "Hidden", "-File", str(script)],
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as error:
        raise UpdateError(f"Cannot start update installer: {error}") from error
