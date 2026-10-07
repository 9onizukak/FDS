$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$buildPython = Join-Path $PSScriptRoot '.build-venv\Scripts\python.exe'
$appVersion = (& $buildPython -c "import sys; sys.path.insert(0, 'unz'); from app_version import APP_VERSION; print(APP_VERSION)").Trim()
if ($LASTEXITCODE -ne 0 -or $appVersion -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid application version' }
& $buildPython scripts/release_notes.py --version $appVersion --output "release/RELEASE-NOTES-$appVersion.md"
if ($LASTEXITCODE -ne 0) { throw 'Release notes generation failed' }
& $buildPython -m PyInstaller --noconfirm --clean --windowed --onedir --name FDH --icon unz/assets/moph-logo.ico --add-data 'unz/assets/moph-logo.png;assets' --add-data 'unz/.env.example;.' --hidden-import pymysql --collect-all cryptography unz/windows_launcher.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
Copy-Item -LiteralPath release/README-TH.txt -Destination dist/FDH/README-TH.txt
Copy-Item -LiteralPath CHANGELOG.md -Destination dist/FDH/CHANGELOG.md
$compiler = Join-Path $PSScriptRoot 'build-tools\InnoSetup\ISCC.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    $compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'
}
& $compiler /Q "/DAppVersion=$appVersion" installer/FDH.iss
if ($LASTEXITCODE -ne 0) { throw 'Setup build failed' }
Compress-Archive -Path dist/FDH -DestinationPath "release/FDH-Portable-$appVersion.zip" -Force
$checksums = @("release/FDH-Setup-$appVersion.exe", "release/FDH-Portable-$appVersion.zip") | ForEach-Object {
    $hash = Get-FileHash -LiteralPath $_ -Algorithm SHA256
    $hash.Hash.ToLowerInvariant() + '  ' + (Split-Path $_ -Leaf)
}
$checksums | Set-Content -LiteralPath "release/SHA256SUMS-$appVersion.txt" -Encoding ascii
