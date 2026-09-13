"""Strict, privacy-safe mobile field diagnostic contract and classifier."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Code = str


def sensor_observation(document: dict) -> dict | None:
    """Optional latest sensor telemetry, never authentication or passage proof."""
    counters = ("sensor_samples", "sensor_valid_samples", "sensor_timeouts", "sensor_invalid_samples")
    distances = ("sensor_min_cm", "sensor_max_cm")
    if not all(type(document.get(key)) is int and 0 <= document[key] <= 0xffffffff for key in counters):
        return None
    if not all(type(document.get(key)) in (int, float) and 0 <= document[key] <= 999 for key in distances):
        return None
    if type(document.get("sensor_rearm_blocked")) is not bool:
        return None
    if document["sensor_samples"] != sum(document[key] for key in counters[1:]):
        return None
    return {key: document[key] for key in (*counters, *distances, "sensor_rearm_blocked")}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AppSnapshot(StrictModel):
    version: str = Field(min_length=1, max_length=32)
    build: str = Field(min_length=1, max_length=32)
    android_sdk: Optional[int] = Field(default=None, ge=21, le=1000)


class IdentitySnapshot(StrictModel):
    enrollment_state: Code = Field(pattern=r"^[a-z_]{1,32}$")
    access_ready: bool
    door_count: int = Field(ge=0, le=64)
    target_synced: bool
    acl_version: Optional[int] = Field(default=None, ge=0)


class ScanLifecycleSnapshot(StrictModel):
    event: Literal["REGISTER_REQUESTED", "REGISTER_ACCEPTED", "REGISTER_FAILED",
                   "STOP_REQUESTED", "INVALIDATED", "CALLBACK_ERROR",
                   "RECOVERY_ATTEMPT", "RECOVERY_EXHAUSTED"]
    at_epoch_ms: int = Field(ge=0, strict=True)
    error_code: Optional[int] = Field(default=None, ge=0, le=65535, strict=True)


class ScanSnapshot(StrictModel):
    observation: Literal["NOT_OBSERVED", "CLOCK_UNCERTAIN", "RECENT_PACKET", "NO_RECENT_PACKET"]
    last_packet_at_epoch_ms: Optional[int] = Field(default=None, ge=1, strict=True)
    lifecycle: list[ScanLifecycleSnapshot] = Field(max_length=32)
    # Optional counters describe observed boundaries, never radio health.
    callback_count: Optional[int] = Field(default=None, ge=0, strict=True)
    empty_callback_count: Optional[int] = Field(default=None, ge=0, strict=True)
    result_count: Optional[int] = Field(default=None, ge=0, strict=True)
    filter_match_count: Optional[int] = Field(default=None, ge=0, strict=True)
    fresh_match_count: Optional[int] = Field(default=None, ge=0, strict=True)
    stale_match_count: Optional[int] = Field(default=None, ge=0, strict=True)
    missing_ready_hint_count: Optional[int] = Field(default=None, ge=0, strict=True)
    malformed_ready_hint_count: Optional[int] = Field(default=None, ge=0, strict=True)
    target_not_ready_count: Optional[int] = Field(default=None, ge=0, strict=True)
    callback_error_count: Optional[int] = Field(default=None, ge=0, strict=True)
    dispatch_attempt_count: Optional[int] = Field(default=None, ge=0, strict=True)
    dispatch_enqueued_count: Optional[int] = Field(default=None, ge=0, strict=True)
    dispatch_skipped_count: Optional[int] = Field(default=None, ge=0, strict=True)
    owner_wait_count: Optional[int] = Field(default=None, ge=0, strict=True)
    enqueue_failure_count: Optional[int] = Field(default=None, ge=0, strict=True)
    last_callback_at_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    last_error_at_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    last_error_code: Optional[int] = Field(default=None, ge=0, le=65535, strict=True)
    last_dispatch_at_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    last_dispatch_reason: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9_]{1,64}$")
    recovery_started_at_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    recovery_deadline_at_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    recovery_finished_at_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    recovery_reason: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9_]{1,64}$")
    recovery_outcome: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9_]{1,64}$")


class RuntimeLifecycleSnapshot(StrictModel):
    sequence: Optional[int] = Field(default=None, ge=0, strict=True)
    event: str = Field(pattern=r"^[A-Z0-9_]{1,64}$")
    at_epoch_ms: int = Field(ge=0, strict=True)
    elapsed_ms: int = Field(ge=0, strict=True)
    session_ref: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    reason: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9_]{1,64}$")
    ready: Optional[bool] = Field(default=None, strict=True)
    ready_epoch: Optional[int] = Field(default=None, ge=0, le=0xffffffff, strict=True)
    status: Optional[int] = Field(default=None, ge=-1, le=65535, strict=True)
    incident_ref: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{16}$")


class RuntimeSnapshot(StrictModel):
    captured_epoch_ms: int = Field(ge=0, strict=True)
    captured_elapsed_ms: int = Field(ge=0, strict=True)
    process_ref: str = Field(pattern=r"^[0-9a-f]{16}$")
    pending_uploads: int = Field(ge=0, le=1, strict=True)
    oldest_pending_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    last_upload_success_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    last_upload_code: Optional[str] = Field(default=None, pattern=r"^[A-Z0-9_]{1,64}$")
    dropped_events: int = Field(ge=0, le=0xffffffff, strict=True)
    lifecycle: list[RuntimeLifecycleSnapshot] = Field(max_length=64)
    background_restricted: Optional[bool] = Field(default=None, strict=True)
    battery_optimization_exempt: Optional[bool] = Field(default=None, strict=True)
    device_idle: Optional[bool] = Field(default=None, strict=True)
    app_standby_bucket: Optional[int] = Field(default=None, ge=0, le=100, strict=True)
    previous_exit_reason: Optional[int] = Field(default=None, ge=0, le=255, strict=True)
    previous_exit_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    last_start_was_force_stopped: Optional[bool] = Field(default=None, strict=True)
    event_first_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    event_last_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    pending_events: Optional[int] = Field(default=None, ge=0, le=256, strict=True)
    last_enqueue_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    last_worker_start_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    last_worker_stop_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    last_upload_attempt_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    next_attempt_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    upload_attempt: Optional[int] = Field(default=None, ge=0, strict=True)
    upload_state: Optional[Literal[
        "DISABLED", "AUTH_REQUIRED", "UPLOADING", "RETRY_WAIT", "QUEUED",
        "NOT_UPLOADED", "STALE", "ACKNOWLEDGED",
    ]] = None
    journal_dropped: Optional[int] = Field(default=None, ge=0, strict=True)
    ring_dropped: Optional[int] = Field(default=None, ge=0, strict=True)
    export_trimmed: Optional[int] = Field(default=None, ge=0, strict=True)
    quarantined_count: Optional[int] = Field(default=None, ge=0, le=4, strict=True)
    quarantined_dropped: Optional[int] = Field(default=None, ge=0, strict=True)
    ring_drop_first_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    ring_drop_last_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    generation: Optional[int] = Field(default=None, ge=0, strict=True)
    latest_snapshot: Optional[bool] = Field(default=None, strict=True)
    incident_ref: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{16}$")

class NativeSnapshot(StrictModel):
    scan: Optional[ScanSnapshot] = None
    runtime: Optional[RuntimeSnapshot] = None

    @field_validator("stage", "wake_registration_status", mode="before")
    @classmethod
    def legacy_native_code(cls, value: Any) -> Any:
        # Existing mobile v2 producers use Dart enum names (lower/camel case).
        # Normalize only bounded ASCII codes, never arbitrary text or secrets.
        if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            return value.upper()
        return value

    healthy: Optional[bool] = None
    hands_free_ready: Optional[bool] = None
    wake_registered: Optional[bool] = None
    wake_registration_requested: Optional[bool] = None
    wake_registration_reconciled: Optional[bool] = None
    wake_registration_status: Optional[Code] = Field(
        default=None, pattern=r"^[A-Z0-9_-]{1,64}$"
    )
    wake_registration_attempted_at_epoch_ms: Optional[int] = Field(default=None, ge=0)
    wake_registration_reconciled_at_epoch_ms: Optional[int] = Field(default=None, ge=0)
    wake_registration_last_callback_at_epoch_ms: Optional[int] = Field(default=None, ge=0)
    initial_work_expedited: Optional[bool] = None
    stage: Optional[Code] = Field(default=None, pattern=r"^[A-Z0-9_-]{1,64}$")
    reason: Optional[Code] = Field(default=None, pattern=r"^[A-Z0-9_-]{1,64}$")
    presence_to_dispatch_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    presence_to_armed_ms: Optional[int] = Field(default=None, ge=0, le=3600000)


class FieldTestSnapshot(StrictModel):
    ref: str = Field(pattern=r"^[0-9a-f]{16}$")
    created_at: str = Field(max_length=40)
    expires_at: str = Field(max_length=40)
    active: bool

    @model_validator(mode="after")
    def bounded_utc_window(self) -> "FieldTestSnapshot":
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            expires = datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("field-test timestamps must be ISO-8601") from exc
        utc_offset = timezone.utc.utcoffset(None)
        if created.utcoffset() != utc_offset or expires.utcoffset() != utc_offset:
            raise ValueError("field-test timestamps must be UTC")
        duration = (expires - created).total_seconds()
        if not 60 <= duration <= 1800:
            raise ValueError("field-test window must be between 1 and 30 minutes")
        return self


class GattPerformance(StrictModel):
    connect_setup_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    negotiation_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    challenge_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    signing_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    proof_write_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    result_wait_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    negotiated_mtu: Optional[int] = Field(default=None, ge=0, le=517)
    mtu_status: Optional[Code] = Field(default=None, pattern=r"^[A-Z0-9_-]{1,64}$")
    high_priority_requested: bool = False


class SessionSnapshot(StrictModel):
    event_ref: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    created_epoch_ms: Optional[int] = Field(default=None, ge=0)
    updated_epoch_ms: Optional[int] = Field(default=None, ge=0)
    attempt: Optional[int] = Field(default=None, ge=0, le=100)
    state: Optional[Code] = Field(default=None, pattern=r"^[A-Z0-9_-]{1,64}$")
    reason_code: Optional[Code] = Field(default=None, pattern=r"^[A-Z0-9_-]{1,64}$")
    target_reason_code: Optional[int] = Field(default=None, ge=0, le=65535)
    target_reason_name: Optional[Code] = Field(default=None, pattern=r"^[A-Z0-9_-]{1,64}$")
    transport_reason: Optional[Code] = Field(default=None, pattern=r"^[A-Z0-9_-]{1,64}$")
    transport_status: Optional[int] = Field(default=None, ge=-1, le=65535)
    retry_after_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    scheduled_retry_delay_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    latency_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    dispatch_started_epoch_ms: Optional[int] = Field(default=None, ge=0)
    presence_to_dispatch_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    presence_to_armed_ms: Optional[int] = Field(default=None, ge=0, le=3600000)
    active_acl_version: Optional[int] = Field(default=None, ge=0)
    target_session_id: Optional[str] = Field(
        default=None,
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    )
    gatt_performance: Optional[GattPerformance] = None


class WakeSnapshot(StrictModel):
    @field_validator("strongest_rssi", mode="before")
    @classmethod
    def unknown_rssi(cls, value: Any) -> Any:
        # Legacy reports preserve the radio's unavailable sentinel. Do not
        # interpret it as signal strength or widen the valid measurement range.
        return None if type(value) is int and value == 127 else value

    source: Optional[Code] = Field(default=None, pattern=r"^[A-Z0-9_-]{1,64}$")
    process_ref: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{16}$")
    success: bool
    received_epoch_ms: Optional[int] = Field(default=None, ge=0)
    received_elapsed_ms: Optional[int] = Field(default=None, ge=0)
    callback_latency_ms: Optional[float] = Field(default=None, ge=0, le=3600000)
    strongest_rssi: Optional[int] = Field(default=None, ge=-127, le=20)
    screen_interactive: bool
    result_count: Optional[int] = Field(default=None, ge=0, le=128)
    callback_type: Optional[int] = Field(default=None, ge=0, le=65535)
    error_code: Optional[int] = Field(default=None, ge=0, le=65535)


class MobileDiagnosticBundle(StrictModel):
    schema_: Literal["sgk-mobile-support-v2"] = Field(alias="schema")
    bundle_ref: str = Field(pattern=r"^[0-9a-f]{32}$")
    created_at: str = Field(max_length=40)
    app: AppSnapshot
    identity: IdentitySnapshot
    native: NativeSnapshot
    field_test: Optional[FieldTestSnapshot] = None
    sessions: list[SessionSnapshot] = Field(max_length=50)
    wake_events: list[WakeSnapshot] = Field(max_length=100)

    @field_validator("created_at")
    @classmethod
    def utc_timestamp(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("created_at must be an ISO-8601 UTC timestamp") from None
        if parsed.utcoffset() != timezone.utc.utcoffset(None) or parsed.year < 1970:
            raise ValueError("created_at must be UTC")
        return value


def ingest_bundle_payload(bundle: MobileDiagnosticBundle) -> dict[str, Any]:
    """Keep pre-extension default serialization stable for in-flight N-1 retries.

    Older ingesters populated defaults for the original schema2 fields. Keep
    those defaults, but never inject newly introduced NULL fields into an old
    immutable bundle identity. Explicit optional NULLs from new apps survive.
    """
    body = bundle.model_dump(by_alias=True, mode="json")
    scan = bundle.native.scan
    if scan is None:
        body["native"].pop("scan", None)
    else:
        for field in ScanSnapshot.model_fields.keys() - {"observation", "last_packet_at_epoch_ms", "lifecycle"}:
            if field not in scan.model_fields_set:
                body["native"]["scan"].pop(field, None)
    runtime = bundle.native.runtime
    if runtime is not None:
        legacy = {"captured_epoch_ms", "captured_elapsed_ms", "process_ref", "pending_uploads",
                  "oldest_pending_epoch_ms", "last_upload_success_epoch_ms", "last_upload_code", "dropped_events",
                  "lifecycle", "background_restricted", "battery_optimization_exempt", "device_idle", "app_standby_bucket",
                  "previous_exit_reason", "previous_exit_epoch_ms", "last_start_was_force_stopped"}
        for field in RuntimeSnapshot.model_fields.keys() - legacy:
            if field not in runtime.model_fields_set:
                body["native"]["runtime"].pop(field, None)
        for model, row in zip(runtime.lifecycle, body["native"]["runtime"]["lifecycle"]):
            for field in ("sequence", "incident_ref"):
                if field not in model.model_fields_set:
                    row.pop(field, None)
    return body


class TargetDiagnosticBaseline(StrictModel):
    fresh: bool = Field(strict=True)
    observed_epoch_ms: Optional[int] = Field(default=None, ge=0, strict=True)
    state: Optional[Literal["IDLE", "AUTH_PENDING", "ARMED", "RELAY_HOLD", "COOLDOWN"]] = None
    relay_commanded_on: Optional[bool] = Field(default=None, strict=True)

    @model_validator(mode="after")
    def freshness_has_observation(self) -> "TargetDiagnosticBaseline":
        if self.fresh and (self.observed_epoch_ms is None or self.state is None or self.relay_commanded_on is None):
            raise ValueError("fresh baseline requires a complete signed observation")
        if not self.fresh:
            self.observed_epoch_ms = self.state = self.relay_commanded_on = None
        return self


def bundle_event_bounds(bundle: dict[str, Any]) -> tuple[int | None, int | None]:
    """Index included evidence, independently of capture/export/receipt times.

    Legacy bundles have no declared range; derive it from their bounded arrays.
    Neither an empty report nor a capture timestamp invents an event.
    """
    native = bundle.get("native") or {}
    runtime, scan = native.get("runtime") or {}, native.get("scan") or {}
    times = [runtime.get("event_first_epoch_ms"), runtime.get("event_last_epoch_ms")]
    times += [item.get("at_epoch_ms") for item in runtime.get("lifecycle", [])]
    times += [item.get("at_epoch_ms") for item in scan.get("lifecycle", [])]
    times += [scan.get("last_packet_at_epoch_ms")]
    times += [item.get("received_epoch_ms") for item in bundle.get("wake_events", [])]
    for item in bundle.get("sessions", []):
        times += [item.get(key) for key in ("created_epoch_ms", "updated_epoch_ms", "dispatch_started_epoch_ms")]
    # BIGINT UNSIGNED index ceiling; valid but unindexable clocks stay in the
    # explicit legacy/unindexed fallback and remain available by mobile cursor.
    known = [value for value in times if type(value) is int and value >= 0]
    return (min(known), max(known)) if known else (None, None)


def bundle_evidence_metadata(bundle: dict[str, Any], created_at_ms: int,
                             received_at: datetime, *, as_of_ms: int) -> dict[str, Any]:
    """Truthful report freshness and upload snapshot, not an access verdict."""
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    received_ms = int(received_at.timestamp() * 1000)
    runtime = (bundle.get("native") or {}).get("runtime") or {}
    captured = runtime.get("captured_epoch_ms", created_at_ms)
    first, last = bundle_event_bounds(bundle)
    clock_uncertain = (captured > received_ms + 60000 or created_at_ms > received_ms + 60000
                       or captured > as_of_ms or (last is not None and last > captured + 60000)
                       or (runtime.get("event_first_epoch_ms") is not None
                           and runtime.get("event_last_epoch_ms") is not None
                           and runtime["event_first_epoch_ms"] > runtime["event_last_epoch_ms"]))
    age = as_of_ms - captured
    freshness = "CLOCK_UNCERTAIN" if clock_uncertain else "RECENT_REPORT" if age <= 300000 else "STALE_REPORT"
    if not clock_uncertain and runtime.get("latest_snapshot") is False:
        freshness = "HISTORICAL_EVIDENCE_ONLY"
    dropped = {key: runtime.get(key) for key in
               ("dropped_events", "journal_dropped", "ring_dropped", "export_trimmed", "quarantined_dropped")}
    reasons = []
    if freshness != "RECENT_REPORT":
        reasons.append(freshness)
    if any((value or 0) > 0 for value in dropped.values()):
        reasons.append("COLLECTION_LOSS_REPORTED")
    if (runtime.get("pending_events") or 0) > 0 or (runtime.get("pending_uploads") or 0) > 0:
        reasons.append("PENDING_AT_CAPTURE")
    if (runtime.get("quarantined_count") or 0) > 0:
        reasons.append("QUARANTINED_REPORTS")
    if not runtime:
        reasons.append("RUNTIME_NOT_REPORTED")
    oldest = runtime.get("oldest_pending_epoch_ms")
    return dict(
        report_created_epoch_ms=str(created_at_ms), captured_epoch_ms=str(captured),
        event_first_epoch_ms=str(first) if first is not None else None,
        event_last_epoch_ms=str(last) if last is not None else None,
        health_snapshot_epoch_ms=str(captured) if runtime.get("latest_snapshot") is not False else None,
        latest_snapshot=runtime.get("latest_snapshot"), snapshot_age_ms=age,
        freshness=freshness, clock_basis="PHONE_WALL_CLOCK_UNVERIFIED",
        received_at=received_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        server_storage_confirmed=True, receipt_is_current_health=False,
        capture_to_receipt_ms=received_ms - captured,
        gaps=reasons, loss_counters=dropped, loss_scope="CUMULATIVE_NOT_INCIDENT_LOSS",
        ring_drop_first_epoch_ms=runtime.get("ring_drop_first_epoch_ms"),
        ring_drop_last_epoch_ms=runtime.get("ring_drop_last_epoch_ms"),
        upload=dict(state=runtime.get("upload_state", "NOT_REPORTED"),
                    pending_uploads=runtime.get("pending_uploads"), pending_events=runtime.get("pending_events"),
                    oldest_pending_epoch_ms=oldest,
                    pending_age_at_capture_ms=(captured - oldest) if oldest is not None and oldest <= captured else None,
                    last_server_ack_epoch_ms=runtime.get("last_upload_success_epoch_ms"),
                    last_code=runtime.get("last_upload_code"), attempt=runtime.get("upload_attempt"),
                    last_enqueue_epoch_ms=runtime.get("last_enqueue_epoch_ms"),
                    last_worker_start_epoch_ms=runtime.get("last_worker_start_epoch_ms"),
                    last_worker_stop_epoch_ms=runtime.get("last_worker_stop_epoch_ms"),
                    last_upload_attempt_epoch_ms=runtime.get("last_upload_attempt_epoch_ms"),
                    next_attempt_epoch_ms=runtime.get("next_attempt_epoch_ms"),
                    quarantined_count=runtime.get("quarantined_count"),
                    values_are_capture_snapshot=True, next_attempt_is_os_guarantee=False),
    )


def classify_bundle(
    bundle: dict[str, Any],
    target_events: list[dict[str, Any]],
    *,
    now_ms: Optional[int] = None,
    target_controller: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Return only the last proven and first missing stage; never infer RF/door travel."""

    sessions = bundle.get("sessions") or []
    wakes = bundle.get("wake_events") or []
    marker = bundle.get("field_test")
    if marker:
        start_ms = int(
            datetime.fromisoformat(marker["created_at"].replace("Z", "+00:00")).timestamp()
            * 1000
        )
        end_ms = int(
            datetime.fromisoformat(marker["expires_at"].replace("Z", "+00:00")).timestamp()
            * 1000
        )
        sessions = [
            item
            for item in sessions
            if start_ms <= int(item.get("created_epoch_ms") or 0) <= end_ms
        ]
        wakes = [
            item
            for item in wakes
            if start_ms <= int(item.get("received_epoch_ms") or 0) <= end_ms
        ]
    if not wakes:
        if marker and (now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)) < end_ms:
            return {"last_stage": "FIELD_MARKER", "first_missing": "FIELD_WINDOW_OPEN"}
        manual_context = any(item.get("event") == "MANUAL_OPEN_CONTEXT" for item in
                             ((bundle.get("native") or {}).get("runtime") or {}).get("lifecycle", []))
        return {"last_stage": "MANUAL_OPEN_CONTEXT" if manual_context else "FIELD_MARKER" if marker else "MOBILE_SNAPSHOT",
                "first_missing": "PHONE_WAKE_NOT_OBSERVED"}
    if not sessions:
        return {"last_stage": "PHONE_WAKE", "first_missing": "ANDROID_DISPATCH_NOT_OBSERVED"}

    session = sessions[0]
    state = str(session.get("state") or "")
    reason = str(session.get("reason_code") or session.get("transport_reason") or "")
    target_session_id = session.get("target_session_id")
    if state in {"QUEUED", "RETRY_PENDING"}:
        return {"last_stage": "PHONE_WAKE", "first_missing": "ANDROID_DISPATCH_NOT_OBSERVED"}
    if state == "FAILED":
        return {"last_stage": "ANDROID_WORKER", "first_missing": reason or "GATT_CONNECT_NOT_OBSERVED"}
    if not target_session_id:
        return {"last_stage": "ANDROID_WORKER", "first_missing": reason or "GATT_PROTOCOL_INCOMPLETE"}

    matching = [event for event in target_events if event.get("session_id") == target_session_id]
    if not matching:
        if target_controller is not None:
            previous_match = (
                target_controller.get("previous_access_valid") is True
                and target_controller.get("previous_access_session_id")
                == target_session_id
            )
            return {
                "last_stage": (
                    "TARGET_RESET_BREADCRUMB"
                    if previous_match
                    else str(target_controller.get("gatt_last_stage") or "TARGET_CONTROLLER")
                ),
                "first_missing": "BACKEND_INGEST_NOT_OBSERVED",
            }
        return {"last_stage": "MOBILE_TARGET_RESULT", "first_missing": "BACKEND_INGEST_NOT_OBSERVED"}
    codes = {str(event.get("event_code") or "") for event in matching}
    if "ACCESS_SESSION_TERMINATED" in codes:
        terminal = next(event for event in reversed(matching) if event.get("event_code") == "ACCESS_SESSION_TERMINATED")
        return {"last_stage": "TARGET_TERMINATED", "first_missing": str(terminal.get("reason_code") or "TARGET_TERMINAL_FAILURE")}
    if "ACCESS_SESSION_COMPLETED" in codes:
        return {"last_stage": "BACKEND_COMPLETION", "first_missing": "DOOR_MOVEMENT_UNCONFIRMED"}
    if "ACCESS_RELAY_OFF" in codes:
        return {"last_stage": "RELAY_OFF", "first_missing": "TARGET_TERMINAL_NOT_OBSERVED"}
    if "ACCESS_SENSOR_DETECTED" in codes:
        return {"last_stage": "SENSOR", "first_missing": "RELAY_TRANSITION_NOT_OBSERVED"}
    if "ACCESS_ARMED" in codes:
        return {"last_stage": "ARMED", "first_missing": "SENSOR_TRIGGER_NOT_OBSERVED"}
    if "ACCESS_PROOF_VERIFIED" in codes:
        return {"last_stage": "PROOF_VERIFIED", "first_missing": "TARGET_FSM_ARM_NOT_OBSERVED"}
    if "ACCESS_PROOF_REQUESTED" in codes:
        return {"last_stage": "PROOF_REQUESTED", "first_missing": "TARGET_RESULT_NOT_OBSERVED"}
    return {"last_stage": "GATT_CONNECTED", "first_missing": "GATT_PROTOCOL_INCOMPLETE"}
