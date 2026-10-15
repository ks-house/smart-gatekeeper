#!/usr/bin/env python3
"""Render an explicit deny-by-default ACL candidate, without reading passwords.

Input inventories contain role names and exact Target IDs only. No production
file is overwritten; installing the candidate is a separate operator step.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
FIELDS = {"schema_version", "targets", "backend_username", "ha_username",
          "diagnostic_usernames", "discovery_device_id"}
NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
DIAGNOSTIC = (("targets", "status"), ("targets", "availability"), ("targets", "boot"),
              ("ha-bridge", "verified-status"), ("ha-bridge", "availability"),
              ("ha-bridge", "connectivity-diagnostic"))


def name(value):
    if not isinstance(value, str) or NAME.fullmatch(value) is None:
        raise ValueError("invalid principal, Target or discovery name")
    return value


def inventory(profile):
    if not isinstance(profile, dict) or set(profile) != FIELDS:
        raise ValueError("inventory fields must be exact; passwords do not belong here")
    if type(profile["schema_version"]) is not int or profile["schema_version"] != 1:
        raise ValueError("unsupported inventory schema")
    targets, diagnostics = profile["targets"], profile["diagnostic_usernames"]
    if not isinstance(targets, list) or not 1 <= len(targets) <= 64:
        raise ValueError("one to64 exact Targets required")
    if not isinstance(diagnostics, list) or len(diagnostics) > 8:
        raise ValueError("at most8 diagnostic principals")
    principals = [*(name(x) for x in targets), name(profile["backend_username"]),
                  name(profile["ha_username"]), *(name(x) for x in diagnostics)]
    if len(set(principals)) != len(principals):
        raise ValueError("principal roles/Target usernames must be distinct")
    name(profile["discovery_device_id"])
    return sorted(targets), sorted(diagnostics)


def template_blocks(template):
    blocks, user = {}, None
    for raw in template.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0] == "user" and len(parts) == 2:
            user = parts[1]
            if user in blocks:
                raise ValueError("duplicate template principal")
            blocks[user] = []
        elif (parts[0] == "topic" and len(parts) == 3 and user is not None
              and parts[1] in {"read", "write", "readwrite"}):
            blocks[user].append((parts[1], parts[2]))
        else:
            raise ValueError("only explicit named-user topic rules are allowed")
    if set(blocks) != {"target-example", "gatekeeper-backend", "homeassistant"}:
        raise ValueError("unexpected reference roles")
    return blocks


def render_acl(profile, template=None):
    targets, diagnostics = inventory(profile)
    if template is None:
        template = (ROOT / "security/target-acl").read_text(encoding="utf-8")
    blocks = template_blocks(template)
    lines = ["# Generated candidate: exact named principals; implicit default deny.",
             "# No passwords or global pattern rules. Install only after staged validation."]

    def block(username, rules):
        lines.extend(["", "user " + username])
        lines.extend("topic " + mode + " " + topic for mode, topic in rules)

    for target in targets:
        block(target, [(mode, topic.replace("/target-example/", "/" + target + "/"))
                       for mode, topic in blocks["target-example"]])
    for reference, selected in [("gatekeeper-backend", profile["backend_username"]),
                                ("homeassistant", profile["ha_username"])]:
        rules = []
        for mode, topic in blocks[reference]:
            topic = topic.replace("/smart_gatekeeper_01/", "/" + profile["discovery_device_id"] + "/")
            if topic.startswith(("gatekeeper/v1/targets/+/", "gatekeeper/v1/ha-bridge/+/")):
                rules.extend((mode, topic.replace("/+/", "/" + target + "/", 1)) for target in targets)
            else:
                rules.append((mode, topic))
        block(selected, rules)
    for diagnostic in diagnostics:
        block(diagnostic, [("read", "gatekeeper/v1/" + group + "/" + target + "/" + suffix)
                           for target in targets for group, suffix in DIAGNOSTIC])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="new candidate file; existing files are never replaced")
    args = parser.parse_args(argv)
    with args.inventory.open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        parser.error("inventory byte bound exceeded")
    profile = json.loads(raw)
    rendered = render_acl(profile).encode("utf-8")
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(rendered)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(dict(candidate_sha256=hashlib.sha256(rendered).hexdigest(),
                          target_count=len(profile["targets"]),
                          principal_count=len(profile["targets"]) + 2 +
                          len(profile["diagnostic_usernames"]),
                          production_installed=False)))


if __name__ == "__main__":
    main()
