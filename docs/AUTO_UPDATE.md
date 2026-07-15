# Penguix Auto-Update

Penguix checks for updates against a **signed manifest** hosted on GitHub
Releases, and (with the user's consent) downloads and runs the new installer.

## How it works
1. On launch (throttled to once/day) and via **Help → Check for updates…**, the
   app fetches `latest.json` from the GitHub Release.
2. `latest.json` is `{"data": {version,url,sha256,notes}, "sig": "<hex>"}`. The
   app verifies `sig` (Ed25519) against the **public key baked into the app**
   before trusting anything.
3. If `data.version` is newer, the user is asked to install. On yes, the app
   downloads the installer, checks its **SHA-256** matches the manifest, then
   launches it and closes so files can be replaced. The installer reopens Penguix.
4. On next launch, DB **migrations** run automatically. The database lives in
   AppData, separate from program files, so updates never touch shop data.

Because the manifest is signed, a tampered installer **or** a tampered manifest is
rejected — even if the GitHub account/host is compromised — because the attacker
does not have the private signing key.

## One-time key setup
Already done once via `python tools/keygen.py`:
- Private seed: `keys/update_private_seed.hex` — **secret, git-ignored, back it up.**
  If you lose it you can't sign updates; if it leaks, rotate keys.
- Public key: pasted into `lubripos/services/update_config.py`
  (`UPDATE_PUBLIC_KEY_HEX`). Safe to ship.

## Cutting a release
1. Bump `__version__` in `lubripos/__init__.py` (and `AppVersion` in the `.iss`).
2. Build the installer: `installer\build_installer.bat`
   → `installer/output/Penguix-Setup-<version>.exe`
3. Build + sign the manifest:
   ```
   python tools/release.py --installer installer/output/Penguix-Setup-<version>.exe \
                           --notes "What changed in this version"
   ```
   → writes `dist/latest.json`
4. Publish both as assets on a release tagged `v<version>`:
   ```
   gh release create v<version> "installer/output/Penguix-Setup-<version>.exe" \
       "dist/latest.json" --title "v<version>" --notes "What changed"
   ```
   The manifest URL `.../releases/latest/download/latest.json` now resolves to it.

## Notes
- The repo (or a dedicated releases repo) must be **public** so shop PCs can
  download without a login.
- Removing the SmartScreen "unknown publisher" warning is a **separate** step
  (Authenticode code-signing certificate) and can be added later without changing
  any of this.
