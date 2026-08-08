#!/usr/bin/env python3
"""Create and verify artifact-bound Smart Gatekeeper mobile OTA metadata."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ota_contract_gate import GateError, canonical_signed_bytes, validate_manifest


def _artifact_identity(path: Path) -> tuple[int, str]:
  if not path.is_file():
    raise GateError(f"mobile artifact is missing or not a file: {path}")
  digest = hashlib.sha256()
  size = 0
  with path.open("rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
      size += len(chunk)
      digest.update(chunk)
  if size < 1:
    raise GateError("mobile artifact must not be empty")
  return size, digest.hexdigest()


def _private_key_from_env(variable: str) -> Ed25519PrivateKey:
  value = os.environ.get(variable, "")
  if not re.fullmatch(r"[0-9a-f]{64}", value):
    raise GateError(f"{variable} must contain an exact 32-byte lowercase hex seed")
  return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(value))


def _public_hex(private_key: Ed25519PrivateKey) -> str:
  public = private_key.public_key().public_bytes(
      encoding=serialization.Encoding.Raw,
      format=serialization.PublicFormat.Raw,
  )
  return public.hex()


def _timestamp(value: str, label: str) -> datetime:
  if not re.search(r"(?:Z|[+-]\d{2}:\d{2})$", value):
    raise GateError(f"{label} must be an RFC3339 timestamp with a timezone")
  try:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
  except ValueError as exc:
    raise GateError(f"{label} must be a valid RFC3339 timestamp") from exc


def create_manifest(args: argparse.Namespace) -> None:
  private_key = _private_key_from_env(args.private_key_env)
  public_hex = _public_hex(private_key)
  if args.expected_public_key_hex and public_hex != args.expected_public_key_hex:
    raise GateError("signing private key does not match the pinned updater public key")
  size, sha256 = _artifact_identity(args.artifact)
  publication = _timestamp(args.published_at, "published_at")
  if args.mandatory_after is not None and _timestamp(
      args.mandatory_after, "mandatory_after"
  ) < publication:
    raise GateError("mandatory_after cannot precede published_at")
  manifest: dict[str, object] = {
      "schema_version": 1,
      "artifact_type": "android-apk",
      "version": args.version,
      "version_name": args.version,
      "build_number": args.build_number,
      "version_code": args.build_number,
      "protocol_min": args.protocol_min,
      "protocol_max": args.protocol_max,
      "min_android_sdk": args.min_android_sdk,
      "apk_url": args.apk_url,
      "fallback_url": args.fallback_url,
      "apk_size": size,
      "sha256": sha256,
      "signing_certificate_digest": args.certificate_sha256,
      "signature_algorithm": "Ed25519",
      "signing_key_id": args.signing_key_id,
      "signature": "",
      "mandatory_after": args.mandatory_after,
      "release_notes_url": args.release_notes_url,
      "published_at": args.published_at,
      "commit": args.commit,
  }
  signature = private_key.sign(canonical_signed_bytes(manifest))
  manifest["signature"] = base64.b64encode(signature).decode("ascii")
  validate_manifest(manifest, "mobile-manifest.schema.json", public_hex)
  args.output.parent.mkdir(parents=True, exist_ok=True)
  args.output.write_text(
      json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
      encoding="utf-8",
  )
  print(f"[MOBILE-MANIFEST] created and verified: {args.output}")


def verify_manifest(args: argparse.Namespace) -> None:
  try:
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError) as exc:
    raise GateError(f"mobile manifest cannot be read: {args.manifest}") from exc
  if not isinstance(manifest, dict):
    raise GateError("mobile manifest top-level value must be an object")
  validate_manifest(manifest, "mobile-manifest.schema.json", args.public_key_hex)
  size, sha256 = _artifact_identity(args.artifact)
  if manifest["apk_size"] != size or manifest["sha256"] != sha256:
    raise GateError("mobile manifest is not bound to the exact APK bytes")
  if manifest["signing_certificate_digest"] != args.certificate_sha256:
    raise GateError("mobile manifest certificate digest does not match apksigner")
  print(f"[MOBILE-MANIFEST] artifact binding verified: {args.manifest}")


def _common_create_arguments(parser: argparse.ArgumentParser) -> None:
  parser.add_argument("--artifact", type=Path, required=True)
  parser.add_argument("--output", type=Path, required=True)
  parser.add_argument("--version", required=True)
  parser.add_argument("--build-number", type=int, required=True)
  parser.add_argument("--commit", required=True)
  parser.add_argument("--apk-url", required=True)
  parser.add_argument("--fallback-url", required=True)
  parser.add_argument("--release-notes-url", required=True)
  parser.add_argument("--published-at", required=True)
  parser.add_argument("--mandatory-after")
  parser.add_argument("--certificate-sha256", required=True)
  parser.add_argument("--signing-key-id", required=True)
  parser.add_argument("--private-key-env", required=True)
  parser.add_argument("--expected-public-key-hex", required=True)
  parser.add_argument("--protocol-min", type=int, default=1)
  parser.add_argument("--protocol-max", type=int, default=2)
  parser.add_argument("--min-android-sdk", type=int, default=23)


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser()
  subparsers = parser.add_subparsers(dest="command", required=True)
  create = subparsers.add_parser("create")
  _common_create_arguments(create)
  verify = subparsers.add_parser("verify")
  verify.add_argument("--manifest", type=Path, required=True)
  verify.add_argument("--artifact", type=Path, required=True)
  verify.add_argument("--public-key-hex", required=True)
  verify.add_argument("--certificate-sha256", required=True)
  return parser.parse_args()


def main() -> int:
  args = parse_args()
  try:
    if args.command == "create":
      create_manifest(args)
    else:
      verify_manifest(args)
  except (GateError, OSError, ValueError) as exc:
    print(f"[MOBILE-MANIFEST] FAIL: {exc}", file=sys.stderr)
    return 1
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
