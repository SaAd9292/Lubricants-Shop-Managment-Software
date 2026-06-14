# Penguix — Installer & Distribution

This turns the portable `Penguix.exe` into a proper Windows installer
(`Penguix-Setup-0.2.0.exe`) with a Start-menu shortcut, an optional desktop
icon, and a clean uninstaller.

## What you need (one time)

1. Build the app so `dist\Penguix.exe` exists:
   ```
   build_exe.bat
   ```
2. Install **Inno Setup** (free): https://jrsoftware.org/isdl.php

## Build the installer

**Easiest:** open `installer\penguix_installer.iss` in Inno Setup and press **F9** (Compile).

**Or** run the batch file:
```
installer\build_installer.bat
```

Result: **`installer\output\Penguix-Setup-0.2.0.exe`** — this single file is
what you give to a shop. They double-click it, click through, and Penguix is
installed with a Start-menu (and optional desktop) shortcut.

## Key facts

- **No admin rights needed.** It installs per-user (`PrivilegesRequired=lowest`).
- **Data is safe across reinstalls/upgrades.** Shop data lives in
  `%APPDATA%\Penguix` and is never removed by install or uninstall.
- **Upgrades:** keep the same `AppId` in the .iss (already set). Bump
  `AppVersion` in the .iss for each new release; installing a newer Setup over
  an older one upgrades in place.
- **Uninstall:** Settings → Apps → Penguix → Uninstall (or the Start-menu
  "Uninstall Penguix" shortcut).

## Releasing a new version

1. Update the version in `lubripos/__init__.py` and in `penguix_installer.iss`
   (`#define AppVersion`).
2. `build_exe.bat`  →  then build the installer again.

## Code signing (optional, recommended before selling widely)

Unsigned installers/exes show a one-time **“Windows protected your PC”**
SmartScreen warning (click *More info → Run anyway*). To remove it for
customers you need a **code-signing certificate** (paid, from a CA such as
Sectigo/DigiCert; an OV cert is the usual choice, ~$80–200/yr).

Once you have a certificate (`.pfx`), sign both the app exe and the installer:
```
signtool sign /f mycert.pfx /p PASSWORD /tr http://timestamp.digicert.com /td sha256 /fd sha256 dist\Penguix.exe
signtool sign /f mycert.pfx /p PASSWORD /tr http://timestamp.digicert.com /td sha256 /fd sha256 installer\output\Penguix-Setup-0.2.0.exe
```
(`signtool` ships with the Windows SDK.) Inno Setup can also sign automatically
via its **Sign Tools** setting if you prefer. Signing is the only way to make
the SmartScreen prompt go away for your customers.
