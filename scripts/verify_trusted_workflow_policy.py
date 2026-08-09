#!/usr/bin/env python3
"""Verify protected PR files using only a trusted base-branch policy."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable


NORMALIZATION = "utf8-lf-v1"
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PROTECTED_PATH_PATTERN = re.compile(
    r"^[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*$"
)
POLICY_KEYS = {
    "format_version", "normalization", "protected_paths", "approved_bundles"
}
BUNDLE_KEYS = {"id", "mode", "source", "files"}
SOURCE_KEYS = {"repository", "commit"}
BUNDLE_MODES = {"temporary-exact", "persistent-baseline"}


class PolicyError(RuntimeError):
  """A trusted workflow-policy violation."""


def _is_valid_repository(value: Any) -> bool:
  if not isinstance(value, str) or not REPOSITORY_PATTERN.fullmatch(value):
    return False
  return all(part not in (".", "..") for part in value.split("/"))


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
  actual = set(value)
  if actual != expected:
    raise PolicyError(
        f"{label}: keys must be exactly {sorted(expected)}; got {sorted(actual)}"
    )


def load_policy(path: Path) -> dict[str, Any]:
  try:
    policy = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, UnicodeError, json.JSONDecodeError) as error:
    raise PolicyError(f"cannot load trusted policy {path}: {error}") from error
  validate_policy(policy)
  return policy


def validate_policy(policy: Any) -> None:
  if not isinstance(policy, dict):
    raise PolicyError("policy: top-level value must be an object")
  _require_exact_keys(policy, POLICY_KEYS, "policy")
  if policy["format_version"] != 2:
    raise PolicyError("policy: format_version must be 2")
  if policy["normalization"] != NORMALIZATION:
    raise PolicyError(f"policy: normalization must be {NORMALIZATION}")

  paths = policy["protected_paths"]
  if not isinstance(paths, list) or not paths:
    raise PolicyError("policy: protected_paths must be a non-empty array")
  if any(not isinstance(path, str) or not path for path in paths):
    raise PolicyError("policy: every protected path must be a non-empty string")
  if len(paths) != len(set(paths)):
    raise PolicyError("policy: protected_paths must be unique")
  if any(not PROTECTED_PATH_PATTERN.fullmatch(path) for path in paths):
    raise PolicyError(
        "policy: protected paths must be canonical repository-relative POSIX paths"
    )
  if any(
      segment in (".", "..")
      for path in paths
      for segment in path.split("/")
  ):
    raise PolicyError("policy: protected paths cannot contain dot segments")
  if len(paths) != len({path.casefold() for path in paths}):
    raise PolicyError("policy: protected_paths must be unique ignoring case")

  bundles = policy["approved_bundles"]
  if not isinstance(bundles, list) or not bundles:
    raise PolicyError("policy: approved_bundles must be a non-empty array")
  bundle_ids: set[str] = set()
  bundle_identities: set[tuple[str, str, str]] = set()
  expected_paths = set(paths)
  for index, bundle in enumerate(bundles):
    label = f"policy.approved_bundles[{index}]"
    if not isinstance(bundle, dict):
      raise PolicyError(f"{label}: must be an object")
    _require_exact_keys(bundle, BUNDLE_KEYS, label)
    bundle_id = bundle["id"]
    if not isinstance(bundle_id, str) or not bundle_id:
      raise PolicyError(f"{label}.id: must be a non-empty string")
    if bundle_id in bundle_ids:
      raise PolicyError(f"{label}.id: duplicate bundle id {bundle_id}")
    bundle_ids.add(bundle_id)

    mode = bundle["mode"]
    if not isinstance(mode, str) or mode not in BUNDLE_MODES:
      raise PolicyError(
          f"{label}.mode: must be one of {sorted(BUNDLE_MODES)}"
      )

    source = bundle["source"]
    if not isinstance(source, dict):
      raise PolicyError(f"{label}.source: must be an object")
    _require_exact_keys(source, SOURCE_KEYS, f"{label}.source")
    if not _is_valid_repository(source["repository"]):
      raise PolicyError(f"{label}.source.repository: invalid repository")
    if (
        not isinstance(source["commit"], str)
        or not COMMIT_PATTERN.fullmatch(source["commit"])
    ):
      raise PolicyError(f"{label}.source.commit: must be 40 lowercase hex")
    identity = (mode, source["repository"], source["commit"])
    if identity in bundle_identities:
      raise PolicyError(f"{label}.source: duplicate authorization identity")
    bundle_identities.add(identity)

    files = bundle["files"]
    if not isinstance(files, dict) or set(files) != expected_paths:
      raise PolicyError(f"{label}.files: keys must match protected_paths exactly")
    for path, digest in files.items():
      if not isinstance(digest, str) or not DIGEST_PATTERN.fullmatch(digest):
        raise PolicyError(f"{label}.files[{path!r}]: invalid SHA-256 digest")


def normalize_content(content: bytes) -> bytes:
  try:
    text = content.decode("utf-8")
  except UnicodeDecodeError as error:
    raise PolicyError("protected file is not valid UTF-8") from error
  return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")


def normalized_sha256(content: bytes) -> str:
  return hashlib.sha256(normalize_content(content)).hexdigest()


def verify_candidate(
    policy: dict[str, Any],
    candidate_repository: str,
    candidate_ref: str,
    fetch_candidate: Callable[[str], bytes],
) -> dict[str, Any]:
  """Return the byte- and source-authorized trusted bundle."""
  validate_policy(policy)
  if not _is_valid_repository(candidate_repository):
    raise PolicyError("candidate repository must be exact owner/name")
  if (
      not isinstance(candidate_ref, str)
      or not COMMIT_PATTERN.fullmatch(candidate_ref)
  ):
    raise PolicyError("candidate ref must be an immutable 40-character lowercase SHA")
  eligible_bundles = [
      bundle
      for bundle in policy["approved_bundles"]
      if candidate_repository == bundle["source"]["repository"]
      and (
          bundle["mode"] == "persistent-baseline"
          or candidate_ref == bundle["source"]["commit"]
      )
  ]
  if not eligible_bundles:
    raise PolicyError("candidate source repository/ref is not authorized")
  actual = {
      path: normalized_sha256(fetch_candidate(path))
      for path in policy["protected_paths"]
  }
  for bundle in eligible_bundles:
    if actual == bundle["files"]:
      return bundle

  mismatches = []
  for path, digest in actual.items():
    allowed = sorted({bundle["files"][path] for bundle in eligible_bundles})
    if digest not in allowed:
      mismatches.append(f"{path}={digest}")
  if not mismatches:
    mismatches.append("protected files mix approved bundles but match no complete bundle")
  raise PolicyError("candidate is not an approved bundle: " + "; ".join(mismatches))


class GitHubContentsFetcher:
  def __init__(self, api_url: str, repository: str, ref: str, token: str):
    if not _is_valid_repository(repository):
      raise PolicyError("candidate repository must be owner/name")
    if not COMMIT_PATTERN.fullmatch(ref):
      raise PolicyError("candidate ref must be a 40-character lowercase commit SHA")
    parsed_api_url = urllib.parse.urlparse(api_url)
    if parsed_api_url.scheme != "https" or not parsed_api_url.netloc:
      raise PolicyError("GitHub API URL must be an absolute HTTPS URL")
    if not token:
      raise PolicyError("GITHUB_TOKEN is required")
    self._api_url = api_url.rstrip("/")
    self._repository = repository
    self._ref = ref
    self._token = token

  def __call__(self, path: str) -> bytes:
    quoted_path = urllib.parse.quote(path, safe="/")
    quoted_ref = urllib.parse.quote(self._ref, safe="")
    url = (
        f"{self._api_url}/repos/{self._repository}/contents/{quoted_path}"
        f"?ref={quoted_ref}"
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "smart-gatekeeper-trusted-workflow-policy",
        },
    )
    try:
      with urllib.request.urlopen(request, timeout=30) as response:
        payload_bytes = response.read()
    except urllib.error.HTTPError as error:
      raise PolicyError(f"GitHub API rejected {path}: HTTP {error.code}") from error
    except urllib.error.URLError as error:
      raise PolicyError(f"GitHub API failed for {path}: {error.reason}") from error

    try:
      payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
      raise PolicyError(f"GitHub API returned invalid JSON for {path}") from error
    if not isinstance(payload, dict):
      raise PolicyError(f"GitHub API returned non-file content for {path}")
    if payload.get("type") != "file" or payload.get("encoding") != "base64":
      raise PolicyError(f"GitHub API did not return a base64 file for {path}")
    encoded = payload.get("content")
    if not isinstance(encoded, str):
      raise PolicyError(f"GitHub API omitted file content for {path}")
    try:
      return base64.b64decode("".join(encoded.split()), validate=True)
    except ValueError as error:
      raise PolicyError(f"GitHub API returned invalid base64 for {path}") from error


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(allow_abbrev=False)
  parser.add_argument("--policy", required=True, type=Path)
  parser.add_argument("--candidate-repository", required=True, action="append")
  parser.add_argument("--candidate-ref", required=True, action="append")
  parser.add_argument("--api-url", default="https://api.github.com")
  args = parser.parse_args()
  if len(args.candidate_repository) != 1:
    parser.error("--candidate-repository must be supplied exactly once")
  if len(args.candidate_ref) != 1:
    parser.error("--candidate-ref must be supplied exactly once")
  args.candidate_repository = args.candidate_repository[0]
  args.candidate_ref = args.candidate_ref[0]
  return args


def main() -> int:
  args = parse_args()
  try:
    policy = load_policy(args.policy)
    fetcher = GitHubContentsFetcher(
        args.api_url,
        args.candidate_repository,
        args.candidate_ref,
        os.environ.get("GITHUB_TOKEN", ""),
    )
    bundle = verify_candidate(
        policy,
        args.candidate_repository,
        args.candidate_ref,
        fetcher,
    )
  except PolicyError as error:
    print(f"[ERROR] trusted workflow policy: {error}", file=sys.stderr)
    return 1
  print(
      json.dumps(
          {
              "status": "approved",
              "bundle": bundle["id"],
              "candidate_repository": args.candidate_repository,
              "candidate_ref": args.candidate_ref,
              "protected_file_count": len(policy["protected_paths"]),
          },
          sort_keys=True,
      )
  )
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
