# backend/app/main.py
# =============================================================
# smart-gatekeeper — FastAPI 출입 통제 API 서버
# v2.0: MariaDB 실제 연동 + MQTT Pre-arm & Force Open + Static Web App
# =============================================================
import os
import ssl
import json
import secrets
import hashlib
import hmac
import ipaddress
import logging
import re
import threading
import time
from typing import Optional, List
from datetime import datetime
from contextlib import asynccontextmanager

import pymysql

try:
    import paho.mqtt.client as mqtt
    HAS_PAHO_MQTT = True
except Exception:
    mqtt = None
    HAS_PAHO_MQTT = False

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

try:
    from .acl_refresh import AclRefreshWorker
    from .admin_security import (
        ADMIN_SESSION_COOKIE, IDEMPOTENCY_HEADER, ROLE_ADMIN, ROLE_APPROVER,
        ROLE_AUDITOR, ROLE_OPERATOR, TENANT_HEADER, AdminPrincipal, AdminSecurity,
    )
except ImportError:  # Docker runs uvicorn with /app as the import root.
    from acl_refresh import AclRefreshWorker
    from admin_security import (
        ADMIN_SESSION_COOKIE, IDEMPOTENCY_HEADER, ROLE_ADMIN, ROLE_APPROVER,
        ROLE_AUDITOR, ROLE_OPERATOR, TENANT_HEADER, AdminPrincipal, AdminSecurity,
    )

try:
    from .acl_management import (
        DeterministicP256Signer,
        legacy_device_storage_id,
        verify_raw64,
    )
    from .command_security import build_signed_command
    from .home_assistant_bridge import (
        HomeAssistantCommandBridge,
        bridge_availability_topic,
        bridge_request_topic,
        bridge_result_topic,
        build_discovery_plan,
        target_ack_topic,
        target_availability_topic,
        target_status_topic,
    )
    from .target_acl_delivery import (
        TargetAclDeliveryTracker,
        build_target_acl_wire_payload,
        parse_target_acl_ack,
        target_acl_ack_topic,
    )
    from .target_boot_registry import BootRefreshOutcome, TargetBootRegistry
    from .ops_runtime import (
        OperationalMetrics, PersistentMqttPublisher, PrivacyLogFilter,
        SlidingWindowRateLimiter, opaque_ref, support_export,
    )
except ImportError:  # Docker runs uvicorn with /app as the import root.
    from acl_management import (
        DeterministicP256Signer,
        legacy_device_storage_id,
        verify_raw64,
    )
    from command_security import build_signed_command
    from home_assistant_bridge import (
        HomeAssistantCommandBridge,
        bridge_availability_topic,
        bridge_request_topic,
        bridge_result_topic,
        build_discovery_plan,
        target_ack_topic,
        target_availability_topic,
        target_status_topic,
    )
    from target_acl_delivery import (
        TargetAclDeliveryTracker,
        build_target_acl_wire_payload,
        parse_target_acl_ack,
        target_acl_ack_topic,
    )
    from target_boot_registry import BootRefreshOutcome, TargetBootRegistry
    from ops_runtime import (
        OperationalMetrics, PersistentMqttPublisher, PrivacyLogFilter,
        SlidingWindowRateLimiter, opaque_ref, support_export,
    )

# ─── 로거 설정 ────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(PrivacyLogFilter())

# Dependencies are installed only while building the immutable image. Runtime
# package installation is a supply-chain and availability failure mode.
if not HAS_PAHO_MQTT:
    log.error("[STARTUP] required MQTT dependency unavailable; control effects remain disabled")


def _secret(name: str, default: str = "") -> str:
    """Read one environment value or its Docker/Kubernetes secret file."""
    direct = os.getenv(name)
    secret_file = os.getenv(f"{name}_FILE", "").strip()
    if direct is not None and secret_file:
        raise RuntimeError(f"{name} and {name}_FILE are mutually exclusive")
    if direct is not None:
        return direct.strip()
    if secret_file:
        with open(secret_file, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    return default


# ─── 환경변수 (docker-compose에서 주입) ──────────────────────
DB_HOST     = os.getenv("DB_HOST", "db")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_NAME     = os.getenv("DB_NAME", "smart_gatekeeper")
DB_USER     = os.getenv("DB_USER", "gatekeeper_user")
DB_PASSWORD = _secret("DB_PASSWORD")

MQTT_HOST           = os.getenv("MQTT_HOST", "").strip()
MQTT_PORT           = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USER           = os.getenv("MQTT_USER", "").strip()
MQTT_PASSWORD       = _secret("MQTT_PASSWORD")
MQTT_CA_FILE        = os.getenv("MQTT_CA_FILE", "").strip()
COMMAND_TARGET_ID   = os.getenv("COMMAND_TARGET_ID", "").strip()
COMMAND_TENANT_ID   = os.getenv("COMMAND_TENANT_ID", "").strip()
COMMAND_DOOR_ID     = os.getenv("COMMAND_DOOR_ID", "").strip()
COMMAND_SIGNING_PRIVATE_SCALAR_HEX = _secret("COMMAND_SIGNING_PRIVATE_SCALAR_HEX")
try:
    COMMAND_SIGNING_KEY_ID = int(os.getenv("COMMAND_SIGNING_KEY_ID", "0"))
except ValueError:
    COMMAND_SIGNING_KEY_ID = 0

# Home Assistant is never allowed to publish Target command envelopes.  When
# explicitly enabled, it writes to a backend-only ingress namespace and this
# process creates a fresh boot-bound signed command after validating live
# Target telemetry.  Manual door opening has an independent opt-in.
HA_BRIDGE_ENABLED = os.getenv("HA_BRIDGE_ENABLED", "false").strip().lower() == "true"
HA_BRIDGE_ALLOW_MANUAL_REMOTE = (
    os.getenv("HA_BRIDGE_ALLOW_MANUAL_REMOTE", "false").strip().lower() == "true"
)
try:
    HA_BRIDGE_STATUS_MAX_AGE_SECONDS = float(
        os.getenv("HA_BRIDGE_STATUS_MAX_AGE_SECONDS", "15")
    )
except ValueError:
    HA_BRIDGE_STATUS_MAX_AGE_SECONDS = 15.0

BEACON_UUID         = os.getenv("GATEKEEPER_BEACON_UUID", "a1b2c3d4-e5f6-7890-abcd-ef1234567890")

# ── 문 제어 API 인증 키 (issue.md P3-22) ──────────────────────────────
# 모바일 앱은 빌드 시 --dart-define=GATEKEEPER_API_KEY=... 로 같은 값을 받는다.
# 관리자 콘솔의 마스터 개방도 이 키를 사용한다.
GATEKEEPER_API_KEY  = _secret("GATEKEEPER_API_KEY")
OPS_HMAC_KEY        = _secret("OPS_HMAC_KEY").encode("utf-8")
BUILD_SHA           = os.getenv("BUILD_SHA", "unknown").strip()
EXPECTED_DB_SCHEMA_VERSION = os.getenv("EXPECTED_DB_SCHEMA_VERSION", "").strip()
EXPECTED_DB_SCHEMA_SHA256 = os.getenv("EXPECTED_DB_SCHEMA_SHA256", "").strip()
# 앱이 사용할 Pre-arm 쿨다운 기본값(초). 앱은 이 값을 "기본값"으로만 쓰고,
# 사용자가 디버그 화면에서 직접 조정한 적이 있으면 로컬 값을 우선한다.
# (issue.md P1-12 — 기존에는 30 이 하드코딩되어 매 부팅마다 로컬 설정을 덮어썼다)
APP_COOLDOWN_SEC    = int(os.getenv("APP_COOLDOWN_SEC", "10"))
APP_RSSI_THRESHOLD  = int(os.getenv("APP_RSSI_THRESHOLD", "-85"))
APK_VERSION_URL     = os.getenv("APK_VERSION_URL", "https://tworimpa.synology.me:4442/api/v1/download/version.json")
APK_DOWNLOAD_URL    = os.getenv("APK_DOWNLOAD_URL", "https://tworimpa.synology.me:4442/api/v1/download/apk")
WEBVIEW_URL         = os.getenv("WEBVIEW_URL", "https://tworimpa.synology.me:4442/app")

# Issue #19 management plane is expand-first and production-OFF by default. Legacy
# prearm/manual_remote and OTA download routes remain available when this flag is false.
ACL_MANAGEMENT_ENABLED = os.getenv("ACL_MANAGEMENT_ENABLED", "false").lower() == "true"
ACL_LEGACY_DEVICE_LOOKUP_ENABLED = os.getenv(
    "ACL_LEGACY_DEVICE_LOOKUP_ENABLED", "true"
).lower() == "true"
ACL_LEGACY_REF_HMAC_KEY = _secret("ACL_LEGACY_REF_HMAC_KEY")
ACL_ENROLLMENT_AUTH_JSON = _secret("ACL_ENROLLMENT_AUTH_JSON")
ACL_ADMIN_API_KEY = _secret("ACL_ADMIN_API_KEY")
ACL_TARGET_AUTH_JSON = _secret("ACL_TARGET_AUTH_JSON")
ACL_SIGNING_PRIVATE_SCALAR_HEX = _secret("ACL_SIGNING_PRIVATE_SCALAR_HEX")
ACL_SIGNING_KEY_ID_RAW = os.getenv("ACL_SIGNING_KEY_ID", "1").strip()
ACL_TRANSITION_SIGNING_PRIVATE_SCALAR_HEX = _secret(
    "ACL_TRANSITION_SIGNING_PRIVATE_SCALAR_HEX"
)
ACL_TRANSITION_SIGNING_KEY_ID_RAW = os.getenv(
    "ACL_TRANSITION_SIGNING_KEY_ID", ""
).strip()
ACL_LEASE_SECONDS_RAW = os.getenv("ACL_LEASE_SECONDS", "900").strip()
ACL_PERSONAL_ENROLLMENT_ENABLED = (
    os.getenv("ACL_PERSONAL_ENROLLMENT_ENABLED", "false").strip().lower()
    == "true"
)
ACL_PERSONAL_TENANT_ID = (
    os.getenv("ACL_PERSONAL_TENANT_ID", "").strip() or COMMAND_TENANT_ID
)
ACL_PERSONAL_DOOR_ID = (
    os.getenv("ACL_PERSONAL_DOOR_ID", "").strip() or COMMAND_DOOR_ID
)


# ─── 문 제어 API 인증 (issue.md P3-22) ────────────────────────
def _api_key_matches(candidate: Optional[str]) -> bool:
    """타이밍 공격을 피하기 위해 상수 시간 비교를 사용한다."""
    if not GATEKEEPER_API_KEY or not candidate:
        return False
    return secrets.compare_digest(candidate.strip(), GATEKEEPER_API_KEY)


def require_api_key(x_api_key: Optional[str] = Header(default=None, alias="X-API-KEY")) -> None:
    """
    문 제어 API 인증 의존성.

    · GATEKEEPER_API_KEY 미설정 → 인증을 강제할 수 없다. 경고만 남기고 통과시킨다.
      여기서 막으면 키를 설정하기 전까지 **모든 세입자의 출입이 불가능해진다.**
      실제 현관문을 다루므로 잠금(lockout)보다 경고를 택한다.
      단, 이 상태에서는 아래 보호가 여전히 유효하다:
        - 미등록/미승인 기기 거부
        - device_id 누락 거부
        - DB 장애 시 fail-closed
    · 설정됨 → X-API-KEY 헤더가 일치해야 한다.
    """
    if not GATEKEEPER_API_KEY:
        raise HTTPException(status_code=503, detail="control API authentication is not configured")
        # Legacy warning-only implementation is intentionally unreachable.
        log.warning(
            "[SECURITY] GATEKEEPER_API_KEY 미설정 — 문 제어 API가 키 인증 없이 열려 있습니다. "
            "앱을 배포한 뒤 반드시 환경변수를 설정하고 재시작하십시오."
        )
        return
    if not _api_key_matches(x_api_key):
        log.warning("[SECURITY] X-API-KEY 불일치/누락 → 문 제어 요청 거부")
        raise HTTPException(status_code=401, detail="invalid or missing X-API-KEY")


# ─── DB 연결 헬퍼 ─────────────────────────────────────────────
def get_db():
    """PyMySQL 커넥션 반환. 사용 후 반드시 .close() 호출."""
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=5,
    )


_target_boot_registry = TargetBootRegistry(get_db)
_target_acl_delivery_tracker = TargetAclDeliveryTracker()
_acl_refresh_worker: AclRefreshWorker | None = None
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


def _command_provisioning_error() -> Optional[str]:
    tokens = (COMMAND_TARGET_ID, COMMAND_TENANT_ID, COMMAND_DOOR_ID)
    if any(
        not token or len(token) > 64 or any(ord(char) < 0x21 or ord(char) > 0x7e for char in token)
        for token in tokens
    ):
        return "target identity"
    if (
        not MQTT_HOST
        or not 1 <= MQTT_PORT <= 65535
        or MQTT_PORT == 1883
        or not MQTT_USER
        or not MQTT_PASSWORD
        or secrets.compare_digest(MQTT_USER, COMMAND_TARGET_ID)
    ):
        return "broker identity"
    if not MQTT_CA_FILE or not os.path.isfile(MQTT_CA_FILE):
        return "broker CA"
    if COMMAND_SIGNING_KEY_ID <= 0:
        return "signing key ID"
    if (
        len(COMMAND_SIGNING_PRIVATE_SCALAR_HEX) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in COMMAND_SIGNING_PRIVATE_SCALAR_HEX)
        or not 0 < int(COMMAND_SIGNING_PRIVATE_SCALAR_HEX, 16) < _P256_ORDER
    ):
        return "signing scalar"
    return None

# ─── MQTT Helper Functions ────────────────────────────────────
def _create_mqtt_client(client_id: str):
    """paho-mqtt 1.x 및 2.x 버전 호환 클라이언트 생성 헬퍼"""
    try:
        if hasattr(mqtt, "CallbackAPIVersion"):
            return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5)
        return mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv5)
    except Exception:
        return mqtt.Client(client_id=client_id)

_mqtt_publisher = None
_mqtt_publisher_lock = threading.Lock()


def _connect_mqtt_client(client) -> None:
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.tls_set(
        ca_certs=MQTT_CA_FILE,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(False)
    # Paho applies this to TCP/TLS. PersistentMqttPublisher additionally wraps
    # the entire DNS+TCP+TLS call in a caller-visible deadline.
    client._connect_timeout = 1.0
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)


def _cancel_mqtt_connect(client) -> None:
    try:
        client._sock_close()
    except Exception:
        try:
            client.disconnect()
        except Exception:
            pass


def _persistent_publisher() -> PersistentMqttPublisher:
    global _mqtt_publisher
    with _mqtt_publisher_lock:
        if _mqtt_publisher is None:
            process_ref = secrets.token_hex(12)
            _mqtt_publisher = PersistentMqttPublisher(
                lambda: _create_mqtt_client(f"gatekeeper-api-{process_ref}"),
                _connect_mqtt_client,
                max_inflight=16,
                publish_timeout=2.0,
                connect_timeout=1.0,
                cancel_connect=_cancel_mqtt_connect,
            )
        return _mqtt_publisher


def _publish_mqtt_msg(topic: str, payload: str | bytes, label: str) -> bool:
    """Publish through one bounded persistent hostname-verified MQTTS session."""
    if not HAS_PAHO_MQTT:
        log.warning("[%s] MQTT dependency unavailable", label)
        return False
    if (
        not MQTT_HOST or MQTT_PORT == 1883 or not MQTT_USER or
        not MQTT_PASSWORD or not MQTT_CA_FILE or not os.path.isfile(MQTT_CA_FILE)
    ):
        log.error("[%s] verified MQTTS provisioning incomplete", label)
        _ops_metrics.event("mqtt", "provisioning_failed")
        return False
    published = _persistent_publisher().publish(topic, payload)
    _ops_metrics.event("mqtt", "published" if published else "bounded_failure")
    log.info("[%s] MQTT publish outcome=%s", label, "published" if published else "bounded_failure")
    return published


def _acl_target_topics(
    logical_topic: str,
    envelope: dict,
    target_credentials: dict[str, dict[str, str]],
) -> list[str]:
    """Resolve one signed tenant/door ACL to exact authorized Target topics."""
    parts = logical_topic.split("/")
    fields = envelope.get("fields")
    if (
        len(parts) != 5
        or parts[:3] != ["gatekeeper", "acl", "v1"]
        or not isinstance(fields, dict)
    ):
        return []
    tenant_id, door_id = parts[3], parts[4]
    envelope_door = fields.get("door_id")
    if not isinstance(envelope_door, str) or not hmac.compare_digest(
        door_id, envelope_door
    ):
        return []
    return sorted(
        f"gatekeeper/v1/targets/{target_id}/acl"
        for target_id, authorization in target_credentials.items()
        if hmac.compare_digest(authorization["tenant_id"], tenant_id)
        and hmac.compare_digest(authorization["door_id"], door_id)
    )


def _publish_acl_to_targets(
    logical_topic: str,
    envelope: dict,
    target_credentials: dict[str, dict[str, str]],
    *,
    publish_message,
    delivery_tracker: TargetAclDeliveryTracker,
    ack_timeout_seconds: float = 5.0,
) -> bool:
    target_topics = _acl_target_topics(
        logical_topic, envelope, target_credentials
    )
    fields = envelope.get("fields")
    if not target_topics or not isinstance(fields, dict):
        return False
    acl_version = fields.get("acl_version")
    if (
        isinstance(acl_version, bool)
        or not isinstance(acl_version, int)
        or acl_version < 1
    ):
        return False
    try:
        payload = build_target_acl_wire_payload(envelope)
    except (TypeError, ValueError):
        return False
    target_ids = [target_topic.split("/")[3] for target_topic in target_topics]
    if not delivery_tracker.begin_delivery(target_ids, acl_version):
        return False
    if not all(
        publish_message(target_topic, payload, "MQTT-ACL")
        for target_topic in target_topics
    ):
        return False
    return delivery_tracker.wait_for(
        target_ids,
        acl_version,
        timeout_seconds=ack_timeout_seconds,
    )


def _signed_target_command(
    action: str,
    value: int = 0,
    *,
    expected_boot_id: Optional[str] = None,
    session_id: Optional[str] = None,
    nonce: Optional[str] = None,
    ttl_seconds: int = 60,
) -> bool:
    provisioning_error = _command_provisioning_error()
    if provisioning_error is not None:
        log.error("[MQTT-COMMAND] provisioning incomplete: %s", provisioning_error)
        return False
    try:
        boot_id = _target_boot_registry.current_boot_id(COMMAND_TARGET_ID)
        if boot_id is None:
            return False
        if expected_boot_id is not None and not secrets.compare_digest(
            boot_id, expected_boot_id
        ):
            return False
        scalar = int(COMMAND_SIGNING_PRIVATE_SCALAR_HEX, 16)
        signer = DeterministicP256Signer(scalar, COMMAND_SIGNING_KEY_ID)
        envelope = build_signed_command(
            signer=signer,
            target_id=COMMAND_TARGET_ID,
            tenant_id=COMMAND_TENANT_ID,
            door_id=COMMAND_DOOR_ID,
            boot_id=boot_id,
            action=action,
            value=value,
            ttl_seconds=ttl_seconds,
            session_id=session_id,
            nonce=nonce,
        )
    except (TypeError, ValueError):
        return False
    topic = f"gatekeeper/v1/targets/{COMMAND_TARGET_ID}/command"
    return _publish_mqtt_msg(
        topic,
        json.dumps(envelope, separators=(",", ":"), sort_keys=True),
        f"MQTT-COMMAND-{action}",
    )


def _refresh_target_acl(
    target_id: str, tenant_id: str, door_id: str, reason: str
) -> bool:
    authorization = globals().get("_acl_target_credentials", {}).get(target_id)
    service = globals().get("_acl_service")
    if authorization is None or service is None:
        return False
    if not (
        secrets.compare_digest(authorization["tenant_id"], tenant_id)
        and secrets.compare_digest(authorization["door_id"], door_id)
    ):
        return False
    refresh_reason = (
        "TARGET_BOOT_REFRESH" if reason == "target_boot" else "ACL_LEASE_REFRESH"
    )
    try:
        envelope = service.refresh_snapshot(
            tenant_id,
            door_id,
            actor_ref=f"system:{reason}",
            reason=refresh_reason,
        )
    except Exception:
        log.warning("[MQTT-ACL] bounded asynchronous refresh failed")
        return False
    fields = envelope.get("fields") if isinstance(envelope, dict) else None
    return bool(
        isinstance(fields, dict)
        and isinstance(fields.get("acl_version"), int)
        and fields["acl_version"] > 0
    )


def _start_acl_refresh_worker() -> AclRefreshWorker | None:
    global _acl_refresh_worker
    if not globals().get("_acl_runtime_ready", False):
        return None
    try:
        worker = AclRefreshWorker(
            globals().get("_acl_target_credentials", {}),
            _refresh_target_acl,
            lease_seconds=int(globals().get("_acl_lease_seconds", 0)),
        )
    except (TypeError, ValueError):
        log.error("[MQTT-ACL] refresh worker configuration invalid")
        return None
    _acl_refresh_worker = worker
    worker.start()
    return worker


def _request_target_acl_refresh(target_id: str, reason: str) -> bool:
    worker = _acl_refresh_worker
    return worker.request(target_id, reason) if worker is not None else False


def _start_target_boot_subscriber():
    if _command_provisioning_error() is not None or not HAS_PAHO_MQTT:
        return None
    bridge = None
    if HA_BRIDGE_ENABLED:
        try:
            bridge = HomeAssistantCommandBridge(
                COMMAND_TARGET_ID,
                allow_manual_remote=HA_BRIDGE_ALLOW_MANUAL_REMOTE,
                status_max_age_seconds=HA_BRIDGE_STATUS_MAX_AGE_SECONDS,
            )
        except ValueError:
            log.error("[MQTT-HA] bridge configuration invalid; bridge remains disabled")

    client = _create_mqtt_client(f"gatekeeper-boot-registry-{time.time_ns()}")
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.tls_set(
        ca_certs=MQTT_CA_FILE,
        cert_reqs=ssl.CERT_REQUIRED,
        tls_version=ssl.PROTOCOL_TLS_CLIENT,
    )
    client.tls_insecure_set(False)
    if bridge is not None:
        client.will_set(
            bridge_availability_topic(COMMAND_TARGET_ID),
            payload="offline",
            qos=1,
            retain=True,
        )

    def publish_bridge_result(connected_client, result: dict) -> None:
        connected_client.publish(
            bridge_result_topic(COMMAND_TARGET_ID),
            json.dumps(result, separators=(",", ":"), sort_keys=True),
            qos=1,
            retain=False,
        )

    def bridge_boot_is_aligned() -> bool:
        if bridge is None:
            return False
        live_boot_id = bridge.live_boot_id()
        registered_boot_id = _target_boot_registry.current_boot_id(
            COMMAND_TARGET_ID
        )
        return bool(
            live_boot_id
            and registered_boot_id
            and secrets.compare_digest(live_boot_id, registered_boot_id)
        )

    def on_connect(connected_client, _userdata, _flags, reason_code, *args):
        # MQTT v5 in paho-mqtt 1.6.1 passes a ReasonCodes object here.  It
        # deliberately supports comparison with integer reason codes but does
        # not implement int(), so coercion raises TypeError inside the network
        # thread before subscriptions or HA discovery can be published.
        if reason_code == 0:
            _target_acl_delivery_tracker.reset_transport()
            status_target_ids = {COMMAND_TARGET_ID}
            status_target_ids.update(
                globals().get("_acl_target_credentials", {}).keys()
            )
            status_target_ids.discard("")
            for target_id in sorted(status_target_ids):
                connected_client.subscribe(
                    f"gatekeeper/v1/targets/{target_id}/boot", qos=1
                )
            if globals().get("_acl_runtime_ready", False):
                for target_id in globals().get("_acl_target_credentials", {}):
                    connected_client.subscribe(
                        target_acl_ack_topic(target_id), qos=1
                    )

            for target_id in sorted(status_target_ids):
                connected_client.subscribe(target_status_topic(target_id), qos=1)

            if bridge is None:
                return
            bridge.reset_transport()
            connected_client.subscribe(
                target_availability_topic(COMMAND_TARGET_ID), qos=1
            )
            connected_client.subscribe(target_ack_topic(COMMAND_TARGET_ID), qos=1)
            connected_client.subscribe(
                bridge_request_topic(COMMAND_TARGET_ID, "+"), qos=1
            )
            connected_client.publish(
                bridge_availability_topic(COMMAND_TARGET_ID),
                "offline",
                qos=1,
                retain=True,
            )
            for publication in build_discovery_plan(
                COMMAND_TARGET_ID,
                allow_manual_remote=HA_BRIDGE_ALLOW_MANUAL_REMOTE,
            ):
                connected_client.publish(
                    publication.topic,
                    publication.payload,
                    qos=publication.qos,
                    retain=publication.retain,
                )

    def on_message(connected_client, _userdata, message):
        payload = bytes(message.payload)
        if message.topic.endswith("/boot"):
            boot_target_id = next(
                (
                    target_id
                    for target_id in {
                        COMMAND_TARGET_ID,
                        *globals().get("_acl_target_credentials", {}).keys(),
                    }
                    if target_id
                    and secrets.compare_digest(
                        message.topic,
                        f"gatekeeper/v1/targets/{target_id}/boot",
                    )
                ),
                None,
            )
            if boot_target_id is None or bool(getattr(message, "retain", False)):
                log.warning("[MQTT-BOOT] rejected boot refresh")
                return
            refresh_outcome = (
                _target_boot_registry.refresh_outcome_from_authenticated_topic(
                    message.topic, payload
                )
            )
            if refresh_outcome is BootRefreshOutcome.REJECTED:
                log.warning("[MQTT-BOOT] rejected boot refresh")
            elif refresh_outcome is BootRefreshOutcome.ADVANCED:
                _request_target_acl_refresh(boot_target_id, "target_boot")
            return
        if message.topic.endswith("/acl/ack"):
            ack = parse_target_acl_ack(
                message.topic,
                payload,
                retained=bool(getattr(message, "retain", False)),
            )
            authorization = globals().get("_acl_target_credentials", {}).get(
                ack.target_id if ack is not None else ""
            )
            acl_service = globals().get("_acl_service")
            if ack is None or authorization is None or acl_service is None:
                log.warning("[MQTT-ACL] rejected unauthenticated or malformed Target ACK")
                return
            snapshot = acl_service.store.snapshot_by_version(
                authorization["tenant_id"],
                authorization["door_id"],
                ack.acl_version,
            )
            if snapshot is None:
                log.warning("[MQTT-ACL] rejected ACK for unknown snapshot")
                return
            try:
                acl_service.ack_snapshot(
                    authorization["tenant_id"],
                    ack.target_id,
                    authorization["door_id"],
                    ack.acl_version,
                    snapshot["sha256"],
                    "APPLIED",
                )
            except Exception:
                log.warning("[MQTT-ACL] failed to persist Target application ACK")
                return
            _target_acl_delivery_tracker.mark_applied(
                ack.target_id, ack.acl_version
            )
            return


        status_target_id = next(
            (
                target_id
                for target_id in {
                    COMMAND_TARGET_ID,
                    *globals().get("_acl_target_credentials", {}).keys(),
                }
                if target_id
                and secrets.compare_digest(
                    message.topic, target_status_topic(target_id)
                )
            ),
            None,
        )
        if status_target_id is not None:
            retained = bool(getattr(message, "retain", False))
            refresh_outcome = (
                _target_boot_registry.refresh_outcome_from_authenticated_status_topic(
                    message.topic, payload, retained=retained
                )
            )
            if refresh_outcome is BootRefreshOutcome.REJECTED:
                log.warning("[MQTT-BOOT] rejected status boot refresh")
                return
            if refresh_outcome is BootRefreshOutcome.ADVANCED:
                _request_target_acl_refresh(status_target_id, "target_boot")
            if bridge is None or not secrets.compare_digest(
                status_target_id, COMMAND_TARGET_ID
            ):
                return
            if not bridge.note_status(message.topic, payload):
                log.warning("[MQTT-HA] rejected malformed Target status")
                return
            online = bridge_boot_is_aligned()
            connected_client.publish(
                bridge_availability_topic(COMMAND_TARGET_ID),
                "online" if online else "offline",
                qos=1,
                retain=True,
            )
            return
        if bridge is None:
            return

        if message.topic == target_availability_topic(COMMAND_TARGET_ID):
            if bool(getattr(message, "retain", False)):
                return
            state = bridge.note_target_availability(message.topic, payload)
            if state is not None:
                connected_client.publish(
                    bridge_availability_topic(COMMAND_TARGET_ID),
                    (
                        "online"
                        if state == "online" and bridge_boot_is_aligned()
                        else "offline"
                    ),
                    qos=1,
                    retain=True,
                )
            return

        if message.topic == target_ack_topic(COMMAND_TARGET_ID):
            if bool(getattr(message, "retain", False)):
                return
            ack = bridge.accept_ack(message.topic, payload)
            if ack.accepted:
                publish_bridge_result(
                    connected_client,
                    {
                        "action": ack.action,
                        "reason": ack.reason,
                        "result_code": ack.result_code,
                        "session_id": ack.session_id,
                        "stage": "target_ack",
                    },
                )
            return

        request_prefix = bridge_request_topic(COMMAND_TARGET_ID, "+")[:-1]
        if message.topic.startswith(request_prefix):
            decision = bridge.accept_request(
                message.topic,
                payload,
                retained=bool(getattr(message, "retain", False)),
                duplicate=bool(getattr(message, "dup", False)),
            )
            if not decision.accepted or decision.command is None:
                publish_bridge_result(
                    connected_client,
                    {"reason": decision.reason, "stage": "rejected"},
                )
                if decision.reason == "target_status_stale":
                    connected_client.publish(
                        bridge_availability_topic(COMMAND_TARGET_ID),
                        "offline",
                        qos=1,
                        retain=True,
                    )
                return
            command = decision.command
            published = _signed_target_command(
                command.action,
                command.value,
                expected_boot_id=command.expected_boot_id,
                session_id=command.session_id,
                nonce=command.nonce,
                ttl_seconds=15,
            )
            if published:
                bridge.note_published(command)
            else:
                bridge.note_publish_failed(command)
            publish_bridge_result(
                connected_client,
                {
                    "action": command.action,
                    "reason": "broker_accepted" if published else "publish_failed",
                    "session_id": command.session_id,
                    "stage": "backend_publish",
                },
            )

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
    client.loop_start()
    client._sgk_ha_bridge = bridge
    return client


def publish_arm_to_mqtt(tenant_name: str, tenant_id: int) -> bool:
    """Publish a signed, boot-bound pre-arm command."""
    return _signed_target_command("arm")

def publish_force_open_to_mqtt(tenant_name: str = "수동원격") -> bool:
    """Publish the authenticated explicit-button manual_remote command."""
    return _signed_target_command("manual_remote")

def publish_admin_config_to_mqtt(tx_power: Optional[int] = None, tof_distance: Optional[int] = None, distance_threshold: Optional[int] = None, duration: Optional[int] = None, relay_cooldown: Optional[int] = None) -> dict:
    """NAS → MQTT Broker → ESP32-C6 gatekeeper/config/... 엔지니어 튜닝 토픽 및 gatekeeper/config/set 일괄 발행."""
    results = {}
    dist_val = distance_threshold if distance_threshold is not None else tof_distance
    if tx_power is not None:
        ok = _signed_target_command("set_tx_power", tx_power)
        results["tx_power"] = {"value": tx_power, "success": ok}
    if dist_val is not None:
        ok = _signed_target_command("set_distance_threshold", dist_val)
        results["distance_threshold"] = {"value": dist_val, "success": ok}
    if duration is not None:
        ok = _signed_target_command("set_duration", duration)
        results["duration"] = {"value": duration, "success": ok}
    if relay_cooldown is not None:
        ok = _signed_target_command("set_relay_cooldown", relay_cooldown)
        results["relay_cooldown"] = {"value": relay_cooldown, "success": ok}
    
    return results





# ─── Pydantic 스키마 ──────────────────────────────────────────
class AuthVerifyRequest(BaseModel):
    ble_mac: str = Field(..., example="AA:BB:CC:DD:EE:01", description="스마트폰 BLE MAC 주소")
    auth_key: Optional[str] = Field(None, description="인증 토큰/키 (선택)")
    distance_mm: Optional[int] = Field(None, description="센서 측정 거리(mm)")

class AuthVerifyResponse(BaseModel):
    granted: bool
    tenant_name: Optional[str] = None
    unit_number: Optional[str] = None
    message: str
    arm_published: Optional[bool] = Field(None, description="MQTT arm 발행 성공 여부")

class UserRequestSchema(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    room_no: str = Field(min_length=1, max_length=20)
    device_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^(?:DEV|GK)-[A-Z0-9-]+$",
    )


class PersonalAdminLoginSchema(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class AdminTenantUpdateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=50)
    unit_number: str = Field(min_length=1, max_length=20)

class PrearmRequestSchema(BaseModel):
    beacon_uuid: str
    device_id: Optional[str] = None
    rssi: Optional[int] = None
    timestamp: Optional[str] = None


class ForceOpenRequestSchema(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=8, max_length=256)


class ManualOpenV2Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: Optional[str] = Field(default=None, max_length=128)
    reason: Optional[str] = Field(default=None, max_length=256)
    nonce: Optional[str] = Field(default=None, min_length=32, max_length=128)
    expires_at: Optional[int] = None
    credential_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    signature_raw64: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{128}$")


def build_mobile_manual_open_input(
    credential_id: str,
    nonce: str,
    expires_at: int,
    reason: str,
    idempotency_key: str,
) -> bytes:
    """Canonical AndroidKeyStore possession proof; never includes private material."""
    if reason != "mobile_manual_button":
        raise ValueError("unsupported mobile manual reason")
    if not re.fullmatch(r"[0-9a-f]{32}", credential_id):
        raise ValueError("credential id")
    if not re.fullmatch(r"[0-9a-f]{64}", nonce):
        raise ValueError("nonce")
    if not 16 <= len(idempotency_key) <= 128:
        raise ValueError("idempotency")
    return b"".join(
        (
            b"SGKRMO01",
            bytes.fromhex(credential_id),
            bytes.fromhex(nonce),
            int(expires_at).to_bytes(8, "big"),
            hashlib.sha256(reason.encode("utf-8")).digest(),
            hashlib.sha256(idempotency_key.encode("utf-8")).digest(),
        )
    )


class PrivacyDeletionRequest(BaseModel):
    policy_version: str = Field(pattern=r"^sgk-retention-v1$")
    before_days: int = Field(ge=30, le=3650)

class AdminConfigRequestSchema(BaseModel):
    tx_power: Optional[int] = Field(None, example=-6, description="BLE Tx Power dBm (-6, 0, 3, 9)")
    distance_threshold: Optional[int] = Field(None, example=50, description="초음파 감지 기준 거리 cm (20 ~ 200)")
    tof_distance: Optional[int] = Field(None, example=50, description="하위 호환용 감지 기준 거리 cm (20 ~ 200)")
    duration: Optional[int] = Field(None, example=60000, description="Pre-arm 유효 유지 시간 ms (1000 ~ 60000)")
    relay_cooldown: Optional[int] = Field(None, example=3000, description="Target 릴레이 쿨다운 ms (1000 ~ 30000)")





class AccessLogItem(BaseModel):
    id: int
    tenant_id: Optional[int]
    auth_method: str
    is_success: bool
    distance_mm: Optional[int]
    failure_reason: Optional[str]
    created_at: datetime

# ─── FastAPI 앱 ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("[STARTUP] Smart Gatekeeper API v2.1 starting")
    log.info("[STARTUP] database endpoint configured=%s", bool(DB_HOST and DB_NAME))
    log.info(
        "[STARTUP] verified MQTTS broker configured; per-Target signed command plane=%s",
        bool(COMMAND_TARGET_ID and COMMAND_SIGNING_KEY_ID),
    )
    log.info(
        "[STARTUP] Home Assistant signed-command bridge=%s manual_remote=%s",
        HA_BRIDGE_ENABLED,
        HA_BRIDGE_ENABLED and HA_BRIDGE_ALLOW_MANUAL_REMOTE,
    )
    if GATEKEEPER_API_KEY:
        log.info("[STARTUP] 🔐 문 제어 API 키 인증 활성화 (X-API-KEY)")
    else:
        log.warning(
            "[STARTUP] ⚠️ GATEKEEPER_API_KEY 미설정 — 문 제어 API 키 인증이 비활성 상태입니다. "
            "Pre-arm 은 키 없이도 호출 가능하고, 관리자 마스터 개방은 사용할 수 없습니다. "
            "미등록/미승인 기기 거부와 DB 장애 시 fail-closed 는 계속 동작합니다."
        )
    boot_subscriber = None
    acl_refresh_worker = None
    try:
        boot_subscriber = _start_target_boot_subscriber()
    except Exception as error:
        log.error(
            "[MQTT-BOOT] subscriber unavailable error_type=%s; "
            "commands stay disabled",
            type(error).__name__,
        )
    try:
        acl_refresh_worker = _start_acl_refresh_worker()
    except Exception:
        log.error("[MQTT-ACL] refresh worker unavailable; local GATT stays fail-closed")
    try:
        yield
    finally:
        if acl_refresh_worker is not None:
            acl_refresh_worker.stop()
        if boot_subscriber is not None:
            if getattr(boot_subscriber, "_sgk_ha_bridge", None) is not None:
                try:
                    boot_subscriber.publish(
                        bridge_availability_topic(COMMAND_TARGET_ID),
                        "offline",
                        qos=1,
                        retain=True,
                    ).wait_for_publish(timeout=2.0)
                except Exception:
                    pass
            boot_subscriber.loop_stop()
            boot_subscriber.disconnect()
        if _mqtt_publisher is not None:
            _mqtt_publisher.close()
        log.info("[SHUTDOWN] Smart Gatekeeper API 종료")

app = FastAPI(
    title="Smart Gatekeeper API",
    description="시놀로지 NAS 백엔드 — BLE Beacon + MQTT Pre-arm 기반 출입 통제 v2.0",
    version="2.0.0",
    lifespan=lifespan,
    default_response_class=JSONResponse
)

# Admin access is deliberately independent of the mobile pre-arm credential.
# Missing mTLS identity configuration leaves admin/control routes unavailable;
# this is a deployment gate, not a development fallback.
admin_security = AdminSecurity.from_environment()
_control_proposals: dict[str, dict] = {}
_control_proposals_lock = threading.Lock()
_ops_metrics = OperationalMetrics()
_ops_rate_limiter = SlidingWindowRateLimiter(limit=30, window_seconds=60, max_keys=4096)
_ops_hmac_key = OPS_HMAC_KEY if len(OPS_HMAC_KEY) >= 32 else secrets.token_bytes(32)


def _route_group(path: str) -> str:
    if path.startswith("/api/v1/admin/control") or path == "/api/v1/door/open":
        return "control"
    if path in {"/api/v1/door/prearm", "/api/v1/auth/verify"}:
        return "authentication"
    if path.startswith("/api/v1/admin/privacy"):
        return "privacy"
    if path in {"/live", "/ready", "/health", "/api/v1/admin/metrics"}:
        return "health"
    return "other"


def _rate_limit_identity(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    if peer in admin_security.trusted_proxy_ips:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded and "," not in forwarded:
            try:
                peer = str(ipaddress.ip_address(forwarded.strip()))
            except ValueError:
                pass
    return opaque_ref(peer, _ops_hmac_key, "peer")


@app.middleware("http")
async def deny_by_default_admin_routes(request: Request, call_next):
    """Put a session/CSRF/re-auth boundary in front of every admin route.

    Route handlers still perform their narrower role and tenant checks.  This
    guard prevents a newly added /api/v1/admin endpoint from silently becoming
    public while preserving target OTA/download and emergency hardware paths.
    """
    started = time.monotonic()
    path = request.url.path
    route_group = _route_group(path)
    if route_group in {"control", "authentication", "privacy"}:
        peer_ref = _rate_limit_identity(request)
        allowed, retry_after = _ops_rate_limiter.allow(f"{route_group}:{peer_ref}")
        if not allowed:
            _ops_metrics.event("rate_limit", route_group)
            return JSONResponse(
                status_code=429,
                content={"detail": "request rate exceeded"},
                headers={"Retry-After": str(retry_after)},
            )
    if path.startswith("/api/v1/admin/") and path not in {
        "/api/v1/admin/sessions", "/api/v1/admin/personal-sessions"
    }:
        try:
            required_roles = (ROLE_ADMIN, ROLE_AUDITOR, ROLE_OPERATOR, ROLE_APPROVER)
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                required_roles = (ROLE_OPERATOR, ROLE_APPROVER) if "/control/" in path else (ROLE_ADMIN,)
            request.state.admin_principal = _admin_principal(
                request,
                unsafe=request.method not in {"GET", "HEAD", "OPTIONS"},
                roles=required_roles,
                tenant_scope=request.headers.get(TENANT_HEADER),
                reauthenticate=request.method not in {"GET", "HEAD", "OPTIONS"},
            )
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    response = await call_next(request)
    status_class = f"{response.status_code // 100}xx"
    _ops_metrics.request(route_group, status_class, time.monotonic() - started)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store" if route_group in {"control", "authentication", "privacy"} else "no-cache"
    return response


def _legacy_tenant_scope(tenant_id: int) -> str:
    return f"legacy:{tenant_id}"


def _admin_principal(
    request: Request,
    *,
    unsafe: bool = False,
    roles: tuple[str, ...] = (ROLE_ADMIN,),
    tenant_scope: Optional[str] = None,
    reauthenticate: bool = False,
) -> AdminPrincipal:
    return admin_security.principal(
        request,
        unsafe=unsafe,
        roles=roles,
        tenant_id=tenant_scope,
        reauthenticate=reauthenticate,
    )


def _audit_admin(
    conn, principal: AdminPrincipal, tenant_scope: str, action: str,
    object_ref: str, idempotency_key: Optional[str] = None,
) -> None:
    """Append an actor-attributed audit event before an irreversible action."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO admin_audit (actor_subject, tenant_scope, action, object_ref, "
            "idempotency_hash, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (
                principal.subject,
                tenant_scope,
                action,
                object_ref,
                hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
                if idempotency_key else None,
                int(datetime.now().timestamp()),
            ),
        )

# Mount the new management plane only when the feature is explicitly enabled and all
# authentication/signing prerequisites are present. A bad RC configuration must not take
# down the distinct legacy manual_remote or independent OTA download paths.
_acl_runtime_ready = False
if ACL_MANAGEMENT_ENABLED:
    _acl_missing = [
        name
        for name, value in (
            ("ACL_ENROLLMENT_AUTH_JSON", ACL_ENROLLMENT_AUTH_JSON),
            ("ACL_ADMIN_API_KEY", ACL_ADMIN_API_KEY),
            ("ACL_TARGET_AUTH_JSON", ACL_TARGET_AUTH_JSON),
            ("ACL_SIGNING_PRIVATE_SCALAR_HEX", ACL_SIGNING_PRIVATE_SCALAR_HEX),
        )
        if not value
    ]
    if ACL_LEGACY_DEVICE_LOOKUP_ENABLED and not ACL_LEGACY_REF_HMAC_KEY:
        _acl_missing.append("ACL_LEGACY_REF_HMAC_KEY")
    if ACL_PERSONAL_ENROLLMENT_ENABLED:
        for _name, _value in (
            ("GATEKEEPER_API_KEY", GATEKEEPER_API_KEY),
            ("ACL_LEGACY_REF_HMAC_KEY", ACL_LEGACY_REF_HMAC_KEY),
            ("ACL_PERSONAL_TENANT_ID", ACL_PERSONAL_TENANT_ID),
            ("ACL_PERSONAL_DOOR_ID", ACL_PERSONAL_DOOR_ID),
        ):
            if not _value:
                _acl_missing.append(_name)
    if _acl_missing:
        log.error(
            "[ACL-MANAGEMENT] feature remains unavailable; missing required settings: %s",
            ",".join(_acl_missing),
        )
    else:
        try:
            try:
                from .acl_api import AclApiConfig, create_acl_router
                from .acl_management import (
                    AclManagementService,
                    AclStore,
                    DeterministicP256Signer,
                )
            except ImportError:  # Docker runs uvicorn with /app as the import root.
                from acl_api import AclApiConfig, create_acl_router
                from acl_management import (
                    AclManagementService,
                    AclStore,
                    DeterministicP256Signer,
                )

            _acl_enrollment_credentials = json.loads(ACL_ENROLLMENT_AUTH_JSON)
            _acl_target_credentials = json.loads(ACL_TARGET_AUTH_JSON)
            _acl_signing_key_id = int(ACL_SIGNING_KEY_ID_RAW)
            _acl_lease_seconds = int(ACL_LEASE_SECONDS_RAW)
            if (
                not isinstance(_acl_enrollment_credentials, dict)
                or not _acl_enrollment_credentials
                or not all(
                    isinstance(actor_id, str)
                    and actor_id
                    and isinstance(value, dict)
                    and isinstance(value.get("tenant_id"), str)
                    and len(value["tenant_id"]) == 32
                    and isinstance(value.get("key"), str)
                    and bool(value["key"])
                    for actor_id, value in _acl_enrollment_credentials.items()
                )
            ):
                raise ValueError("ACL_ENROLLMENT_AUTH_JSON must map actor IDs to tenant_id/key")
            if (
                not isinstance(_acl_target_credentials, dict)
                or not _acl_target_credentials
                or not all(
                    isinstance(target_id, str)
                    and target_id
                    and isinstance(value, dict)
                    and isinstance(value.get("tenant_id"), str)
                    and len(value["tenant_id"]) == 32
                    and isinstance(value.get("door_id"), str)
                    and len(value["door_id"]) == 32
                    and all(char in "0123456789abcdef" for char in value["door_id"])
                    and isinstance(value.get("key"), str)
                    and bool(value["key"])
                    for target_id, value in _acl_target_credentials.items()
                )
            ):
                raise ValueError(
                    "ACL_TARGET_AUTH_JSON must map target IDs to tenant_id/door_id/key"
                )
            _acl_target_door_owners: dict[str, str] = {}
            for _target_credential in _acl_target_credentials.values():
                _door_id = _target_credential["door_id"]
                _tenant_id = _target_credential["tenant_id"]
                _existing_owner = _acl_target_door_owners.setdefault(
                    _door_id, _tenant_id
                )
                if not secrets.compare_digest(_existing_owner, _tenant_id):
                    raise ValueError(
                        "ACL_TARGET_AUTH_JSON cannot assign one door to multiple tenants"
                    )
            if ACL_PERSONAL_ENROLLMENT_ENABLED:
                _personal_command_target = _acl_target_credentials.get(
                    COMMAND_TARGET_ID
                )
                if (
                    len(ACL_PERSONAL_TENANT_ID) != 32
                    or any(
                        char not in "0123456789abcdef"
                        for char in ACL_PERSONAL_TENANT_ID
                    )
                    or len(ACL_PERSONAL_DOOR_ID) != 32
                    or any(
                        char not in "0123456789abcdef"
                        for char in ACL_PERSONAL_DOOR_ID
                    )
                    or not isinstance(_personal_command_target, dict)
                    or not (
                        secrets.compare_digest(
                            _personal_command_target.get("tenant_id", ""),
                            ACL_PERSONAL_TENANT_ID,
                        )
                        and secrets.compare_digest(
                            _personal_command_target.get("door_id", ""),
                            ACL_PERSONAL_DOOR_ID,
                        )
                    )
                ):
                    raise ValueError(
                        "personal enrollment scope must match the configured command Target"
                    )

            class _AclMqttPublisher:
                def publish(self, topic: str, envelope: dict) -> bool:
                    return _publish_acl_to_targets(
                        topic,
                        envelope,
                        _acl_target_credentials,
                        publish_message=_publish_mqtt_msg,
                        delivery_tracker=_target_acl_delivery_tracker,
                    )

            _acl_signer = DeterministicP256Signer(
                int(ACL_SIGNING_PRIVATE_SCALAR_HEX, 16),
                signing_key_id=_acl_signing_key_id,
            )
            _acl_transition_signers = ()
            if bool(ACL_TRANSITION_SIGNING_PRIVATE_SCALAR_HEX) != bool(
                ACL_TRANSITION_SIGNING_KEY_ID_RAW
            ):
                raise ValueError(
                    "transition signer scalar and key ID must be configured together"
                )
            if ACL_TRANSITION_SIGNING_PRIVATE_SCALAR_HEX:
                _acl_transition_signers = (
                    DeterministicP256Signer(
                        int(ACL_TRANSITION_SIGNING_PRIVATE_SCALAR_HEX, 16),
                        signing_key_id=int(ACL_TRANSITION_SIGNING_KEY_ID_RAW),
                    ),
                )
            _acl_service = AclManagementService(
                AclStore(get_db, dialect="mysql", close_connections=True),
                _acl_signer,
                _AclMqttPublisher(),
                lease_seconds=_acl_lease_seconds,
                legacy_lookup_enabled=ACL_LEGACY_DEVICE_LOOKUP_ENABLED,
                legacy_hmac_key=ACL_LEGACY_REF_HMAC_KEY.encode("utf-8"),
                transition_signers=_acl_transition_signers,
            )
            app.include_router(
                create_acl_router(
                    _acl_service,
                    AclApiConfig(
                        enabled=True,
                        enrollment_credentials=_acl_enrollment_credentials,
                        admin_key=ACL_ADMIN_API_KEY,
                        target_credentials=_acl_target_credentials,
                        personal_enabled=ACL_PERSONAL_ENROLLMENT_ENABLED,
                        personal_api_key=GATEKEEPER_API_KEY,
                        personal_tenant_id=ACL_PERSONAL_TENANT_ID,
                        personal_door_id=ACL_PERSONAL_DOOR_ID,
                    ),
                )
            )
            _acl_runtime_ready = True
            log.info(
                "[ACL-MANAGEMENT] Hardwareless RC enabled (signing_key_id=%s, lease=%ss, legacy_lookup=%s)",
                _acl_signing_key_id,
                _acl_lease_seconds,
                ACL_LEGACY_DEVICE_LOOKUP_ENABLED,
            )
        except Exception:
            # Do not log exception text/traceback: malformed signing input can contain key material.
            log.error(
                "[ACL-MANAGEMENT] initialization failed; legacy/manual_remote/OTA routes remain active"
            )

# 정적 파일 디렉토리 마운트
# Administrator sessions are mTLS-authenticated, server-side, short lived, and
# fail closed when ADMIN_MTLS_IDENTITIES_JSON is not configured.
@app.post("/api/v1/admin/sessions")
def create_admin_session(request: Request, response: Response):
    identity = admin_security.authenticate_mtls(request)
    token, principal = admin_security.issue_session(identity)
    response.set_cookie(
        ADMIN_SESSION_COOKIE, token, max_age=admin_security.session_seconds,
        httponly=True, secure=True, samesite="strict", path="/",
    )
    return {"expires_at": principal.expires_at, "csrf_token": principal.csrf_token}


@app.post("/api/v1/admin/personal-sessions")
def create_personal_admin_session(payload: PersonalAdminLoginSchema, request: Request, response: Response):
    identity = admin_security.authenticate_personal_password(request, payload.password)
    token, principal = admin_security.issue_session(identity)
    response.set_cookie(
        ADMIN_SESSION_COOKIE, token, max_age=admin_security.session_seconds,
        httponly=True, secure=True, samesite="strict", path="/",
    )
    return {
        "expires_at": principal.expires_at,
        "csrf_token": principal.csrf_token,
        "auth_method": principal.auth_method,
    }


@app.get("/api/v1/admin/session")
def get_admin_session(request: Request):
    principal = _admin_principal(request, roles=(ROLE_ADMIN, ROLE_AUDITOR, ROLE_OPERATOR))
    return {
        "expires_at": principal.expires_at,
        "csrf_token": principal.csrf_token,
        "auth_method": principal.auth_method,
    }


@app.post("/api/v1/admin/sessions/rotate")
def rotate_admin_sessions(request: Request):
    _admin_principal(request, unsafe=True, roles=(ROLE_ADMIN,), reauthenticate=True)
    admin_security.rotate_sessions()
    return {"status": "rotated"}


static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/admin/login", response_class=HTMLResponse)
def get_admin_login():
    return FileResponse(os.path.join(static_dir, "admin_login.html"), media_type="text/html")

# ─── Web & Endpoints ──────────────────────────────────────────
@app.get("/app", response_class=HTMLResponse)
def get_webview_app():
    """모바일 앱 WebView 내에 렌더링될 HTML 메인 화면 반환"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return HTMLResponse("<h1>Smart Gatekeeper Web App</h1><p>static/index.html not found</p>")

@app.get("/admin", response_class=HTMLResponse)
def get_admin_console(request: Request):
    try:
        _admin_principal(request, roles=(ROLE_ADMIN, ROLE_AUDITOR, ROLE_OPERATOR))
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
        raise
    """관리자 콘솔 웹 화면 반환"""
    admin_path = os.path.join(static_dir, "admin.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path, media_type="text/html")
    return HTMLResponse("<h1>Smart Gatekeeper Admin Console</h1><p>static/admin.html not found</p>")

@app.get("/api/v1/admin/tenants")
def get_all_tenants_admin(request: Request):
    principal = _admin_principal(request, roles=(ROLE_ADMIN, ROLE_AUDITOR))
    """관리자용 전체 세입자 및 승인 대기 세입자 목록 조회"""
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, unit_number, ble_device_mac, is_active "
                "FROM tenants ORDER BY id DESC"
            )
            rows = [row for row in cur.fetchall() if principal.can_access_tenant(_legacy_tenant_scope(row["id"]))]
            return JSONResponse(content=rows, headers={"Content-Type": "application/json; charset=utf-8"})
    except Exception as e:
        log.error("[ADMIN-DB] tenant list unavailable")
        raise HTTPException(status_code=503, detail="tenant data unavailable") from e
        # DB 조회 불가 시 기본 목데이터 제공
        return JSONResponse(content=[
            {"id": 1, "name": "홍길동", "unit_number": "101호", "ble_device_mac": "AA:BB:CC:DD:EE:01", "is_active": True},
            {"id": 2, "name": "김철수", "unit_number": "202호", "ble_device_mac": "11:22:33:44:55:66", "is_active": False}
        ], headers={"Content-Type": "application/json; charset=utf-8"})
    finally:
        if conn:
            conn.close()

@app.post("/api/v1/admin/tenants/{tenant_id}/approve")
def approve_tenant(tenant_id: int, request: Request):
    principal = _admin_principal(request, unsafe=True, roles=(ROLE_ADMIN,), tenant_scope=_legacy_tenant_scope(tenant_id), reauthenticate=True)
    idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="bounded Idempotency-Key required")
    """관리자 세입자 승인 처리 (is_active = true)"""
    log.info("[ADMIN] tenant approval requested")
    conn = None
    try:
        conn = get_db()
        conn.begin()
        with conn.cursor() as cur:
            _audit_admin(conn, principal, _legacy_tenant_scope(tenant_id), "TENANT_APPROVED", str(tenant_id), idempotency_key)
            cur.execute("UPDATE tenants SET is_active = true WHERE id = %s", (tenant_id,))
            if cur.rowcount != 1:
                raise LookupError("tenant not found")
        conn.commit()
        return JSONResponse(content={"status": "approved", "tenant_id": tenant_id})
    except Exception as e:
        log.error("[ADMIN] tenant approval unavailable")
        if conn:
            conn.rollback()
        raise HTTPException(status_code=503, detail="tenant approval unavailable")
    finally:
        if conn:
            conn.close()

@app.post("/api/v1/admin/tenants/{tenant_id}/reject")
def reject_tenant(tenant_id: int, request: Request):
    principal = _admin_principal(request, unsafe=True, roles=(ROLE_ADMIN,), tenant_scope=_legacy_tenant_scope(tenant_id), reauthenticate=True)
    idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="bounded Idempotency-Key required")
    """관리자 세입자 권한 회수/거절 처리 (is_active = false)"""
    log.info("[ADMIN] tenant revocation requested")
    conn = None
    try:
        conn = get_db()
        conn.begin()
        with conn.cursor() as cur:
            _audit_admin(conn, principal, _legacy_tenant_scope(tenant_id), "TENANT_REVOKED", str(tenant_id), idempotency_key)
            cur.execute("UPDATE tenants SET is_active = false WHERE id = %s", (tenant_id,))
            if cur.rowcount != 1:
                raise LookupError("tenant not found")
        conn.commit()
        return JSONResponse(content={"status": "rejected", "tenant_id": tenant_id})
    except Exception as e:
        log.error("[ADMIN] tenant revocation unavailable")
        if conn:
            conn.rollback()
        raise HTTPException(status_code=503, detail="tenant rejection unavailable")
    finally:
        if conn:
            conn.close()


@app.patch("/api/v1/admin/tenants/{tenant_id}")
def update_tenant_admin(
    tenant_id: int, payload: AdminTenantUpdateSchema, request: Request
):
    principal = _admin_principal(
        request,
        unsafe=True,
        roles=(ROLE_ADMIN,),
        tenant_scope=_legacy_tenant_scope(tenant_id),
        reauthenticate=True,
    )
    idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="bounded Idempotency-Key required")
    name = payload.name.strip()
    unit_number = payload.unit_number.strip()
    if not name or not unit_number:
        raise HTTPException(status_code=422, detail="name and unit number are required")
    conn = None
    try:
        conn = get_db()
        conn.begin()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_uuid FROM tenants WHERE id=%s FOR UPDATE",
                (tenant_id,),
            )
            existing = cur.fetchone()
            if existing is None:
                raise LookupError("tenant not found")
            _audit_admin(
                conn,
                principal,
                _legacy_tenant_scope(tenant_id),
                "TENANT_PROFILE_UPDATED",
                str(tenant_id),
                idempotency_key,
            )
            cur.execute(
                "UPDATE tenants SET name=%s, unit_number=%s WHERE id=%s",
                (name, unit_number, tenant_id),
            )
            if cur.rowcount != 1:
                raise RuntimeError("tenant update lost its state lock")
            canonical_tenant = existing.get("tenant_uuid")
            if canonical_tenant:
                cur.execute(
                    "UPDATE acl_tenants SET display_name=%s, updated_at=%s "
                    "WHERE tenant_id=%s",
                    (f"{name} {unit_number}"[:100], int(time.time()), canonical_tenant),
                )
        conn.commit()
        return {"status": "updated", "tenant_id": tenant_id}
    except LookupError as exc:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as exc:
        if conn:
            conn.rollback()
        log.error("[ADMIN] tenant profile update unavailable")
        raise HTTPException(status_code=503, detail="tenant profile update unavailable") from exc
    finally:
        if conn:
            conn.close()


@app.delete("/api/v1/admin/tenants/{tenant_id}")
def delete_tenant_admin(tenant_id: int, request: Request):
    principal = _admin_principal(
        request,
        unsafe=True,
        roles=(ROLE_ADMIN,),
        tenant_scope=_legacy_tenant_scope(tenant_id),
        reauthenticate=True,
    )
    idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="bounded Idempotency-Key required")

    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, is_active, tenant_uuid, credential_mode, credential_id "
                "FROM tenants WHERE id=%s",
                (tenant_id,),
            )
            account = cur.fetchone()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="tenant deletion preflight unavailable") from exc
    finally:
        if conn:
            conn.close()
    if account is None:
        raise HTTPException(status_code=404, detail="tenant not found")

    credential_id = account.get("credential_id")
    if credential_id is None and str(account.get("credential_mode") or "legacy") != "legacy":
        raise HTTPException(
            status_code=409,
            detail="open the enrolled phone once to reconcile its credential before deletion",
        )
    if credential_id is not None:
        service = globals().get("_acl_service")
        if not globals().get("_acl_runtime_ready", False) or service is None:
            raise HTTPException(status_code=503, detail="credential revocation unavailable")
        try:
            service.revoke_credential(
                ACL_PERSONAL_TENANT_ID,
                str(credential_id),
                actor_ref=f"admin:{principal.subject}",
            )
        except Exception as exc:
            # Revocation is durable before MQTT publication. Keep the account
            # row for a safe retry instead of claiming deletion.
            log.error("[ADMIN] credential revocation or ACL publication unavailable")
            raise HTTPException(
                status_code=503,
                detail="credential revocation or ACL publication unavailable",
            ) from exc

    conn = None
    try:
        conn = get_db()
        conn.begin()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_uuid, credential_id FROM tenants WHERE id=%s FOR UPDATE",
                (tenant_id,),
            )
            locked = cur.fetchone()
            if locked is None:
                raise LookupError("tenant not found")
            if str(locked.get("credential_id") or "") != str(credential_id or ""):
                raise RuntimeError("tenant credential changed during deletion")

            replacement = None
            canonical_tenant = locked.get("tenant_uuid")
            if canonical_tenant:
                cur.execute(
                    "SELECT id, name, unit_number, credential_id FROM tenants "
                    "WHERE id<>%s AND is_active=TRUE ORDER BY id LIMIT 1 FOR UPDATE",
                    (tenant_id,),
                )
                replacement = cur.fetchone()
                if replacement is not None and not replacement.get("credential_id"):
                    raise HTTPException(
                        status_code=409,
                        detail="open another active phone once before deleting the tenant owner",
                    )
                if replacement is not None:
                    cur.execute(
                        "UPDATE tenants SET tenant_uuid=NULL WHERE id=%s",
                        (tenant_id,),
                    )
                    cur.execute(
                        "UPDATE tenants SET tenant_uuid=%s, credential_mode='dual' WHERE id=%s",
                        (canonical_tenant, replacement["id"]),
                    )
                    cur.execute(
                        "UPDATE acl_tenants SET display_name=%s, updated_at=%s "
                        "WHERE tenant_id=%s",
                        (
                            f"{replacement['name']} {replacement['unit_number']}"[:100],
                            int(time.time()),
                            canonical_tenant,
                        ),
                    )

            _audit_admin(
                conn,
                principal,
                _legacy_tenant_scope(tenant_id),
                "TENANT_ACCOUNT_DELETED",
                str(tenant_id),
                idempotency_key,
            )
            cur.execute("DELETE FROM tenants WHERE id=%s", (tenant_id,))
            if cur.rowcount != 1:
                raise RuntimeError("tenant deletion lost its state lock")
        conn.commit()
        return {"status": "deleted", "tenant_id": tenant_id}
    except LookupError as exc:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as exc:
        if conn:
            conn.rollback()
        log.error("[ADMIN] tenant account deletion unavailable")
        raise HTTPException(status_code=503, detail="tenant account deletion unavailable") from exc
    finally:
        if conn:
            conn.close()


@app.get("/live", status_code=status.HTTP_200_OK)
@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """Process-only liveness. Use /ready for dependency admission."""
    return JSONResponse(content={
        "status": "healthy",
        "scope": "process_liveness_only",
        "service": "smart-gatekeeper-api",
        "version": "2.1.0",
        "build_sha": BUILD_SHA,
    })


def _readiness_snapshot() -> tuple[bool, dict]:
    checks = {
        "database": False,
        "database_schema": False,
        "mqtt": False,
        "runtime_secrets": bool(DB_PASSWORD and len(OPS_HMAC_KEY) >= 32),
        "control_api_auth": len(GATEKEEPER_API_KEY) >= 32,
        "admin_auth": admin_security.browser_login_ready,
        "acl_management": bool(ACL_MANAGEMENT_ENABLED and _acl_runtime_ready),
        "legacy_prearm_retired": not _legacy_prearm_authority_enabled(),
        "build_identity": bool(re.fullmatch(r"[a-f0-9]{40}", BUILD_SHA)),
    }
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 AS ready")
            checks["database"] = bool(cur.fetchone())
            if (
                re.fullmatch(r"[0-9]{3}", EXPECTED_DB_SCHEMA_VERSION)
                and re.fullmatch(r"[a-f0-9]{64}", EXPECTED_DB_SCHEMA_SHA256)
            ):
                cur.execute(
                    "SELECT script_sha256 FROM schema_migrations WHERE version=%s",
                    (EXPECTED_DB_SCHEMA_VERSION,),
                )
                schema = cur.fetchone()
                checks["database_schema"] = bool(
                    schema
                    and secrets.compare_digest(
                        schema["script_sha256"], EXPECTED_DB_SCHEMA_SHA256
                    )
                )
    except Exception:
        _ops_metrics.event("readiness", "database_failed")
    finally:
        if conn:
            conn.close()
    if _command_provisioning_error() is None and HAS_PAHO_MQTT:
        checks["mqtt"] = _persistent_publisher().probe(timeout=1.0)
        if not checks["mqtt"]:
            _ops_metrics.event("readiness", "mqtt_failed")
    return all(checks.values()), checks


def _legacy_prearm_authority_enabled() -> bool:
    """One source of truth for the raw device-id legacy authority boundary."""
    return ACL_LEGACY_DEVICE_LOOKUP_ENABLED


@app.get("/ready")
def readiness_check():
    ready, checks = _readiness_snapshot()
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "service": "smart-gatekeeper-api",
            "build_sha": BUILD_SHA,
            "checks": checks,
        },
    )


@app.get("/api/v1/admin/metrics", response_class=PlainTextResponse)
def operational_metrics(request: Request):
    _admin_principal(request, roles=(ROLE_ADMIN, ROLE_AUDITOR), tenant_scope="*")
    breaker_state = _mqtt_publisher.breaker.state if _mqtt_publisher else "closed"
    return PlainTextResponse(
        _ops_metrics.prometheus(BUILD_SHA, breaker_state),
        media_type="text/plain; version=0.0.4",
    )

@app.get("/api/v1/download/apk")
@app.get("/download/apk")
@app.get("/api/v1/download/ks-house-gatekeeper.apk")
@app.get("/gatekeeper_apk/{filename}")
def download_latest_apk(filename: str = "ks-house-gatekeeper.apk"):

    """Port 4442 동일 포트에서 최신 APK 파일 직접 다운로드 제공"""
    apk_paths = [
        os.path.join("/app/gatekeeper_apk", filename),
        os.path.join("/app/gatekeeper_apk", "ks-house-gatekeeper.apk"),
        os.path.join("/app/static/gatekeeper_apk", filename),
        "/docker/smartbox_ota/gatekeeper_apk/" + filename,
        "/volume1/docker/smartbox_ota/gatekeeper_apk/" + filename,
    ]
    for path in apk_paths:
        if os.path.exists(path):
            log.info("[APK-DOWNLOAD] verified local artifact selected")
            return FileResponse(
                path=path,
                filename="ks-house-gatekeeper.apk",
                media_type="application/vnd.android.package-archive"
            )
    log.error("[APK-DOWNLOAD] APK 파일을 서버에서 찾을 수 없습니다.")
    return JSONResponse(status_code=404, content={"error": "APK file not found on server"})

@app.get("/api/v1/download/version.json")
def download_version_json():
    """Port 4442 동일 포트에서 version.json 동적 제공"""
    v_paths = [
        "/app/gatekeeper_apk/version.json",
        "/docker/smartbox_ota/gatekeeper_apk/version.json",
        "/volume1/docker/smartbox_ota/gatekeeper_apk/version.json",
    ]
    for path in v_paths:
        if os.path.exists(path):
            return FileResponse(path=path, media_type="application/json")
    return JSONResponse(content={
        "version": "1.0.0",
        "build_number": 10,
        "apk_url": "https://tworimpa.synology.me:4442/api/v1/download/apk"
    })

@app.get("/api/v1/config")

def get_remote_config():
    """Flutter Native Shell 및 모바일 앱에 동적 설정 반환 (Remote Config)"""
    return JSONResponse(
        content={
            "beacon_uuid": BEACON_UUID,
            "cooldown_sec": APP_COOLDOWN_SEC,
            "rssi_threshold": APP_RSSI_THRESHOLD,
            "apk_version_url": APK_VERSION_URL,
            "apk_download_url": APK_DOWNLOAD_URL,
            "webview_url": WEBVIEW_URL
        },
        headers={"Content-Type": "application/json; charset=utf-8"}
    )

@app.get("/api/v1/user/me")
def get_user_me(
    device_id: str = Query(...),
    _auth=Depends(require_api_key),
):
    """현재 기기(device_id)의 세입자 등록 상태 및 세입자 정보 조회"""
    mac_upper = legacy_device_storage_id(device_id)
    log.info("[USER-ME] retired device-id lookup invoked")
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, unit_number, is_active FROM tenants "
                "WHERE ble_device_mac = %s LIMIT 1",
                (mac_upper,)
            )
            tenant = cur.fetchone()
            if not tenant:
                return JSONResponse(content={"status": "unregistered", "message": "미등록 기기입니다."})
            
            if not tenant["is_active"]:
                return JSONResponse(content={
                    "status": "pending",
                    "tenant_name": tenant["name"],
                    "unit_number": tenant["unit_number"],
                    "message": "승인 대기 중입니다."
                })
            
            return JSONResponse(content={
                "status": "approved",
                "tenant_name": tenant["name"],
                "unit_number": tenant["unit_number"],
                "message": "출입 승인 완료"
            })
    except Exception:
        log.error("[USER-ME] lookup unavailable")
        return JSONResponse(
            content={
                "status": "unregistered",
                "message": "사용자 정보를 조회할 수 없습니다.",
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    finally:
        if conn:
            conn.close()

@app.post("/api/v1/user/request")
def request_user_access(
    req: UserRequestSchema,
    _auth=Depends(require_api_key),
):
    """신규 세입자 가입 및 출입 권한 신청"""
    mac_upper = legacy_device_storage_id(req.device_id)
    log.info("[USER-REQ] authenticated personal enrollment requested")
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # 기존 레코드 존재 시 업데이트, 미존재 시 인서트
            cur.execute(
                "INSERT INTO tenants (name, unit_number, ble_device_mac, is_active) "
                "VALUES (%s, %s, %s, false) "
                "ON DUPLICATE KEY UPDATE name = VALUES(name), unit_number = VALUES(unit_number)",
                (req.name, req.room_no, mac_upper)
            )
        return JSONResponse(
            content={"status": "pending", "message": "가입 신청 완료. 관리자 승인 대기 중"},
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
    except Exception as e:
        log.error("[USER-REQ] request persistence unavailable")
        raise HTTPException(status_code=503, detail="request persistence unavailable") from e
    finally:
        if conn:
            conn.close()

@app.post("/api/v1/door/prearm")
def door_prearm(
    req: PrearmRequestSchema,
    _auth=Depends(require_api_key),
):
    """
    BLE 비콘 감지 시 Flutter Native Shell이 호출하는 Pre-arm 사전 승인 API.

    ⚠️ **fail-closed 설계** (issue.md P3-22).
    이전 구현은 세 가지 경로로 무조건 arm 을 발행했다:
      1. device_id 가 없으면 검증을 완전히 건너뛰었다
      2. DB 예외가 나면 로그만 남기고 통과해 tenant_id=1 로 arm 을 발행했다
         → DB 가 죽으면 미등록 기기에도 문이 열렸다
      3. 인증이 전혀 없었다
    지금은 세 경로 모두 거부한다. 승인은 "등록되고 승인된 기기"에만 부여된다.
    """
    if not _legacy_prearm_authority_enabled():
        log.warning("[PREARM-REJECT] legacy device identifier authority retired")
        return JSONResponse(
            status_code=410,
            content={
                "result": "retired",
                "message": "Signed per-device credential flow is required.",
            },
        )
    log.info("[PREARM] beacon pre-arm request received")

    # ── 1. device_id 는 필수 ────────────────────────────────────────────
    device_id = (req.device_id or "").strip()
    if not device_id:
        log.warning("[PREARM-REJECT] device_id 없는 Pre-arm 요청 거부")
        return JSONResponse(
            status_code=400,
            content={"result": "denied", "message": "기기 식별자가 없어 출입을 승인할 수 없습니다."},
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

    # ── 2. 등록 + 승인 세입자 검증 (실패 시 절대 arm 하지 않는다) ────────
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, unit_number, is_active FROM tenants WHERE ble_device_mac = %s LIMIT 1",
                (device_id.upper(),)
            )
            row = cur.fetchone()

        if not row:
            log.warning("[PREARM-REJECT] unregistered device pre-arm rejected")
            return JSONResponse(
                status_code=403,
                content={"result": "denied", "message": "미등록 세입자 기기입니다."},
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        if not row["is_active"]:
            log.warning("[PREARM-REJECT] inactive credential rejected")
            return JSONResponse(
                status_code=403,
                content={"result": "denied", "message": "관리자 승인 대기 중인 세입자입니다."},
                headers={"Content-Type": "application/json; charset=utf-8"}
            )

        user_label = f"{row['name']}({row['unit_number']})"
        tenant_id = row["id"]

    except Exception as e:
        # fail-closed: 검증할 수 없으면 승인하지 않는다.
        log.error("[PREARM-REJECT] database verification unavailable; fail closed")
        return JSONResponse(
            status_code=503,
            content={
                "result": "error",
                "message": "출입 검증 서버 오류로 승인할 수 없습니다. 잠시 후 다시 시도해주세요."
            },
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
    finally:
        if conn:
            conn.close()

    # ── 3. 검증 통과 — arm 발행 ─────────────────────────────────────────
    arm_ok = publish_arm_to_mqtt(user_label, tenant_id)
    if not arm_ok:
        log.error("[PREARM-ERROR] verified credential command publication failed")
        return JSONResponse(
            status_code=503,
            content={
                "result": "error",
                "message": "Target에 출입 승인 명령을 전달하지 못했습니다.",
                "mqtt_published": False,
                "user": user_label,
            },
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
    return JSONResponse(
        content={
            "result": "armed",
            "ttl_sec": 60,
            "mqtt_published": True,
            "user": user_label,
        },
        headers={"Content-Type": "application/json; charset=utf-8"}
    )


@app.post("/api/v1/admin/control/force-open")
def request_force_open(req: ForceOpenRequestSchema, request: Request):
    """Create a two-person, re-authenticated force-open proposal.

    This never accepts a device identifier as authority and deliberately does
    not publish MQTT until a separate authorized approver completes it.
    """
    principal = _admin_principal(
        request, unsafe=True, roles=(ROLE_OPERATOR,), tenant_scope=req.tenant_id,
        reauthenticate=True,
    )
    idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="bounded Idempotency-Key required")
    now = int(time.time())
    proposal_id = secrets.token_hex(24)
    idempotency_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    conn = None
    try:
        conn = get_db()
        conn.begin()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT approval_id FROM force_open_approvals WHERE proposer_subject=%s AND tenant_scope=%s AND idempotency_hash=%s FOR UPDATE",
                (principal.subject, req.tenant_id, idempotency_hash),
            )
            existing = cur.fetchone()
            if existing:
                proposal_id = existing["approval_id"]
            else:
                cur.execute(
                    "INSERT INTO force_open_approvals (approval_id,tenant_scope,proposer_subject,reason,idempotency_hash,expires_at,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (proposal_id, req.tenant_id, principal.subject, req.reason, idempotency_hash, now + 300, now),
                )
                _audit_admin(conn, principal, req.tenant_id, "FORCE_OPEN_PROPOSED", proposal_id, idempotency_key)
        conn.commit()
        return JSONResponse(status_code=202, content={"status": "approval_required", "approval_id": proposal_id})
    except Exception as exc:
        log.error("[FORCE-OPEN] proposal audit unavailable")
        raise HTTPException(status_code=503, detail="force-open proposal unavailable") from exc
    finally:
        if conn:
            conn.close()


@app.post("/api/v1/admin/control/force-open/{approval_id}/approve")
def approve_force_open(approval_id: str, request: Request):
    now = int(time.time())
    conn = None
    proposal = None
    principal = None
    idempotency_key = None
    try:
        conn = get_db()
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM force_open_approvals WHERE approval_id=%s FOR UPDATE", (approval_id,))
            proposal = cur.fetchone()
            if not proposal or proposal["status"] != "PENDING" or int(proposal["expires_at"]) <= now:
                raise LookupError("force-open proposal is unavailable")
        principal = _admin_principal(
            request, unsafe=True, roles=(ROLE_APPROVER,), tenant_scope=proposal["tenant_scope"],
            reauthenticate=True,
        )
        if secrets.compare_digest(principal.subject, proposal["proposer_subject"]):
            raise HTTPException(status_code=403, detail="force-open requires a distinct approver")
        idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
        if not idempotency_key or len(idempotency_key) > 128:
            raise HTTPException(status_code=400, detail="bounded Idempotency-Key required")
        with conn.cursor() as cur:
            # This durable disposition is intentionally committed before any
            # physical-effect attempt.  A later DB outage therefore cannot
            # turn a broker success into a retry-safe PUBLISHING ambiguity.
            cur.execute("UPDATE force_open_approvals SET status='RECONCILIATION_REQUIRED', approver_subject=%s WHERE approval_id=%s AND status='PENDING'", (principal.subject, approval_id))
            if cur.rowcount != 1:
                raise RuntimeError("force-open was already reserved")
        _audit_admin(conn, principal, proposal["tenant_scope"], "FORCE_OPEN_RECONCILIATION_REQUIRED", approval_id, idempotency_key)
        conn.commit()
        if not publish_force_open_to_mqtt("authorized-control-plane"):
            raise RuntimeError("MQTT publish failed")
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("UPDATE force_open_approvals SET status='PUBLISHED', published_at=%s WHERE approval_id=%s AND status='RECONCILIATION_REQUIRED'", (int(time.time()), approval_id))
            if cur.rowcount != 1:
                raise RuntimeError("force-open publication reconciliation required")
        _audit_admin(conn, principal, proposal["tenant_scope"], "FORCE_OPEN_PUBLISHED", approval_id, idempotency_key)
        conn.commit()
        return {"status": "published", "approval_id": approval_id}
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except LookupError as exc:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        if conn:
            conn.rollback()
        log.error("[FORCE-OPEN] durable reconciliation state retained or publication blocked")
        raise HTTPException(status_code=503, detail="force-open publication unavailable or reconciliation required") from exc
    finally:
        if conn:
            conn.close()


@app.post("/api/v1/door/open")
def manual_open_v2(
    req: ManualOpenV2Request,
    request: Request,
    x_device_proof: Optional[str] = Header(default=None, alias="X-Device-Proof"),
    x_idempotency_key: Optional[str] = Header(default=None, alias=IDEMPOTENCY_HEADER),
):
    """N/N-1-safe URI for legacy HMAC v2 and AndroidKeyStore signature v3."""
    now = int(time.time())
    if req.credential_id is not None or req.signature_raw64 is not None:
        if not all(
            (
                req.credential_id,
                req.signature_raw64,
                req.reason,
                req.nonce,
                req.expires_at,
                x_idempotency_key,
            )
        ):
            raise HTTPException(
                status_code=426,
                detail="manual control requires the signed credential envelope",
            )
        if (
            not now < int(req.expires_at) <= now + 120
            or len(x_idempotency_key) > 128
            or req.reason != "mobile_manual_button"
        ):
            raise HTTPException(
                status_code=400,
                detail="manual control proof expiry, reason or idempotency is invalid",
            )
        if not globals().get("_acl_runtime_ready", False):
            raise HTTPException(status_code=503, detail="credential control unavailable")
        conn = None
        try:
            conn = get_db()
            conn.begin()
            with conn.cursor() as cur:
                # AndroidKeyStore credentials and door grants belong to the
                # personal ACL scope.  COMMAND_* is the independent legacy
                # signed-MQTT command envelope and may intentionally use a
                # different tenant/door identity on an installed Target.
                cur.execute(
                    "SELECT c.credential_id,c.tenant_id,c.public_key_sec1,"
                    "c.status,c.expires_at,t.status AS tenant_status,"
                    "l.id AS legacy_tenant_id "
                    "FROM credentials c JOIN acl_tenants t ON t.tenant_id=c.tenant_id "
                    "LEFT JOIN tenants l ON l.credential_id=c.credential_id "
                    "WHERE c.credential_id=%s FOR UPDATE",
                    (req.credential_id,),
                )
                credential = cur.fetchone()
                if (
                    not credential
                    or credential["status"] != "ACTIVE"
                    or credential["tenant_status"] != "ACTIVE"
                    or (
                        credential.get("expires_at") is not None
                        and int(credential["expires_at"]) <= now
                    )
                    or not secrets.compare_digest(
                        str(credential["tenant_id"]), ACL_PERSONAL_TENANT_ID
                    )
                ):
                    raise PermissionError("mobile credential is inactive")
                cur.execute(
                    "SELECT permissions FROM credential_door_grants "
                    "WHERE tenant_id=%s AND door_id=%s AND credential_id=%s "
                    "AND revoked_at IS NULL FOR UPDATE",
                    (
                        ACL_PERSONAL_TENANT_ID,
                        ACL_PERSONAL_DOOR_ID,
                        req.credential_id,
                    ),
                )
                grant = cur.fetchone()
                if not grant or (int(grant["permissions"]) & 1) != 1:
                    raise PermissionError("mobile credential has no open grant")
                canonical = build_mobile_manual_open_input(
                    req.credential_id,
                    req.nonce,
                    int(req.expires_at),
                    req.reason,
                    x_idempotency_key,
                )
                if not verify_raw64(
                    bytes.fromhex(str(credential["public_key_sec1"])),
                    canonical,
                    bytes.fromhex(req.signature_raw64),
                ):
                    raise PermissionError("mobile credential proof rejected")
                cur.execute(
                    "INSERT INTO mobile_credential_control_nonces "
                    "(credential_id,nonce_hash,action,expires_at,consumed_at) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (
                        req.credential_id,
                        hashlib.sha256(req.nonce.encode("utf-8")).hexdigest(),
                        "manual_remote_v3",
                        req.expires_at,
                        now,
                    ),
                )
            conn.commit()
        except PermissionError as exc:
            if conn:
                conn.rollback()
            raise HTTPException(status_code=403, detail="manual control denied") from exc
        except pymysql.err.IntegrityError as exc:
            if conn:
                conn.rollback()
            raise HTTPException(
                status_code=409,
                detail="manual control proof already consumed",
            ) from exc
        except HTTPException:
            if conn:
                conn.rollback()
            raise
        except Exception as exc:
            if conn:
                conn.rollback()
            raise HTTPException(status_code=503, detail="manual control unavailable") from exc
        finally:
            if conn:
                conn.close()
        legacy_tenant_id = credential.get("legacy_tenant_id")
        if not publish_force_open_to_mqtt("credential-signature-v3"):
            _write_access_event(
                legacy_tenant_id,
                "MOBILE_REMOTE",
                False,
                None,
                "broker delivery failed",
            )
            raise HTTPException(status_code=503, detail="manual control was not delivered")
        _write_access_event(
            legacy_tenant_id,
            "MOBILE_REMOTE",
            True,
            None,
            "broker accepted; physical result unconfirmed",
        )
        request_id = hashlib.sha256(
            f"{req.credential_id}:{req.nonce}".encode("utf-8")
        ).hexdigest()[:24]
        return {
            "result": "requested",
            "delivery": "broker-ack-only",
            "auth": "credential-signature-v3",
            "request_id": request_id,
        }

    if not all((req.device_id, req.reason, req.nonce, req.expires_at, x_device_proof, x_idempotency_key)):
        raise HTTPException(status_code=426, detail="manual control requires the v2 proof envelope")
    if not now < int(req.expires_at) <= now + 120 or len(x_idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="manual control proof expiry or idempotency is invalid")
    conn = None
    try:
        conn = get_db()
        conn.begin()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, auth_key, is_active FROM tenants WHERE ble_device_mac = %s LIMIT 1",
                (req.device_id.strip().upper(),),
            )
            tenant = cur.fetchone()
            if not tenant or not tenant["is_active"] or not tenant.get("auth_key"):
                raise PermissionError("manual control credential is unavailable")
            payload = "|".join((str(tenant["id"]), req.device_id, "manual_open_v2", req.reason, req.nonce, str(req.expires_at), x_idempotency_key))
            expected = hmac.new(tenant["auth_key"].encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(x_device_proof.lower(), expected):
                raise PermissionError("manual control proof rejected")
            cur.execute(
                "INSERT INTO mobile_control_nonces (tenant_id, nonce_hash, action, expires_at, consumed_at) VALUES (%s, %s, %s, %s, %s)",
                (tenant["id"], hashlib.sha256(req.nonce.encode("utf-8")).hexdigest(), "manual_open_v2", req.expires_at, now),
            )
        conn.commit()
    except PermissionError as exc:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=403, detail="manual control denied") from exc
    except Exception as exc:
        if conn:
            conn.rollback()
        # Duplicate nonce and database failures must both fail closed without
        # emitting an MQTT request.
        raise HTTPException(status_code=503, detail="manual control unavailable") from exc
    finally:
        if conn:
            conn.close()
    if not publish_force_open_to_mqtt("v2-manual-proof"):
        raise HTTPException(status_code=503, detail="manual control was not delivered")
    return {"result": "requested", "delivery": "broker-ack-only"}


# Deliberately not registered: retained only as a migration reference until the
# mobile client no longer imports its request model.  It cannot receive HTTP.
def door_force_open(
    req: ForceOpenRequestSchema,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-KEY"),
):
    """
    WebView 수동 '문 열기' 터치 시 즉시 릴레이 강제 개방 명령 하달.

    ⚠️ **fail-closed 설계** (issue.md P3-22).
    Pre-arm 과 달리 이 API 는 초음파 게이트 없이 **즉시 문을 연다.** 그런데
    이전 구현은 다음 경우에 모두 무조건 문을 열었다:
      1. device_id 가 없으면 검증 없이 개방 (관리자 콘솔의 "마스터 개방"이 이에 의존했다)
      2. device_id 가 미등록이어도 `if row:` 를 그냥 통과해 개방
      3. DB 예외가 나면 로그만 남기고 개방

    두 개의 명확한 경로만 허용한다:
      · **세입자 경로** — 등록되고 승인된 device_id
      · **마스터 경로** — device_id 없이 유효한 X-API-KEY

    ⚠️ 이 엔드포인트는 정적 WebView 페이지에서 호출되므로 세입자 경로에는
       키 인증을 요구하지 않는다(브라우저가 비밀을 안전히 보관할 수 없다).
       세입자 경로의 실질적 인증은 device_id ↔ tenants 테이블 검증이다.
       세션 기반 인증 도입은 issue.md P3-25 로 남겨 둔다.
    """
    log.info("[FORCE-OPEN] retired device-id control invoked")

    device_id = (req.device_id or "").strip()

    # ── 마스터 경로: device_id 없음 → 반드시 유효한 API 키가 필요하다 ──────
    if not device_id:
        if not _api_key_matches(x_api_key):
            if not GATEKEEPER_API_KEY:
                message = ("마스터 개방은 서버에 GATEKEEPER_API_KEY 를 설정해야 사용할 수 있습니다. "
                           "관리자에게 문의하세요.")
                log.error("[FORCE-OPEN-REJECT] 마스터 개방 요청 거부 — GATEKEEPER_API_KEY 미설정")
            else:
                message = "마스터 개방 권한이 없습니다. 관리자 키를 확인해주세요."
                log.warning("[FORCE-OPEN-REJECT] unauthenticated request rejected")
            return JSONResponse(
                status_code=403,
                content={"result": "denied", "message": message},
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        log.info("[FORCE-OPEN] 마스터 키 인증 성공 → 강제 개방 허용")
        user_label = "마스터개방"

    # ── 세입자 경로: 등록 + 승인 검증 (실패 시 절대 열지 않는다) ──────────
    else:
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name, unit_number, is_active FROM tenants WHERE ble_device_mac = %s LIMIT 1",
                    (device_id.upper(),)
                )
                row = cur.fetchone()

            if not row:
                log.warning("[FORCE-OPEN-REJECT] retired unregistered device control rejected")
                return JSONResponse(
                    status_code=403,
                    content={"result": "denied", "message": "미등록 세입자 기기입니다."},
                    headers={"Content-Type": "application/json; charset=utf-8"}
                )
            if not row["is_active"]:
                log.warning("[FORCE-OPEN-REJECT] inactive credential rejected")
                return JSONResponse(
                    status_code=403,
                    content={"result": "denied", "message": "출입 권한이 승인되지 않은 세입자입니다."},
                    headers={"Content-Type": "application/json; charset=utf-8"}
                )

            user_label = f"{row['name']}({row['unit_number']})"

        except Exception as e:
            # fail-closed: 검증할 수 없으면 열지 않는다.
            log.error("[FORCE-OPEN-REJECT] database verification unavailable; fail closed")
            return JSONResponse(
                status_code=503,
                content={
                    "result": "error",
                    "message": "출입 검증 서버 오류로 문을 열 수 없습니다. 잠시 후 다시 시도해주세요."
                },
                headers={"Content-Type": "application/json; charset=utf-8"}
            )
        finally:
            if conn:
                conn.close()

    force_ok = publish_force_open_to_mqtt(user_label)
    return JSONResponse(
        content={"result": "force_opened", "message": "문이 성공적으로 열렸습니다!", "mqtt_published": force_ok},
        headers={"Content-Type": "application/json; charset=utf-8"}
    )


TARGET_CONFIG_FILE = os.getenv(
    "TARGET_CONFIG_FILE",
    os.path.join(os.path.dirname(__file__), "target_config.json"),
)

def load_target_config() -> dict:
    default_config = {
        "tx_power": 9,
        "tof_distance": 50,
        "duration": 60000,
        "relay_cooldown": 3000,
        "updated_at": None
    }
    if os.path.exists(TARGET_CONFIG_FILE):
        try:
            with open(TARGET_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_config.update(saved)
                log.info(f"[CONFIG-STORE] ✅ target_config.json 영구 설정 로드 완료: {default_config}")
        except Exception as e:
            log.error("[CONFIG-STORE] load unavailable")
    return default_config

def save_target_config(config: dict):
    try:
        with open(TARGET_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            log.info(f"[CONFIG-STORE] 💾 target_config.json 영구 저장 완료")
    except Exception as e:
        log.error("[CONFIG-STORE] save unavailable")

current_target_config = load_target_config()


@app.get("/admin/config")
@app.get("/api/v1/admin/config")
def get_admin_config(request: Request):
    _admin_principal(request, roles=(ROLE_ADMIN, ROLE_AUDITOR), tenant_scope="*")
    """현재 적용되어 있는 Target (ESP32-C6) 원격 튜닝 파라미터 조회"""
    return JSONResponse(
        content={
            "result": "success",
            "tx_power": current_target_config.get("tx_power", 9),
            "tof_distance": current_target_config.get("tof_distance", 50),
            "duration": current_target_config.get("duration", 60000),
            "relay_cooldown": current_target_config.get("relay_cooldown", 3000),
            "updated_at": current_target_config.get("updated_at")
        },
        headers={"Content-Type": "application/json; charset=utf-8"}
    )


@app.post("/admin/config")
@app.post("/api/v1/admin/config")
def update_admin_config(req: AdminConfigRequestSchema, request: Request):
    principal = _admin_principal(request, unsafe=True, roles=(ROLE_ADMIN,), tenant_scope="*", reauthenticate=True)
    idempotency_key = request.headers.get(IDEMPOTENCY_HEADER)
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="bounded Idempotency-Key required")
    """엔지니어 원격 튜닝 API — ESP32-C6 파라미터(Tx Power, ToF 거리, Pre-arm 유효시간, 릴레이 쿨다운) 실시간 변경 및 영구 저장"""
    log.info(f"[ADMIN-CONFIG] 원격 파라미터 변경 요청: tx_power={req.tx_power}, tof_distance={req.tof_distance}, duration={req.duration}, relay_cooldown={req.relay_cooldown}")
    if req.tx_power is None and req.tof_distance is None and req.duration is None and req.relay_cooldown is None:
        return JSONResponse(
            status_code=400,
            content={"result": "error", "message": "최소 하나 이상의 튜닝 파라미터를 전달해야 합니다."}
        )

    if req.tx_power is not None:
        current_target_config["tx_power"] = req.tx_power
    if req.tof_distance is not None:
        current_target_config["tof_distance"] = req.tof_distance
    if req.duration is not None:
        current_target_config["duration"] = req.duration
    if req.relay_cooldown is not None:
        current_target_config["relay_cooldown"] = req.relay_cooldown
    current_target_config["updated_at"] = datetime.now().isoformat()
    conn = None
    try:
        conn = get_db()
        _audit_admin(conn, principal, "*", "TARGET_CONFIG_CHANGED", "target-config", idempotency_key)
    except Exception as exc:
        log.error("[ADMIN-CONFIG] audit unavailable")
        raise HTTPException(status_code=503, detail="configuration change unavailable") from exc
    finally:
        if conn:
            conn.close()
    save_target_config(current_target_config)

    mqtt_results = publish_admin_config_to_mqtt(
        tx_power=req.tx_power,
        tof_distance=req.tof_distance,
        duration=req.duration,
        relay_cooldown=req.relay_cooldown
    )

    return JSONResponse(
        content={
            "result": "success",
            "message": "엔지니어 원격 튜닝 파라미터가 영구 저장 및 MQTT로 전송되었습니다.",
            "current_config": current_target_config,
            "details": mqtt_results
        },
        headers={"Content-Type": "application/json; charset=utf-8"}
    )






@app.post("/api/v1/auth/verify", response_model=AuthVerifyResponse)
def verify_access(req: AuthVerifyRequest):
    mac_upper = req.ble_mac.strip().upper()
    log.info("[AUTH] credential verification request received")

    conn = None
    tenant = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, unit_number, auth_key, is_active "
                "FROM tenants WHERE ble_device_mac = %s LIMIT 1",
                (mac_upper,)
            )
            tenant = cur.fetchone()
    except Exception:
        log.error("[DB] credential lookup unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="인증 서비스를 일시적으로 사용할 수 없습니다.",
        )
    finally:
        if conn:
            conn.close()

    if not tenant:
        log.warning("[AUTH] unregistered credential rejected")
        _log_access(mac_upper, False, req.distance_mm, "미등록 기기")
        return JSONResponse(
            content=AuthVerifyResponse(
                granted=False,
                message="인증 실패: 미등록 기기"
            ).model_dump(),
            headers={"Content-Type": "application/json; charset=utf-8"}
        )


    # BLE address is only a lookup locator.  A caller must prove possession of
    # the separately provisioned credential; an omitted/forged device ID never
    # authorizes an arm command.
    if not req.auth_key or not tenant.get("auth_key") or not secrets.compare_digest(
        req.auth_key, tenant["auth_key"]
    ):
        log.warning("[AUTH] credential proof rejected")
        _log_access(mac_upper, False, req.distance_mm, "credential proof rejected", tenant["id"])
        return JSONResponse(
            status_code=403,
            content=AuthVerifyResponse(granted=False, message="credential proof rejected").model_dump(),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

    if not tenant["is_active"]:
        log.warning("[AUTH] inactive credential rejected")
        _log_access(mac_upper, False, req.distance_mm, "비활성화 계정", tenant["id"])
        return JSONResponse(
            content=AuthVerifyResponse(
                granted=False,
                tenant_name=tenant["name"],
                message="인증 실패: 출입 권한이 비활성화된 세입자"
            ).model_dump(),
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

    log.info("[AUTH] credential verification succeeded")
    _log_access(mac_upper, True, req.distance_mm, None, tenant["id"])
    arm_ok = publish_arm_to_mqtt(tenant["name"], tenant["id"])

    return JSONResponse(
        content=AuthVerifyResponse(
            granted=True,
            tenant_name=tenant["name"],
            unit_number=tenant["unit_number"],
            message=f"인증 성공: {tenant['name']} ({tenant['unit_number']}) 출입 허가. Pre-arm 발행됨.",
            arm_published=arm_ok
        ).model_dump(),
        headers={"Content-Type": "application/json; charset=utf-8"}
    )

@app.get("/api/v1/logs", response_model=List[AccessLogItem])
def get_access_logs(
    request: Request,
    x_tenant_id: str = Header(..., alias=TENANT_HEADER),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    if not x_tenant_id.startswith("legacy:") or not x_tenant_id[7:].isdigit():
        raise HTTPException(status_code=400, detail="legacy tenant scope required")
    tenant_id = int(x_tenant_id[7:])
    _admin_principal(request, roles=(ROLE_ADMIN, ROLE_AUDITOR), tenant_scope=x_tenant_id)
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, auth_method, is_success, distance_mm, "
                "failure_reason, created_at "
                "FROM access_logs WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (tenant_id, limit, offset)
            )
            rows = cur.fetchall()
            for row in rows:
                if isinstance(row.get("created_at"), datetime):
                    row["created_at"] = row["created_at"].isoformat()
        return JSONResponse(
            content=rows,
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
    except Exception as e:
        log.error("[DB] access-event query unavailable")
        raise HTTPException(status_code=503, detail="access-event query unavailable")
    finally:
        if conn:
            conn.close()


@app.get("/api/v1/admin/access-events")
def get_all_access_events_admin(
    request: Request,
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    _admin_principal(request, roles=(ROLE_ADMIN, ROLE_AUDITOR), tenant_scope="*")
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT l.id, l.tenant_id, t.name AS tenant_name, "
                "t.unit_number, l.auth_method, l.is_success, l.distance_mm, "
                "l.failure_reason, l.created_at "
                "FROM access_logs l LEFT JOIN tenants t ON t.id=l.tenant_id "
                "ORDER BY l.created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            rows = cur.fetchall()
            for row in rows:
                if isinstance(row.get("created_at"), datetime):
                    row["created_at"] = row["created_at"].isoformat()
            cur.execute(
                "SELECT COUNT(*) AS total FROM access_logs "
                "WHERE created_at >= CURRENT_DATE() AND created_at < CURRENT_DATE() + INTERVAL 1 DAY"
            )
            count = cur.fetchone()
        return {
            "events": rows,
            "today_total": int((count or {}).get("total", 0)),
        }
    except Exception as exc:
        log.error("[ADMIN-DB] global access-event query unavailable")
        raise HTTPException(status_code=503, detail="global access-event query unavailable") from exc
    finally:
        if conn:
            conn.close()


@app.get("/api/v1/admin/privacy/support-export")
def create_support_export(
    request: Request,
    x_tenant_id: str = Header(..., alias=TENANT_HEADER),
    x_support_consent: str = Header(..., alias="X-Support-Consent"),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(200, ge=1, le=500),
):
    """Create one consent-bound, redacted and audited diagnostic export."""
    if not x_tenant_id.startswith("legacy:") or not x_tenant_id[7:].isdigit():
        raise HTTPException(status_code=400, detail="legacy tenant scope required")
    if not re.fullmatch(r"consent_[a-f0-9]{32}", x_support_consent):
        raise HTTPException(status_code=400, detail="opaque support consent reference required")
    principal = _admin_principal(
        request, roles=(ROLE_ADMIN, ROLE_AUDITOR), tenant_scope=x_tenant_id,
    )
    tenant_id = int(x_tenant_id[7:])
    consent_hash = hashlib.sha256(x_support_consent.encode("utf-8")).hexdigest()
    consent_ref = opaque_ref(x_support_consent, _ops_hmac_key, "consent")
    conn = None
    try:
        conn = get_db()
        conn.begin()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_scope,purpose,expires_at,revoked_at "
                "FROM support_export_consents WHERE consent_ref_hash=%s FOR UPDATE",
                (consent_hash,),
            )
            consent = cur.fetchone()
            now = int(time.time())
            if (
                not consent
                or consent["tenant_scope"] != x_tenant_id
                or consent["purpose"] != "support-diagnostics"
                or int(consent["expires_at"]) <= now
                or consent["revoked_at"] is not None
            ):
                raise HTTPException(
                    status_code=403,
                    detail="current tenant-scoped support consent is required",
                )
            cur.execute(
                "SELECT auth_method,is_success,distance_mm,failure_reason,created_at "
                "FROM access_logs WHERE tenant_id=%s AND created_at >= "
                "DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s HOUR) "
                "ORDER BY created_at DESC LIMIT %s",
                (tenant_id, hours, limit),
            )
            records = cur.fetchall()
        for record in records:
            if isinstance(record.get("created_at"), datetime):
                record["created_at"] = record["created_at"].isoformat()
        exported = support_export(
            records,
            consent_ref,
            opaque_ref(x_tenant_id, _ops_hmac_key, "tenant"),
            max_records=500,
        )
        _audit_admin(
            conn, principal, x_tenant_id, "SUPPORT_EXPORT_CREATED",
            exported["sha256"], consent_ref,
        )
        conn.commit()
        return exported
    except ValueError as exc:
        if conn:
            conn.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as exc:
        if conn:
            conn.rollback()
        log.error("[PRIVACY] support export unavailable")
        raise HTTPException(status_code=503, detail="support export unavailable") from exc
    finally:
        if conn:
            conn.close()


@app.post("/api/v1/admin/privacy/delete")
def delete_expired_privacy_data(
    req: PrivacyDeletionRequest,
    request: Request,
    x_tenant_id: str = Header(..., alias=TENANT_HEADER),
    idempotency_key: str = Header(..., alias=IDEMPOTENCY_HEADER),
):
    """Delete only tenant-scoped access records under the versioned policy."""
    if not x_tenant_id.startswith("legacy:") or not x_tenant_id[7:].isdigit():
        raise HTTPException(status_code=400, detail="legacy tenant scope required")
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="bounded Idempotency-Key required")
    principal = _admin_principal(
        request, unsafe=True, roles=(ROLE_ADMIN,), tenant_scope=x_tenant_id,
        reauthenticate=True,
    )
    tenant_id = int(x_tenant_id[7:])
    idempotency_hash = hashlib.sha256(idempotency_key.encode()).hexdigest()
    canonical_request = json.dumps(
        {
            "actor_subject": principal.subject,
            "before_days": req.before_days,
            "policy_version": req.policy_version,
            "tenant_scope": x_tenant_id,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    request_hash = hashlib.sha256(canonical_request).hexdigest()
    conn = None
    try:
        conn = get_db()
        conn.begin()
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO privacy_deletion_jobs "
                    "(tenant_scope,actor_subject,policy_version,before_days,idempotency_hash,"
                    "request_hash,state,created_at) VALUES (%s,%s,%s,%s,%s,%s,'PENDING',%s)",
                    (
                        x_tenant_id, principal.subject, req.policy_version,
                        req.before_days, idempotency_hash, request_hash, int(time.time()),
                    ),
                )
            except pymysql.err.IntegrityError as exc:
                if not exc.args or exc.args[0] != 1062:
                    raise
            cur.execute(
                "SELECT actor_subject,request_hash,state,deleted_count "
                "FROM privacy_deletion_jobs WHERE tenant_scope=%s "
                "AND idempotency_hash=%s FOR UPDATE",
                (x_tenant_id, idempotency_hash),
            )
            existing = cur.fetchone()
            if not existing:
                raise RuntimeError("privacy deletion reservation unavailable")
            if (
                not secrets.compare_digest(existing["request_hash"], request_hash)
                or not secrets.compare_digest(existing["actor_subject"], principal.subject)
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency-Key is already bound to a different request",
                )
            if existing["state"] == "COMPLETED":
                conn.commit()
                return {"status": "already_completed", "deleted_count": existing["deleted_count"]}
            cur.execute(
                "DELETE FROM access_logs WHERE tenant_id=%s AND created_at < "
                "DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)",
                (tenant_id, req.before_days),
            )
            deleted_count = cur.rowcount
            cur.execute(
                "UPDATE privacy_deletion_jobs SET state='COMPLETED',deleted_count=%s,"
                "completed_at=%s WHERE tenant_scope=%s AND idempotency_hash=%s "
                "AND state='PENDING' AND request_hash=%s",
                (
                    deleted_count, int(time.time()), x_tenant_id,
                    idempotency_hash, request_hash,
                ),
            )
            if cur.rowcount != 1:
                raise RuntimeError("privacy deletion completion transition failed")
        _audit_admin(
            conn, principal, x_tenant_id, "PRIVACY_RETENTION_APPLIED",
            req.policy_version, idempotency_key,
        )
        conn.commit()
        return {"status": "completed", "deleted_count": deleted_count}
    except HTTPException:
        if conn:
            conn.rollback()
        raise
    except Exception as exc:
        if conn:
            conn.rollback()
        log.error("[PRIVACY] retention deletion unavailable")
        raise HTTPException(status_code=503, detail="retention deletion unavailable") from exc
    finally:
        if conn:
            conn.close()

def _log_access(
    mac: str,
    success: bool,
    distance_mm: Optional[int],
    failure_reason: Optional[str],
    tenant_id: Optional[int] = None
):
    _write_access_event(
        tenant_id, "BLE_BEACON", success, distance_mm, failure_reason
    )


def _write_access_event(
    tenant_id: Optional[int],
    auth_method: str,
    success: bool,
    distance_mm: Optional[int],
    failure_reason: Optional[str],
):
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO access_logs "
                "(tenant_id, auth_method, is_success, distance_mm, failure_reason) "
                "VALUES (%s, %s, %s, %s, %s)",
                (tenant_id, auth_method, success, distance_mm, failure_reason)
            )
    except Exception as e:
        log.error("[DB] access-event persistence unavailable")
    finally:
        if conn:
            conn.close()
