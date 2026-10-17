#!/usr/bin/env python3
"""Local authenticated signer for privileged, audited NAS maintenance."""
from pathlib import Path
import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import uuid

DEFAULT = Path.home()/".config/smart-gatekeeper-maintenance"


def private(path):
    info = path.lstat()
    if path.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("owner-private maintenance key/config required")
    return path.read_bytes()


def arguments(directory):
    info = json.loads(private(directory/"connection.json"))
    if set(info) != {"host", "port", "username"}:
        raise ValueError("closed maintenance connection metadata required")
    if (re.fullmatch(r"[A-Za-z0-9.-]{1,253}", info["host"]) is None
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}", info["username"]) is None
            or type(info["port"]) is not int or not 1 <= info["port"] <= 65535):
        raise ValueError("bounded maintenance endpoint required")
    private(directory/"nas-maintenance-ed25519")
    return ["ssh", "-F", "/dev/null", "-S", "none", "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes", "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no", "-o", "ForwardAgent=no",
            "-o", "ForwardX11=no", "-o", "StrictHostKeyChecking=yes",
            "-o", "LogLevel=ERROR", "-o", "UserKnownHostsFile="+str(directory/"known_hosts"),
            "-i", str(directory/"nas-maintenance-ed25519"), "-p", str(info["port"]),
            info["username"]+"@"+info["host"]]


def envelope(script, operation, timeout, directory, request_id=None):
    if (re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", operation) is None
            or type(timeout) is not int or not 1 <= timeout <= 900
            or not script or len(script) > 262144):
        raise ValueError("bounded signed operation required")
    compile(script, "<signed-maintenance>", "exec")
    identifier = request_id or uuid.uuid4().hex
    if re.fullmatch(r"[a-f0-9]{32}", identifier) is None:
        raise ValueError("request UUID required")
    requests = directory/"requests";requests.mkdir(mode=0o700, exist_ok=True)
    path = requests/(identifier+".json")
    code_hash = hashlib.sha256(script).hexdigest()
    if path.exists():
        raw = private(path);old = json.loads(raw)["manifest"]
        if (old["script_sha256"] != code_hash or old["operation"] != operation
                or old["timeout_seconds"] != timeout):
            raise ValueError("existing signed request differs")
        return raw
    epoch = int(time.time())
    manifest = {"schema_version": 1, "request_id": identifier, "operation": operation,
                "script_sha256": code_hash, "issued_at": epoch, "expires_at": epoch+900,
                "timeout_seconds": timeout}
    raw_manifest = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    key_path = directory/"signer-private.pem"
    private(key_path)
    signed = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key_path)],
                            input=raw_manifest, capture_output=True, timeout=15)
    if signed.returncode or len(signed.stdout) != 384:
        raise ValueError("RSA3072 maintenance signing failed")
    signature = signed.stdout
    raw = json.dumps({"manifest": manifest, "script": base64.b64encode(script).decode(),
                     "signature": base64.b64encode(signature).decode()},
                    sort_keys=True, separators=(",", ":")).encode()
    fd = os.open(str(path), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "submit", "result"))
    parser.add_argument("--connection-dir", type=Path, default=DEFAULT)
    parser.add_argument("--script", type=Path)
    parser.add_argument("--operation")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--request-id")
    args = parser.parse_args()
    raw = None
    if args.command == "submit":
        if not args.script or not args.operation:
            parser.error("submit requires an explicitly selected script and operation label")
        raw = envelope(args.script.read_bytes(), args.operation, args.timeout,
                       args.connection_dir, args.request_id)
    elif args.script or args.operation or args.request_id:
        parser.error("signed input belongs only to submit")
    result = subprocess.run([*arguments(args.connection_dir), args.command], input=raw,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
    if result.returncode:
        print("Signed maintenance command failed", file=sys.stderr)
        if result.stdout:
            sys.stdout.buffer.write(result.stdout)
        return result.returncode
    print(json.dumps(json.loads(result.stdout), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
