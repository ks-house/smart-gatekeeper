#!/usr/bin/env python3
"""Dedicated pinned NAS ha client; credentials never appear in argv."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

COMMANDS=("status","diagnose","refresh-logging","adopt","verify","rollback")
DEFAULT=Path.home()/".config/smart-gatekeeper-ha"


def ssh_arguments(directory):
    configuration=directory/"connection.json"
    info=configuration.stat()
    if info.st_uid!=os.getuid() or info.st_mode & 0o077:
        raise ValueError("connection metadata must be private")
    data=json.loads(configuration.read_text())
    if set(data)!={"host","port","username"}:
        raise ValueError("unexpected connection fields")
    if not isinstance(data["host"],str) or re.fullmatch(r"[A-Za-z0-9.-]{1,253}",data["host"]) is None:
        raise ValueError("invalid SSH host")
    if not isinstance(data["username"],str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,31}",data["username"]) is None:
        raise ValueError("invalid SSH user")
    if type(data["port"]) is not int or not 1<=data["port"]<=65535:
        raise ValueError("invalid SSH port")
    key=directory/"nas-ha-ops-ed25519"
    info=key.stat()
    if info.st_uid!=os.getuid() or info.st_mode & 0o077:
        raise ValueError("private key permissions invalid")
    return ["ssh","-F","/dev/null","-S","none","-o","BatchMode=yes",
            "-o","IdentitiesOnly=yes","-o","PasswordAuthentication=no",
            "-o","KbdInteractiveAuthentication=no","-o","ForwardAgent=no",
            "-o","ForwardX11=no","-o","StrictHostKeyChecking=yes",
            "-o","LogLevel=ERROR","-o","UserKnownHostsFile="+str(directory/"known_hosts"),
            "-i",str(key),"-p",str(data["port"]),data["username"]+"@"+data["host"]]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation",choices=COMMANDS)
    parser.add_argument("--connection-dir",type=Path,default=DEFAULT)
    args=parser.parse_args()
    raw=None
    result=subprocess.run([*ssh_arguments(args.connection_dir),args.operation],input=raw,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=45)
    if result.returncode:
        print("HA maintenance command failed",file=sys.stderr)
        if result.stdout:sys.stdout.buffer.write(result.stdout)
        return result.returncode
    data=json.loads(result.stdout)
    print(json.dumps(data,sort_keys=True))
    return 0


if __name__=="__main__":
    sys.exit(main())
