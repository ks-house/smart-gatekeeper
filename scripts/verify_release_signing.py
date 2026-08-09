"""Fail-closed release signing identity check for CI.

The script intentionally does not create a keystore or accept debug certificates.
It is a pre-build guard; apksigner remains the source of the emitted APK identity.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import shlex
from pathlib import Path


DEBUG_CERT_MARKERS = ("androiddebugkey", "android debug", "debug.keystore")


def verify(apk: Path, expected_sha256: str, apksigner: str = "apksigner") -> None:
    if not apk.is_file() or apk.stat().st_size == 0:
        raise SystemExit("release signing failed: APK is missing or empty")
    command = shlex.split(apksigner) if isinstance(apksigner, str) else [apksigner]
    output = subprocess.run(
        command + ["verify", "--print-certs", str(apk)],
        capture_output=True,
        text=True,
        check=False,
    )
    if output.returncode != 0:
        raise SystemExit("release signing failed: apksigner rejected APK")
    text = (output.stdout + output.stderr).lower()
    if any(marker in text for marker in DEBUG_CERT_MARKERS):
        raise SystemExit("release signing failed: debug certificate detected")
    actual = re.search(r"certificate sha-256 digest:\s*([0-9a-f:]+)", text)
    if actual is None:
        raise SystemExit("release signing failed: certificate digest missing")
    normalized = actual.group(1).replace(":", "")
    if normalized != expected_sha256.lower().replace(":", ""):
        raise SystemExit("release signing failed: certificate digest mismatch")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--certificate-sha256", required=True)
    parser.add_argument("--apksigner", default="apksigner")
    args = parser.parse_args()
    verify(args.apk, args.certificate_sha256, args.apksigner)
