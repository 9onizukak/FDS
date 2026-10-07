# FDH

Windows application for sending HOSxP OPD UCS data to the MOPH Financial Data Hub.
Includes a Tkinter interface, read-only hospital database access, separate UAT and
Production settings, send history, and GitHub release updates.

## Run from source

Use Python 3.11. Install dependencies from `requirements-build.txt`, copy
`unz/.env.example` to `unz/.env`, and enter your hospital account and database
settings. Use a database account with SELECT permissions only. UAT is the default;
validate your configuration and payloads before submitting hospital data.

```powershell
python -m pip install -r requirements-build.txt
python unz/windows_launcher.py
```

Do not commit credentials, patient payloads, visit data, or send history.

## Build and update

See [Windows build and release instructions](installer/BUILD.md).
Application version: **1.0.5**. Packaged Windows apps check for stable releases at
startup and hourly, verify the installer download, wait for active jobs to finish,
and preserve configuration and history when updating.

The release workflow runs on a matching version tag such as `v1.0.5` and publishes
Windows installer and portable packages. Pushing source alone does not publish
a release. Source checkouts check updates manually and do not install executable
updates.

## Offline tests

```powershell
python -m unittest discover -s tests -v
```

IPD submission is not implemented; the IPD interface lists visits only.
