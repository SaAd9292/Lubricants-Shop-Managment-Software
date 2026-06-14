# Building Penguix.exe (Windows)

A Windows `.exe` must be built **on a Windows PC** (PyInstaller builds for the
OS it runs on). You only need to do this on your machine.

## One-time / each release

1. Open PowerShell in the project folder and activate the venv:

   ```
   cd "C:\Users\GHOST\Desktop\Lubricants Shop Software"
   .venv\Scripts\activate
   ```

2. Double-click **`build_exe.bat`** (or run it from the terminal):

   ```
   build_exe.bat
   ```

   It installs PyInstaller, then builds from `penguix.spec`.

3. When it finishes you'll have:

   ```
   dist\Penguix.exe
   ```

That single file is the whole application. Copy it to any Windows PC (no Python
needed) and double-click to run.

## Notes

- **Size:** expect ~80–150 MB. That's normal — the GUI toolkit (PySide6) is
  bundled inside. UPX compression is enabled in the spec to keep it smaller.
- **First run on a new shop:** the app creates its database automatically in
  `%APPDATA%\Penguix`, seeds the default admin (`admin` / `admin123`, forced
  password change on first login), then the owner sets their shop name, logo,
  currency and tax in **Settings**. Nothing is hardcoded per shop.
- **Data is never inside the exe** — the database, backups and logs live in
  `%APPDATA%\Penguix`, so replacing the exe with a new version never touches
  shop data.
- **Icon:** `assets/penguix.ico` (penguin). Replace that file and rebuild to
  change it.
- **Antivirus / SmartScreen:** unsigned exes may trigger a "Windows protected
  your PC" warning the first time (click *More info → Run anyway*). To remove
  it for customers you'd buy a code-signing certificate — optional, later.

## Optional: installer

`Penguix.exe` is portable and needs no installer. If you later want a proper
Start-menu installer, **Inno Setup** (free) can wrap `dist\Penguix.exe` in a
few lines — ask and I'll generate the script.
