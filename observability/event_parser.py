"""Dependency-free validator and partial-order parser for event schema v1."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import heapq
import json
import re
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "event_codes_v1.json"
UINT64_MAX = (1 << 64) - 1

REQUIRED_FIELDS = {
    "schema_version",
    "event_id",
    "session_id",
    "session_kind",
    "source_component",
    "source_instance_id",
    "source_boot_id",
    "sequence",
    "attempt",
    "event_code",
    "stage",
    "outcome",
    "reason_code",
    "clock",
    "target",
    "causation_event_id",
    "attributes",
}
OPTIONAL_FIELDS = {"update"}
SOURCE_COMPONENTS = {"android", "target", "backend", "collector"}
SESSION_KINDS = {"access", "update"}
CLOCK_QUALITIES = {"SYNCED", "UNSYNCED", "UNKNOWN"}
OUTCOMES = {
    "STARTED",
    "PROGRESS",
    "SUCCEEDED",
    "DENIED",
    "FAILED",
    "TIMED_OUT",
    "CANCELLED",
}
OPAQUE_REF_RE = re.compile(r"^[a-z][a-z0-9_-]{7,63}$")
BOOT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{7,63}$")
REASON_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
WALL_TIME_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z$"
)
MAC_RE = re.compile(r"(?i)(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}")
PHONE_RE = re.compile(r"(?<!\d)01[016789][ -]?\d{3,4}[ -]?\d{4}(?!\d)")
PRIVATE_MATERIAL_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._~-]+",
    re.IGNORECASE,
)
FORBIDDEN_KEY_RE = re.compile(
    r"(?:^|_)(?:secret|password|token|private_key|proof|signature|nonce|mac|"
    r"phone|tenant_name|unit_number|raw_payload|artifact_url|apk_url|firmware_url)(?:$|_)",
    re.IGNORECASE,
)
ATTRIBUTE_FIELDS = {
    "path",
    "credential_ref",
    "distance_mm",
    "duration_ms",
    "relay_hold_ms",
    "queue_depth",
    "http_status",
    "transport",
    "protocol_version",
    "prior_target_boot_id",
    "reset_reason_code",
    "progress_percent",
}
UPDATE_FIELDS = {
    "component",
    "current_version",
    "target_version",
    "artifact_sha256",
    "confirmation",
}
UPDATE_CONFIRMATIONS = {
    "NONE",
    "ARTIFACT_VERIFIED",
    "INSTALLED",
    "BOOTED",
    "HEALTH_CONFIRMED",
    "MARKED_VALID",
    "ROLLED_BACK",
}
DIGEST_REQUIRED_EVENTS = {
    "UPDATE_MANIFEST_VERIFIED",
    "UPDATE_DOWNLOAD_STARTED",
    "UPDATE_DOWNLOAD_PROGRESS",
    "UPDATE_ARTIFACT_VERIFIED",
    "UPDATE_INSTALL_STARTED",
    "UPDATE_INSTALLED",
    "UPDATE_REBOOT_REQUESTED",
    "UPDATE_BOOT_CONFIRMED",
    "UPDATE_HEALTH_CONFIRMED",
    "UPDATE_MARKED_VALID",
    "UPDATE_ROLLBACK_STARTED",
    "UPDATE_ROLLBACK_PREVIOUS_INSTALL_CONFIRMED",
    "UPDATE_ROLLBACK_PREVIOUS_BOOT_CONFIRMED",
    "UPDATE_ROLLBACK_PREVIOUS_HEALTH_CONFIRMED",
    "UPDATE_ROLLBACK_CONFIRMED",
    "UPDATE_SESSION_COMPLETED",
}


class EventValidationError(ValueError):
    """Raised when one event or a stream violates the v1 contract."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def load_jsonl(path: Path | str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise EventValidationError(
                    [f"{path}:{line_number}: invalid JSON: {error.msg}"]
                ) from error
            if not isinstance(value, dict):
                raise EventValidationError(
                    [f"{path}:{line_number}: event must be a JSON object"]
                )
            events.append(value)
    return events


def _is_uuid4(value: Any) -> bool:
    if not isinstance(value, str) or value != value.lower():
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def _parse_wall_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _privacy_errors(value: Any, path: str = "event") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if FORBIDDEN_KEY_RE.search(str(key)):
                errors.append(f"{path}.{key}: forbidden sensitive field name")
            errors.extend(_privacy_errors(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_privacy_errors(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        if MAC_RE.search(value):
            errors.append(f"{path}: raw MAC address is forbidden")
        if PHONE_RE.search(value):
            errors.append(f"{path}: phone number is forbidden")
        if PRIVATE_MATERIAL_RE.search(value):
            errors.append(f"{path}: private/auth material is forbidden")
        if re.match(r"https?://", value, re.IGNORECASE) and "?" in value:
            errors.append(f"{path}: URL query strings may contain credentials")
    return errors


def validate_event(
    event: dict[str, Any], catalog: dict[str, Any] | None = None
) -> None:
    catalog = catalog or load_catalog()
    errors: list[str] = []
    keys = set(event)
    missing = sorted(REQUIRED_FIELDS - keys)
    extra = sorted(keys - REQUIRED_FIELDS - OPTIONAL_FIELDS)
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if extra:
        errors.append(f"unknown fields: {', '.join(extra)}")
    if missing:
        raise EventValidationError(errors)

    if event["schema_version"] != catalog.get("schema_version"):
        errors.append("schema_version must match event code catalog")
    for field in ("event_id", "session_id"):
        if not _is_uuid4(event[field]):
            errors.append(f"{field} must be a lowercase UUIDv4")
    if event["session_kind"] not in SESSION_KINDS:
        errors.append("session_kind is invalid")
    if event["source_component"] not in SOURCE_COMPONENTS:
        errors.append("source_component is invalid")
    if not isinstance(event["source_instance_id"], str) or not OPAQUE_REF_RE.fullmatch(
        event["source_instance_id"]
    ):
        errors.append("source_instance_id must be an opaque lowercase reference")
    if not isinstance(event["source_boot_id"], str) or not BOOT_ID_RE.fullmatch(
        event["source_boot_id"]
    ):
        errors.append("source_boot_id is invalid")
    sequence = event["sequence"]
    if (
        isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or not 0 <= sequence <= UINT64_MAX
    ):
        errors.append(f"sequence must be an integer between 0 and {UINT64_MAX}")
    attempt = event["attempt"]
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        errors.append("attempt must be an integer >= 1")

    code = catalog.get("event_codes", {}).get(event["event_code"])
    if code is None:
        errors.append(f"event_code is not registered: {event['event_code']}")
    else:
        if event["session_kind"] != code["session_kind"]:
            errors.append("event_code is not valid for session_kind")
        if event["stage"] != code["stage"]:
            errors.append("stage does not match event_code")
        if event["outcome"] not in code["allowed_outcomes"]:
            errors.append("outcome is not allowed for event_code")
        if event["reason_code"] not in code["allowed_reason_codes"]:
            errors.append("reason_code is not allowed for event_code")
    if event["outcome"] not in OUTCOMES:
        errors.append("outcome is invalid")
    if not isinstance(event["reason_code"], str) or not REASON_RE.fullmatch(
        event["reason_code"]
    ):
        errors.append("reason_code format is invalid")

    clock = event["clock"]
    if not isinstance(clock, dict):
        errors.append("clock must be an object")
    else:
        allowed_clock = {"wall_time", "monotonic_ms", "quality", "uncertainty_ms"}
        if set(clock) - allowed_clock:
            errors.append("clock contains unknown fields")
        if not {"wall_time", "monotonic_ms", "quality"}.issubset(clock):
            errors.append("clock is missing required fields")
        else:
            wall_time = clock["wall_time"]
            if wall_time is not None:
                if not isinstance(wall_time, str) or not WALL_TIME_RE.fullmatch(wall_time):
                    errors.append("clock.wall_time must be UTC RFC3339 or null")
                else:
                    try:
                        _parse_wall_time(wall_time)
                    except ValueError:
                        errors.append("clock.wall_time is not a real timestamp")
            monotonic_ms = clock["monotonic_ms"]
            if (
                isinstance(monotonic_ms, bool)
                or not isinstance(monotonic_ms, int)
                or not 0 <= monotonic_ms <= UINT64_MAX
            ):
                errors.append(
                    f"clock.monotonic_ms must be an integer between 0 and {UINT64_MAX}"
                )
            if clock["quality"] not in CLOCK_QUALITIES:
                errors.append("clock.quality is invalid")
            if clock["quality"] == "SYNCED":
                if wall_time is None:
                    errors.append("SYNCED clock requires wall_time")
                if not isinstance(clock.get("uncertainty_ms"), int) or isinstance(
                    clock.get("uncertainty_ms"), bool
                ) or clock.get("uncertainty_ms", -1) < 0:
                    errors.append("SYNCED clock requires uncertainty_ms >= 0")

    target = event["target"]
    if not isinstance(target, dict) or set(target) != {"target_ref", "boot_id"}:
        errors.append("target must contain only target_ref and boot_id")
    else:
        if not isinstance(target["target_ref"], str) or not OPAQUE_REF_RE.fullmatch(
            target["target_ref"]
        ):
            errors.append("target.target_ref must be an opaque reference")
        if target["boot_id"] is not None and (
            not isinstance(target["boot_id"], str)
            or not BOOT_ID_RE.fullmatch(target["boot_id"])
        ):
            errors.append("target.boot_id is invalid")
        if event["source_component"] == "target":
            if target["boot_id"] != event["source_boot_id"]:
                errors.append("target producer must use its source_boot_id as target.boot_id")

    cause = event["causation_event_id"]
    if cause is not None and not _is_uuid4(cause):
        errors.append("causation_event_id must be a lowercase UUIDv4 or null")
    if cause == event["event_id"]:
        errors.append("event cannot cause itself")

    attributes = event["attributes"]
    if not isinstance(attributes, dict):
        errors.append("attributes must be an object")
    else:
        unknown_attributes = sorted(set(attributes) - ATTRIBUTE_FIELDS)
        if unknown_attributes:
            errors.append(f"unknown attributes: {', '.join(unknown_attributes)}")
        if "credential_ref" in attributes and (
            not isinstance(attributes["credential_ref"], str)
            or not OPAQUE_REF_RE.fullmatch(attributes["credential_ref"])
        ):
            errors.append("attributes.credential_ref must be an opaque reference")
        if "prior_target_boot_id" in attributes and (
            not isinstance(attributes["prior_target_boot_id"], str)
            or not BOOT_ID_RE.fullmatch(attributes["prior_target_boot_id"])
        ):
            errors.append("attributes.prior_target_boot_id is invalid")
        for number_field in ("distance_mm", "duration_ms", "relay_hold_ms", "queue_depth"):
            if number_field in attributes and (
                isinstance(attributes[number_field], bool)
                or not isinstance(attributes[number_field], int)
                or attributes[number_field] < 0
            ):
                errors.append(f"attributes.{number_field} must be an integer >= 0")
        if "progress_percent" in attributes and (
            isinstance(attributes["progress_percent"], bool)
            or not isinstance(attributes["progress_percent"], (int, float))
            or not 0 <= attributes["progress_percent"] <= 100
        ):
            errors.append("attributes.progress_percent must be between 0 and 100")

    if event["session_kind"] == "update":
        update = event.get("update")
        if not isinstance(update, dict) or set(update) != UPDATE_FIELDS:
            errors.append("update session requires the complete update object")
        else:
            if update["component"] not in {"mobile", "target"}:
                errors.append("update.component is invalid")
            for field in ("current_version", "target_version"):
                if not isinstance(update[field], str) or not VERSION_RE.fullmatch(update[field]):
                    errors.append(f"update.{field} is invalid")
            digest = update["artifact_sha256"]
            if digest is not None and (
                not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
            ):
                errors.append("update.artifact_sha256 must be lowercase SHA-256 or null")
            if update["confirmation"] not in UPDATE_CONFIRMATIONS:
                errors.append("update.confirmation is invalid")
            if event["event_code"] in DIGEST_REQUIRED_EVENTS and digest is None:
                errors.append("event requires update.artifact_sha256")
    elif "update" in event:
        errors.append("access event must not contain update")

    errors.extend(_privacy_errors(event))
    if errors:
        raise EventValidationError(errors)


def _canonical(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def deduplicate_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_event_id: dict[str, dict[str, Any]] = {}
    by_position: dict[tuple[str, str, int], dict[str, Any]] = {}
    for event in events:
        event_id = event["event_id"]
        position = (
            event["source_instance_id"],
            event["source_boot_id"],
            event["sequence"],
        )
        prior_id = by_event_id.get(event_id)
        if prior_id is not None:
            if _canonical(prior_id) != _canonical(event):
                raise EventValidationError([f"event_id conflict: {event_id}"])
            continue
        prior_position = by_position.get(position)
        if prior_position is not None:
            raise EventValidationError(
                [
                    "sequence conflict for "
                    f"{position[0]}/{position[1]}/{position[2]}: "
                    f"{prior_position['event_id']} vs {event_id}"
                ]
            )
        by_event_id[event_id] = copy.deepcopy(event)
        by_position[position] = event
    return list(by_event_id.values())


def validate_stream(
    events: Iterable[dict[str, Any]], *, strict_causation: bool = True
) -> list[dict[str, Any]]:
    catalog = load_catalog()
    raw_events = list(events)
    for index, event in enumerate(raw_events):
        try:
            validate_event(event, catalog)
        except EventValidationError as error:
            raise EventValidationError(
                [f"event[{index}] {message}" for message in error.errors]
            ) from error
    unique = deduplicate_events(raw_events)
    by_id = {event["event_id"]: event for event in unique}
    errors: list[str] = []

    source_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in unique:
        source_groups[(event["source_instance_id"], event["source_boot_id"])].append(event)
        cause = event["causation_event_id"]
        if cause is not None and cause not in by_id and strict_causation:
            errors.append(f"missing causation event {cause} for {event['event_id']}")
        elif cause is not None and cause in by_id:
            if by_id[cause]["session_id"] != event["session_id"]:
                errors.append(f"causation crosses session boundary at {event['event_id']}")
            if by_id[cause]["attempt"] > event["attempt"]:
                errors.append(f"attempt regressed across causation at {event['event_id']}")

    for source_key, group in source_groups.items():
        ordered = sorted(group, key=lambda value: value["sequence"])
        last_monotonic = -1
        last_attempt = 0
        for event in ordered:
            monotonic_ms = event["clock"]["monotonic_ms"]
            if monotonic_ms < last_monotonic:
                errors.append(
                    "monotonic clock regressed for "
                    f"{source_key[0]}/{source_key[1]} at sequence {event['sequence']}"
                )
            last_monotonic = monotonic_ms
            if event["attempt"] < last_attempt:
                errors.append(
                    "attempt regressed for "
                    f"{source_key[0]}/{source_key[1]} at sequence {event['sequence']}"
                )
            last_attempt = event["attempt"]

    sessions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in unique:
        sessions[event["session_id"]].append(event)
    for session_id, group in sessions.items():
        kinds = {event["session_kind"] for event in group}
        if len(kinds) != 1:
            errors.append(f"session {session_id} mixes session_kind values")
        terminal = [
            event
            for event in group
            if catalog["event_codes"][event["event_code"]]["terminal"]
        ]
        if len(terminal) != 1:
            errors.append(f"session {session_id} must have exactly one terminal event")
        if group[0]["session_kind"] == "update":
            components = {event["update"]["component"] for event in group}
            target_versions = {event["update"]["target_version"] for event in group}
            artifact_digests = {
                event["update"]["artifact_sha256"]
                for event in group
                if event["update"]["artifact_sha256"] is not None
            }
            if len(components) != 1:
                errors.append(f"update session {session_id} mixes components")
            if len(target_versions) != 1:
                errors.append(f"update session {session_id} changes target_version")
            if len(artifact_digests) > 1:
                errors.append(f"update session {session_id} changes artifact_sha256")
            if artifact_digests:
                for event in group:
                    if (
                        event["event_code"] == "UPDATE_SESSION_FAILED"
                        and event["update"]["artifact_sha256"] is None
                    ):
                        errors.append(
                            f"update session {session_id} drops artifact_sha256 "
                            "at terminal failure"
                        )

    edges: dict[str, set[str]] = defaultdict(set)
    indegree = {event_id: 0 for event_id in by_id}
    for event in unique:
        cause = event["causation_event_id"]
        if cause is not None and cause in by_id:
            edges[cause].add(event["event_id"])
    for group in source_groups.values():
        ordered = sorted(group, key=lambda value: value["sequence"])
        for left, right in zip(ordered, ordered[1:]):
            edges[left["event_id"]].add(right["event_id"])
    for children in edges.values():
        for child in children:
            indegree[child] += 1
    pending = [event_id for event_id, degree in indegree.items() if degree == 0]
    visited = 0
    while pending:
        current = pending.pop()
        visited += 1
        for child in edges[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                pending.append(child)
    if visited != len(by_id):
        errors.append("causation/sequence graph contains a cycle")

    if errors:
        raise EventValidationError(errors)
    return unique


def order_events(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a deterministic topological order without inventing clock order."""
    unique = validate_stream(events)
    by_id = {event["event_id"]: event for event in unique}
    edges: dict[str, set[str]] = defaultdict(set)
    indegree = {event_id: 0 for event_id in by_id}

    source_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in unique:
        source_groups[(event["source_instance_id"], event["source_boot_id"])].append(event)
        cause = event["causation_event_id"]
        if cause is not None:
            edges[cause].add(event["event_id"])

    for group in source_groups.values():
        ordered = sorted(group, key=lambda value: value["sequence"])
        for left, right in zip(ordered, ordered[1:]):
            edges[left["event_id"]].add(right["event_id"])

    for children in edges.values():
        for child in children:
            indegree[child] += 1

    def tie_breaker(event_id: str) -> tuple[Any, ...]:
        event = by_id[event_id]
        clock = event["clock"]
        if clock["quality"] == "SYNCED" and clock["wall_time"] is not None:
            return (0, _parse_wall_time(clock["wall_time"]), event_id)
        return (
            1,
            event["source_instance_id"],
            event["source_boot_id"],
            event["sequence"],
            event_id,
        )

    ready: list[tuple[tuple[Any, ...], str]] = []
    for event_id, degree in indegree.items():
        if degree == 0:
            heapq.heappush(ready, (tie_breaker(event_id), event_id))

    ordered_ids: list[str] = []
    while ready:
        _, event_id = heapq.heappop(ready)
        ordered_ids.append(event_id)
        for child in sorted(edges[event_id]):
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, (tie_breaker(child), child))
    if len(ordered_ids) != len(by_id):
        raise EventValidationError(["causation/sequence graph contains a cycle"])
    return [by_id[event_id] for event_id in ordered_ids]


def _causally_precedes(
    left_id: str, right_id: str, events: Iterable[dict[str, Any]]
) -> bool:
    if left_id == right_id:
        return True
    event_list = list(events)
    edges: dict[str, set[str]] = defaultdict(set)
    source_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in event_list:
        source_groups[(event["source_instance_id"], event["source_boot_id"])].append(event)
        cause = event["causation_event_id"]
        if cause is not None:
            edges[cause].add(event["event_id"])
    for group in source_groups.values():
        source_order = sorted(group, key=lambda value: value["sequence"])
        for left, right in zip(source_order, source_order[1:]):
            edges[left["event_id"]].add(right["event_id"])
    pending = [left_id]
    seen = {left_id}
    while pending:
        current = pending.pop()
        for child in edges[current]:
            if child == right_id:
                return True
            if child not in seen:
                seen.add(child)
                pending.append(child)
    return False


def _required_causal_chain(
    required_codes: list[str], ordered: list[dict[str, Any]]
) -> tuple[list[str], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    cursor = 0
    for event in ordered:
        if cursor < len(required_codes) and event["event_code"] == required_codes[cursor]:
            selected.append(event)
            cursor += 1
    missing = required_codes[cursor:]
    if not missing:
        for left, right in zip(selected, selected[1:]):
            if not _causally_precedes(left["event_id"], right["event_id"], ordered):
                return [f"causal edge {left['event_code']} -> {right['event_code']}"], selected
    return missing, selected


def evaluate_access_session(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = order_events(events)
    if not ordered or any(event["session_kind"] != "access" for event in ordered):
        raise EventValidationError(["expected one access session"])
    session_ids = {event["session_id"] for event in ordered}
    if len(session_ids) != 1:
        raise EventValidationError(["expected one session_id"])

    codes = [event["event_code"] for event in ordered]
    terminal = ordered[-1] if ordered[-1]["stage"] == "COMPLETE" else next(
        event for event in ordered if event["stage"] == "COMPLETE"
    )
    relay_on = codes.count("ACCESS_RELAY_ON")
    relay_off = codes.count("ACCESS_RELAY_OFF")
    errors: list[str] = []
    if relay_on > 1:
        errors.append("access session may activate relay at most once")
    if relay_on != relay_off:
        errors.append("every relay activation must have one relay-off event")
    if relay_on and any(
        code in {"ACCESS_PROOF_REJECTED", "ACCESS_ACL_REJECTED"} for code in codes
    ):
        errors.append("proof/ACL rejection must never activate relay")

    target_events = [
        event for event in ordered if event["source_component"] == "target"
    ]
    target_boots = {
        event["target"]["boot_id"]
        for event in target_events
    }
    is_reset_terminal = (
        terminal["event_code"] == "ACCESS_SESSION_TERMINATED"
        and terminal["reason_code"] == "RESET_DURING_SESSION"
    )
    if len(target_boots) > 1 and not is_reset_terminal:
        errors.append("target boot changed without RESET_DURING_SESSION termination")
    if is_reset_terminal:
        prior_boot_id = terminal["attributes"].get("prior_target_boot_id")
        prior_target_events = [
            event
            for event in target_events
            if event["source_boot_id"] != terminal["source_boot_id"]
        ]
        actual_prior_target = prior_target_events[-1] if prior_target_events else None
        cause = next(
            (
                event
                for event in ordered
                if event["event_id"] == terminal["causation_event_id"]
            ),
            None,
        )
        if terminal["source_component"] != "target":
            errors.append("reset terminal must be emitted by the new target boot")
        if cause is None or cause["source_component"] != "target":
            errors.append(
                "reset terminal must directly reference the prior target event"
            )
        else:
            if prior_boot_id != cause["source_boot_id"]:
                errors.append("prior_target_boot_id does not match prior target boot")
            if (
                actual_prior_target is None
                or cause["event_id"] != actual_prior_target["event_id"]
            ):
                errors.append(
                    "reset terminal must directly reference the last prior target event"
                )
            if cause["target"]["target_ref"] != terminal["target"]["target_ref"]:
                errors.append("reset terminal target_ref does not match prior target")
            if cause["source_boot_id"] == terminal["source_boot_id"]:
                errors.append("reset terminal must be emitted from a new target boot")
        if len(target_boots) != 2:
            errors.append(
                "reset session must contain exactly one prior and one new target boot"
            )

    if terminal["event_code"] == "ACCESS_SESSION_COMPLETED":
        path = next(
            (
                event["attributes"].get("path")
                for event in ordered
                if event["attributes"].get("path")
            ),
            "local_gatt",
        )
        if path == "local_gatt":
            required = [
                "ACCESS_SESSION_STARTED",
                "ACCESS_WAKE_DETECTED",
                "ACCESS_GATT_CONNECT_STARTED",
                "ACCESS_GATT_CONNECTED",
                "ACCESS_PROOF_REQUESTED",
                "ACCESS_PROOF_VERIFIED",
                "ACCESS_ACL_ACCEPTED",
                "ACCESS_ARMED",
                "ACCESS_SENSOR_DETECTED",
                "ACCESS_RELAY_ON",
                "ACCESS_RELAY_OFF",
                "ACCESS_SESSION_COMPLETED",
            ]
        elif path == "legacy_mqtt":
            required = [
                "ACCESS_SESSION_STARTED",
                "ACCESS_WAKE_DETECTED",
                "ACCESS_BACKEND_REQUESTED",
                "ACCESS_BACKEND_AUTHORIZED",
                "ACCESS_ARM_PUBLISHED",
                "ACCESS_ARM_RECEIVED",
                "ACCESS_ARMED",
                "ACCESS_SENSOR_DETECTED",
                "ACCESS_RELAY_ON",
                "ACCESS_RELAY_OFF",
                "ACCESS_SESSION_COMPLETED",
            ]
        else:
            required = [
                "ACCESS_SESSION_STARTED",
                "ACCESS_RELAY_ON",
                "ACCESS_RELAY_OFF",
                "ACCESS_SESSION_COMPLETED",
            ]
        missing, _ = _required_causal_chain(required, ordered)
        if missing:
            errors.append(f"successful {path} path is missing ordered required events")
    if errors:
        raise EventValidationError(errors)
    return {
        "session_id": ordered[0]["session_id"],
        "passed": True,
        "terminal_event_code": terminal["event_code"],
        "terminal_reason_code": terminal["reason_code"],
        "event_count": len(ordered),
    }


def evaluate_update_session(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = order_events(events)
    if not ordered or any(event["session_kind"] != "update" for event in ordered):
        raise EventValidationError(["expected one update session"])
    session_ids = {event["session_id"] for event in ordered}
    if len(session_ids) != 1:
        raise EventValidationError(["expected one session_id"])

    codes = [event["event_code"] for event in ordered]
    terminal = next(event for event in ordered if event["stage"] == "COMPLETE")
    errors: list[str] = []
    if terminal["event_code"] == "UPDATE_SESSION_COMPLETED":
        component = terminal["update"]["component"]
        if terminal["reason_code"] == "ROLLBACK_COMPLETED":
            required = [
                "UPDATE_SESSION_STARTED",
                "UPDATE_ROLLBACK_STARTED",
                "UPDATE_ROLLBACK_PREVIOUS_INSTALL_CONFIRMED",
                "UPDATE_ROLLBACK_PREVIOUS_BOOT_CONFIRMED",
                "UPDATE_ROLLBACK_PREVIOUS_HEALTH_CONFIRMED",
                "UPDATE_ROLLBACK_CONFIRMED",
                "UPDATE_SESSION_COMPLETED",
            ]
        elif component == "target":
            required = [
                "UPDATE_SESSION_STARTED",
                "UPDATE_MANIFEST_CHECK_STARTED",
                "UPDATE_MANIFEST_VERIFIED",
                "UPDATE_DOWNLOAD_STARTED",
                "UPDATE_ARTIFACT_VERIFIED",
                "UPDATE_INSTALL_STARTED",
                "UPDATE_INSTALLED",
                "UPDATE_REBOOT_REQUESTED",
                "UPDATE_BOOT_CONFIRMED",
                "UPDATE_HEALTH_CONFIRMED",
                "UPDATE_MARKED_VALID",
            ]
            install_boots = {
                event["target"]["boot_id"]
                for event in ordered
                if event["event_code"] == "UPDATE_INSTALLED"
            }
            boot_confirmed = {
                event["target"]["boot_id"]
                for event in ordered
                if event["event_code"] == "UPDATE_BOOT_CONFIRMED"
            }
            if install_boots & boot_confirmed:
                errors.append("target OTA boot confirmation must use a new target boot_id")
        else:
            required = [
                "UPDATE_SESSION_STARTED",
                "UPDATE_MANIFEST_CHECK_STARTED",
                "UPDATE_MANIFEST_VERIFIED",
                "UPDATE_DOWNLOAD_STARTED",
                "UPDATE_ARTIFACT_VERIFIED",
                "UPDATE_INSTALL_STARTED",
                "UPDATE_INSTALLED",
                "UPDATE_HEALTH_CONFIRMED",
            ]
        missing, _ = _required_causal_chain(required, ordered)
        if missing:
            errors.append(
                f"completed update is missing ordered stages: {', '.join(missing)}"
            )
        if terminal["reason_code"] == "ROLLBACK_COMPLETED" and not missing:
            start = next(
                event
                for event in ordered
                if event["event_code"] == "UPDATE_SESSION_STARTED"
            )
            previous_version = start["update"]["current_version"]
            rollback_evidence_codes = {
                "UPDATE_ROLLBACK_PREVIOUS_INSTALL_CONFIRMED": "INSTALLED",
                "UPDATE_ROLLBACK_PREVIOUS_BOOT_CONFIRMED": "BOOTED",
                "UPDATE_ROLLBACK_PREVIOUS_HEALTH_CONFIRMED": "HEALTH_CONFIRMED",
                "UPDATE_ROLLBACK_CONFIRMED": "ROLLED_BACK",
                "UPDATE_SESSION_COMPLETED": "ROLLED_BACK",
            }
            for event in ordered:
                expected_confirmation = rollback_evidence_codes.get(event["event_code"])
                if expected_confirmation is None:
                    continue
                if event["update"]["current_version"] != previous_version:
                    errors.append(
                        f"{event['event_code']} does not confirm previous version "
                        f"{previous_version}"
                    )
                if event["update"]["confirmation"] != expected_confirmation:
                    errors.append(
                        f"{event['event_code']} must use confirmation "
                        f"{expected_confirmation}"
                    )
            if previous_version == terminal["update"]["target_version"]:
                errors.append(
                    "rollback previous version must differ from failed target_version"
                )
            if component == "target":
                rollback_start = next(
                    event
                    for event in ordered
                    if event["event_code"] == "UPDATE_ROLLBACK_STARTED"
                )
                previous_boot = next(
                    event
                    for event in ordered
                    if event["event_code"] == "UPDATE_ROLLBACK_PREVIOUS_BOOT_CONFIRMED"
                )
                if rollback_start["source_boot_id"] == previous_boot["source_boot_id"]:
                    errors.append(
                        "target rollback boot evidence must use a new target boot_id"
                    )
                recovery_evidence = [
                    event
                    for event in ordered
                    if event["event_code"] in rollback_evidence_codes
                ]
                if any(
                    event["source_component"] != "target"
                    for event in recovery_evidence
                ):
                    errors.append(
                        "target rollback evidence must be emitted by the target"
                    )
                recovery_boots = {
                    event["source_boot_id"] for event in recovery_evidence
                }
                if len(recovery_boots) != 1:
                    errors.append(
                        "target rollback evidence must use one recovery boot_id"
                    )
                recovery_targets = {
                    event["target"]["target_ref"] for event in recovery_evidence
                }
                if recovery_targets != {rollback_start["target"]["target_ref"]}:
                    errors.append(
                        "target rollback evidence must match the failed target_ref"
                    )
        if terminal["update"]["confirmation"] not in {"HEALTH_CONFIRMED", "ROLLED_BACK"}:
            errors.append("completed update lacks health or rollback confirmation")
    if errors:
        raise EventValidationError(errors)
    return {
        "session_id": ordered[0]["session_id"],
        "passed": True,
        "terminal_event_code": terminal["event_code"],
        "terminal_reason_code": terminal["reason_code"],
        "event_count": len(ordered),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "order", "evaluate"))
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    try:
        for path in args.files:
            events = load_jsonl(path)
            if args.command == "validate":
                validated = validate_stream(events)
                print(f"{path}: valid ({len(validated)} unique events)")
            elif args.command == "order":
                for event in order_events(events):
                    print(json.dumps(event, ensure_ascii=False, sort_keys=True))
            else:
                unique = validate_stream(events)
                kind = unique[0]["session_kind"] if unique else None
                if kind == "access":
                    result = evaluate_access_session(unique)
                elif kind == "update":
                    result = evaluate_update_session(unique)
                else:
                    raise EventValidationError(["fixture is empty"])
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except EventValidationError as error:
        for message in error.errors:
            print(f"ERROR: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
