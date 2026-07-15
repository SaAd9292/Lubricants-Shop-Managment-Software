"""Auto-update configuration.

MANIFEST_URL points at the signed manifest published with each GitHub Release.
Using the '/releases/latest/download/<asset>' form means the URL is stable and
always resolves to the newest release's asset — no per-version edits needed.

UPDATE_PUBLIC_KEY_HEX is the Ed25519 PUBLIC key. It is safe to ship. The matching
PRIVATE seed lives ONLY on the release machine (keys/, git-ignored) and signs the
manifest. If you ever rotate keys, replace this value and re-sign.
"""
from __future__ import annotations

MANIFEST_URL = (
    "https://github.com/SaAd9292/Lubricants-Shop-Managment-Software"
    "/releases/latest/download/latest.json"
)

UPDATE_PUBLIC_KEY_HEX = "78b17538767856d8dd01c730a536ab04099956f61cb3a4889cc78099c2af528b"
