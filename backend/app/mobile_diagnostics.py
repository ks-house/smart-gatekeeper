"""Strict, privacy-safe mobile field diagnostic contract and classifier."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Code = str


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


class NativeSnapshot(StrictModel):
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
        if not value.endswith("Z") and "+00:00" not in value:
            raise ValueError("created_at must be UTC")
        return value


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
        return {"last_stage": "FIELD_MARKER", "first_missing": "PHONE_WAKE_NOT_OBSERVED"}
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
