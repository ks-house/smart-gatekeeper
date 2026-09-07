#!/usr/bin/env python3
"""Read-only PC client. Credentials never appear in command arguments or output."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_TOKEN_FILE = Path.home() / ".config/smart-gatekeeper/diagnostics-read.token"
TOKEN_ENV = "SGK_DIAGNOSTICS_READ_TOKEN"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even same-origin redirects are unexpected for this API.
        return None


def load_token(default_file=DEFAULT_TOKEN_FILE):
    direct = os.getenv(TOKEN_ENV)
    file_name = os.getenv(TOKEN_ENV + "_FILE")
    if direct is not None and file_name:
        raise ValueError("choose token environment OR token file, not both")
    if direct is None:
        path = Path(file_name) if file_name else default_file
        with path.open(encoding="ascii") as handle:
            direct = handle.read(130).strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{43,128}", direct):
        raise ValueError("invalid diagnostic token format")
    return direct


def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = secrets.token_urlsafe(32)
    # Refuse overwrites/symlinks. Rotation is an explicit new file + server update.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(token + "\n")
    return {"client_token_file": str(path.resolve()),
            "server_environment": {"DIAGNOSTICS_READ_TOKEN_SHA256":
                                   hashlib.sha256(token.encode("ascii")).hexdigest()}}


def endpoint(base, bundle_id, limit, before_id):
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("base URL must be an HTTPS origin without credentials or query")
    url = base.rstrip("/") + "/api/v1/diagnostics/bundles"
    if bundle_id is not None:
        return url + "/" + str(bundle_id)
    query = {"limit": limit}
    if before_id is not None:
        query["before_id"] = before_id
    return url + "?" + urllib.parse.urlencode(query)


def fetch(url, token):
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + token, "Accept": "application/json",
    }, method="GET")
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
        content = response.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError("diagnostic response exceeds limit")
    return json.loads(content)


def positive(value):
    result = int(value)
    if not 1 <= result <= 18446744073709551615:
        raise argparse.ArgumentTypeError("expected positive database ID")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--init-token", action="store_true", help="create local token without displaying it")
    mode.add_argument("--check-token", action="store_true", help="check local availability; no network")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE,
                        help="creation destination for --init-token only")
    parser.add_argument("--base-url", default="https://tworimpa.synology.me:4442")
    parser.add_argument("--bundle-id", type=positive)
    parser.add_argument("--before-id", type=positive)
    parser.add_argument("--limit", type=int, default=20, choices=range(1, 101), metavar="1..100")
    args = parser.parse_args(argv)
    try:
        if args.init_token:
            result = initialize(args.token_file)
        else:
            token = load_token()
            result = {"token_available": True} if args.check_token else fetch(
                endpoint(args.base_url, args.bundle_id, args.limit, args.before_id), token,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except urllib.error.HTTPError as error:
        # Do not echo untrusted response bodies, URLs or request headers.
        print(f"Diagnostic read failed: HTTP {error.code}", file=sys.stderr)
    except (OSError, ValueError):
        print("Diagnostic client failed: check token availability, HTTPS origin and connectivity.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
