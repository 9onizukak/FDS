# FDH version history

Application versions are separate from the FDH dataset schema version.

## [Unreleased]

- Include this changelog in installer and portable packages, with a Start Menu shortcut.
- Generate GitHub release notes from the matching version entry below.

## [1.0.5]

- Update the application version and Windows package names to 1.0.5.
- Include the verified GitHub automatic updater and its Windows helper startup fix.
- Verify live detection and installer download from the `v1.0.5` GitHub release.
- Confirm an app already on 1.0.5 does not reinstall the same version.

## [1.0.4]

- Display the installed application version and add a manual update check.
- Check stable GitHub releases automatically at startup and every hour.
- Add a saved option to disable automatic updates.
- Verify installer size and SHA-256 before installation.
- Wait for active searches, submissions, and status checks to finish before updating.
- Install into the existing application directory and restart after successful setup.
- Preserve configuration and send history during updates.
- Fix packaged Windows helper startup by resetting the DLL search path and PyInstaller environment.
- Keep FDH open if the update helper fails to start, and save startup diagnostics.
- Add offline updater tests and an isolated installer/restart integration test.
- Add a GitHub Actions workflow to build and publish packages from matching version tags.

## [1.0.3]

The existing Windows application baseline includes:

- A Tkinter interface for searching, selecting, submitting, and checking OPD UCS visits.
- Read-only HOSxP database access and send history.
- Separate UAT and Production API settings and history.
- Background searches with progress indicators and protection against duplicate jobs.
- Windows installer and portable packages with configuration outside program files.
- An IPD visit list; IPD submission is not implemented.

Detailed change records for versions before 1.0.3 are not available in this repository.
