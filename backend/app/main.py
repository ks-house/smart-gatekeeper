# backend/app/main.py
# =============================================================
# smart-gatekeeper — FastAPI 출입 통제 API 서버
# v2.0: MariaDB 실제 연동 + MQTT gatekeeper/arm Pre-arm 발행
# =============================================================
import os
import ssl
import json
import logging
from typing import Optional, List
from datetime import datetime
from contextlib import asynccontextmanager

import pymysql
import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ─── 로거 설정 ────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─── 환경변수 (docker-compose에서 주입) ──────────────────────
DB_HOST     = os.getenv("DB_HOST", "db")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_NAME     = os.getenv("DB_NAME", "smart_gatekeeper")
DB_USER     = os.getenv("DB_USER", "gatekeeper_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "gatekeeper_pass")

MQTT_HOST     = os.getenv("MQTT_HOST", "")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USER     = os.getenv("MQTT_USER", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_USE_TLS  = os.getenv("MQTT_USE_TLS", "true").lower() == "true"
MQTT_TOPIC_ARM = os.getenv("MQTT_TOPIC_ARM", "gatekeeper/arm")  # ESP32가 구독 중인 토픽

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

# ─── MQTT Pre-arm 발행 ────────────────────────────────────────
def publish_arm_to_mqtt(tenant_name: str, tenant_id: int) -> bool:
    """
    NAS → MQTT Broker → ESP32-C6 gatekeeper/arm 토픽 발행.
    인증 성공 시 호출하여 ESP32를 ARMED 상태로 전환시킨다.
    """
    if not MQTT_HOST:
        log.warning("[MQTT-ARM] MQTT_HOST 미설정 — arm 발행 건너뜀 (개발 환경)")
        return False

    try:
        client = mqtt.Client(client_id=f"gatekeeper-api-{tenant_id}", protocol=mqtt.MQTTv5)
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

        if MQTT_USE_TLS:
            # MQTTS (TLS) — 시놀로지 NAS 브로커 연결
            client.tls_set(cert_reqs=ssl.CERT_NONE)  # NAS 자체 서명 인증서 허용
            client.tls_insecure_set(True)

        client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)

        payload = json.dumps({
            "action": "arm",
            "user": tenant_name,
            "tenant_id": tenant_id,
            "issued_at": datetime.now().isoformat()
        }, ensure_ascii=False)

        result = client.publish(MQTT_TOPIC_ARM, payload, qos=1)
        client.disconnect()

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            log.info(f"[MQTT-ARM] ✅ arm 발행 성공 → {MQTT_TOPIC_ARM} | 사용자: {tenant_name}")
            return True
        else:
            log.error(f"[MQTT-ARM] ❌ 발행 실패 rc={result.rc}")
            return False

    except Exception as e:
        log.error(f"[MQTT-ARM] ❌ MQTT 연결/발행 예외: {e}")
        return False

# ─── Pydantic 스키마 ──────────────────────────────────────────
class AuthVerifyRequest(BaseModel):
    ble_mac: str = Field(..., example="AA:BB:CC:DD:EE:01", description="스마트폰 BLE MAC 주소")
    auth_key: Optional[str] = Field(None, description="인증 토큰/키 (선택)")
    distance_mm: Optional[int] = Field(None, description="ToF 센서 측정 거리(mm) — v2.0에서 선택 사항")

class AuthVerifyResponse(BaseModel):
    granted: bool
    tenant_name: Optional[str] = None
    unit_number: Optional[str] = None
    message: str
    arm_published: Optional[bool] = Field(None, description="MQTT arm 발행 성공 여부")

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
    log.info(f"[STARTUP] Smart Gatekeeper API v2.0 시작")
    log.info(f"[STARTUP] DB: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    log.info(f"[STARTUP] MQTT Broker: {MQTT_HOST}:{MQTT_PORT} | arm 토픽: {MQTT_TOPIC_ARM}")
    yield
    log.info("[SHUTDOWN] Smart Gatekeeper API 종료")

app = FastAPI(
    title="Smart Gatekeeper API",
    description="시놀로지 NAS 백엔드 — BLE Beacon + MQTT Pre-arm 기반 출입 통제 v2.0",
    version="2.0.0",
    lifespan=lifespan,
    default_response_class=JSONResponse
)

# ─── Endpoints ────────────────────────────────────────────────
@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """서버 헬스 체크"""
    return JSONResponse(
        content={
            "status": "healthy",
            "service": "smart-gatekeeper-api",
            "version": "2.0.0",
            "timestamp": datetime.now().isoformat()
        },
        headers={"Content-Type": "application/json; charset=utf-8"}
    )

@app.post("/api/v1/auth/verify", response_model=AuthVerifyResponse)
def verify_access(req: AuthVerifyRequest):
    """
    스마트폰 앱으로부터 BLE MAC + auth_key 기반 출입 자격 검증.

    v2.0 흐름:
    1. 스마트폰이 ESP32-C6 비콘을 감지 → 이 API 호출
    2. MariaDB에서 등록된 세입자 조회
    3. 인증 성공 시 MQTT gatekeeper/arm 발행 → ESP32 ToF 활성화
    """
    mac_upper = req.ble_mac.strip().upper()
    log.info(f"[AUTH] 자격 검증 요청: MAC={mac_upper}")

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
    except Exception as e:
        log.error(f"[DB] 조회 실패: {e}")
        # DB 연결 실패 시 503 반환
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"데이터베이스 연결 오류: {e}"
        )
    finally:
        if conn:
            conn.close()

    # ── 미등록 MAC ──
    if not tenant:
        log.warning(f"[AUTH] ❌ 미등록 MAC: {mac_upper}")
        _log_access(mac_upper, False, req.distance_mm, "미등록 기기")
        return JSONResponse(
            content=AuthVerifyResponse(
                granted=False,
                message="인증 실패: 미등록 기기"
            ).model_dump(),
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

    # ── 비활성화된 세입자 ──
    if not tenant["is_active"]:
        log.warning(f"[AUTH] ❌ 비활성화 세입자: {tenant['name']}")
        _log_access(mac_upper, False, req.distance_mm, "비활성화 계정", tenant["id"])
        return JSONResponse(
            content=AuthVerifyResponse(
                granted=False,
                tenant_name=tenant["name"],
                message="인증 실패: 출입 권한이 비활성화된 세입자"
            ).model_dump(),
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

    # ── auth_key 검증 (선택 사항 — 요청에 포함된 경우만 체크) ──
    if req.auth_key and tenant["auth_key"] and req.auth_key != tenant["auth_key"]:
        log.warning(f"[AUTH] ❌ auth_key 불일치: {tenant['name']}")
        _log_access(mac_upper, False, req.distance_mm, "auth_key 불일치", tenant["id"])
        return JSONResponse(
            content=AuthVerifyResponse(
                granted=False,
                tenant_name=tenant["name"],
                message="인증 실패: 자격 키 불일치"
            ).model_dump(),
            headers={"Content-Type": "application/json; charset=utf-8"}
        )

    # ── 인증 성공 ──
    log.info(f"[AUTH] ✅ 인증 성공: {tenant['name']} ({tenant['unit_number']})")
    _log_access(mac_upper, True, req.distance_mm, None, tenant["id"])

    # v2.0 핵심: MQTT gatekeeper/arm 발행 → ESP32-C6 ARMED 상태 전환
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
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """출입 기록 최근 로그 조회"""
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, tenant_id, auth_method, is_success, distance_mm, "
                "failure_reason, created_at "
                "FROM access_logs ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset)
            )
            rows = cur.fetchall()
            # datetime → isoformat 직렬화
            for row in rows:
                if isinstance(row.get("created_at"), datetime):
                    row["created_at"] = row["created_at"].isoformat()
        return JSONResponse(
            content=rows,
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
    except Exception as e:
        log.error(f"[DB] 로그 조회 실패: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    finally:
        if conn:
            conn.close()


# ─── 내부 헬퍼: 출입 기록 저장 ───────────────────────────────
def _log_access(
    mac: str,
    success: bool,
    distance_mm: Optional[int],
    failure_reason: Optional[str],
    tenant_id: Optional[int] = None
):
    """access_logs 테이블에 출입 시도 기록 저장."""
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO access_logs "
                "(tenant_id, auth_method, is_success, distance_mm, failure_reason) "
                "VALUES (%s, %s, %s, %s, %s)",
                (tenant_id, "BLE_BEACON", success, distance_mm, failure_reason)
            )
        log.info(f"[DB] 출입 기록 저장: success={success}, tenant_id={tenant_id}")
    except Exception as e:
        log.error(f"[DB] 출입 기록 저장 실패: {e}")
    finally:
        if conn:
            conn.close()
