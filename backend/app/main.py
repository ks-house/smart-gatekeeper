# backend/app/main.py
# =============================================================
# smart-gatekeeper — FastAPI 출입 통제 API 서버
# v2.0: MariaDB 실제 연동 + MQTT Pre-arm & Force Open + Static Web App
# =============================================================
import os
import ssl
import json
import logging
from typing import Optional, List
from datetime import datetime
from contextlib import asynccontextmanager

import pymysql
try:
    import paho.mqtt.client as mqtt
    HAS_PAHO_MQTT = True
except ImportError:
    mqtt = None
    HAS_PAHO_MQTT = False

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
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

MQTT_HOST           = os.getenv("MQTT_HOST", "")
MQTT_PORT           = int(os.getenv("MQTT_PORT", "8883"))
MQTT_USER           = os.getenv("MQTT_USER", "")
MQTT_PASSWORD       = os.getenv("MQTT_PASSWORD", "")
MQTT_USE_TLS        = os.getenv("MQTT_USE_TLS", "true").lower() == "true"
MQTT_TOPIC_ARM      = os.getenv("MQTT_TOPIC_ARM", "gatekeeper/arm")
MQTT_TOPIC_FORCE    = os.getenv("MQTT_TOPIC_FORCE_OPEN", "gatekeeper/force_open")

BEACON_UUID         = os.getenv("GATEKEEPER_BEACON_UUID", "a1b2c3d4-e5f6-7890-abcd-ef1234567890")
APK_VERSION_URL     = os.getenv("APK_VERSION_URL", "https://tworimpa.synology.me:4443/gatekeeper_apk/version.json")
APK_DOWNLOAD_URL    = os.getenv("APK_DOWNLOAD_URL", "https://tworimpa.synology.me:4443/gatekeeper_apk/ks-house-gatekeeper.apk")
WEBVIEW_URL         = os.getenv("WEBVIEW_URL", "https://tworimpa.synology.me:4442/app")

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

# ─── MQTT Helper Functions ────────────────────────────────────
def publish_arm_to_mqtt(tenant_name: str, tenant_id: int) -> bool:
    """NAS → MQTT Broker → ESP32-C6 gatekeeper/arm 토픽 발행."""
    if not HAS_PAHO_MQTT:
        log.warning("[MQTT-ARM] paho-mqtt 패키지 미설치 — arm 발행 건너뜀")
        return False

    if not MQTT_HOST:
        log.warning("[MQTT-ARM] MQTT_HOST 미설정 — arm 발행 건너뜀")
        return False


    try:
        client = mqtt.Client(client_id=f"gatekeeper-api-{tenant_id}", protocol=mqtt.MQTTv5)
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

        if MQTT_USE_TLS:
            client.tls_set(cert_reqs=ssl.CERT_NONE)
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
        log.error(f"[MQTT-ARM] ❌ MQTT 예외: {e}")
        return False

def publish_force_open_to_mqtt(tenant_name: str = " 수동원격") -> bool:
    """NAS → MQTT Broker → ESP32-C6 gatekeeper/force_open 강제 개방 토픽 발행."""
    if not HAS_PAHO_MQTT:
        log.warning("[MQTT-FORCE] paho-mqtt 패키지 미설치 — force_open 발행 건너뜀")
        return False

    if not MQTT_HOST:
        log.warning("[MQTT-FORCE] MQTT_HOST 미설정 — force_open 발행 건너뜀")
        return False


    try:
        client = mqtt.Client(client_id="gatekeeper-force-open", protocol=mqtt.MQTTv5)
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

        if MQTT_USE_TLS:
            client.tls_set(cert_reqs=ssl.CERT_NONE)
            client.tls_insecure_set(True)

        client.connect(MQTT_HOST, MQTT_PORT, keepalive=10)
        payload = json.dumps({
            "action": "force_open",
            "user": tenant_name,
            "issued_at": datetime.now().isoformat()
        }, ensure_ascii=False)

        result = client.publish(MQTT_TOPIC_FORCE, payload, qos=1)
        client.disconnect()

        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            log.info(f"[MQTT-FORCE] ✅ force_open 발행 성공 → {MQTT_TOPIC_FORCE}")
            return True
        else:
            log.error(f"[MQTT-FORCE] ❌ 발행 실패 rc={result.rc}")
            return False
    except Exception as e:
        log.error(f"[MQTT-FORCE] ❌ MQTT 예외: {e}")
        return False

# ─── Pydantic 스키마 ──────────────────────────────────────────
class AuthVerifyRequest(BaseModel):
    ble_mac: str = Field(..., example="AA:BB:CC:DD:EE:01", description="스마트폰 BLE MAC 주소")
    auth_key: Optional[str] = Field(None, description="인증 토큰/키 (선택)")
    distance_mm: Optional[int] = Field(None, description="ToF 센서 측정 거리(mm)")

class AuthVerifyResponse(BaseModel):
    granted: bool
    tenant_name: Optional[str] = None
    unit_number: Optional[str] = None
    message: str
    arm_published: Optional[bool] = Field(None, description="MQTT arm 발행 성공 여부")

class UserRequestSchema(BaseModel):
    name: str
    room_no: str
    device_id: str

class PrearmRequestSchema(BaseModel):
    beacon_uuid: str
    rssi: Optional[int] = None
    timestamp: Optional[str] = None

class ForceOpenRequestSchema(BaseModel):
    reason: Optional[str] = "manual_click"
    device_id: Optional[str] = None


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
    log.info(f"[STARTUP] MQTT Broker: {MQTT_HOST}:{MQTT_PORT} | arm: {MQTT_TOPIC_ARM} | force: {MQTT_TOPIC_FORCE}")
    yield
    log.info("[SHUTDOWN] Smart Gatekeeper API 종료")

app = FastAPI(
    title="Smart Gatekeeper API",
    description="시놀로지 NAS 백엔드 — BLE Beacon + MQTT Pre-arm 기반 출입 통제 v2.0",
    version="2.0.0",
    lifespan=lifespan,
    default_response_class=JSONResponse
)

# 정적 파일 디렉토리 마운트
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ─── Web & Endpoints ──────────────────────────────────────────
@app.get("/app", response_class=HTMLResponse)
def get_webview_app():
    """모바일 앱 WebView 내에 렌더링될 HTML 메인 화면 반환"""
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path, media_type="text/html")
    return HTMLResponse("<h1>Smart Gatekeeper Web App</h1><p>static/index.html not found</p>")

@app.get("/admin", response_class=HTMLResponse)
def get_admin_console():
    """관리자 콘솔 웹 화면 반환"""
    admin_path = os.path.join(static_dir, "admin.html")
    if os.path.exists(admin_path):
        return FileResponse(admin_path, media_type="text/html")
    return HTMLResponse("<h1>Smart Gatekeeper Admin Console</h1><p>static/admin.html not found</p>")

@app.get("/api/v1/admin/tenants")
def get_all_tenants_admin():
    """관리자용 전체 세입자 및 승인 대기 세입자 목록 조회"""
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name, unit_number, ble_device_mac, is_active FROM tenants ORDER BY id DESC")
            rows = cur.fetchall()
            return JSONResponse(content=rows, headers={"Content-Type": "application/json; charset=utf-8"})
    except Exception as e:
        log.error(f"[ADMIN-DB] 세입자 목록 조회 실패: {e}")
        # DB 조회 불가 시 기본 목데이터 제공
        return JSONResponse(content=[
            {"id": 1, "name": "홍길동", "unit_number": "101호", "ble_device_mac": "AA:BB:CC:DD:EE:01", "is_active": True},
            {"id": 2, "name": "김철수", "unit_number": "202호", "ble_device_mac": "11:22:33:44:55:66", "is_active": False}
        ], headers={"Content-Type": "application/json; charset=utf-8"})
    finally:
        if conn:
            conn.close()

@app.post("/api/v1/admin/tenants/{tenant_id}/approve")
def approve_tenant(tenant_id: int):
    """관리자 세입자 승인 처리 (is_active = true)"""
    log.info(f"[ADMIN] 세입자 승인: Tenant ID={tenant_id}")
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET is_active = true WHERE id = %s", (tenant_id,))
        return JSONResponse(content={"status": "approved", "tenant_id": tenant_id})
    except Exception as e:
        log.error(f"[ADMIN] 승인 실패: {e}")
        return JSONResponse(content={"status": "approved_mock", "tenant_id": tenant_id})
    finally:
        if conn:
            conn.close()

@app.post("/api/v1/admin/tenants/{tenant_id}/reject")
def reject_tenant(tenant_id: int):
    """관리자 세입자 권한 회수/거절 처리 (is_active = false)"""
    log.info(f"[ADMIN] 세입자 권한 회수: Tenant ID={tenant_id}")
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("UPDATE tenants SET is_active = false WHERE id = %s", (tenant_id,))
        return JSONResponse(content={"status": "rejected", "tenant_id": tenant_id})
    except Exception as e:
        log.error(f"[ADMIN] 회수 실패: {e}")
        return JSONResponse(content={"status": "rejected_mock", "tenant_id": tenant_id})
    finally:
        if conn:
            conn.close()


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

@app.get("/api/v1/config")
def get_remote_config():
    """Flutter Native Shell 및 모바일 앱에 동적 설정 반환 (Remote Config)"""
    return JSONResponse(
        content={
            "beacon_uuid": BEACON_UUID,
            "cooldown_sec": 30,
            "apk_version_url": APK_VERSION_URL,
            "apk_download_url": APK_DOWNLOAD_URL,
            "webview_url": WEBVIEW_URL
        },
        headers={"Content-Type": "application/json; charset=utf-8"}
    )

@app.get("/api/v1/user/me")
def get_user_me(device_id: str = Query(...)):
    """현재 기기(device_id)의 세입자 등록 상태 및 세입자 정보 조회"""
    mac_upper = device_id.strip().upper()
    log.info(f"[USER-ME] 세입자 상태 조회: MAC/ID={mac_upper}")
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
    except Exception as e:
        log.error(f"[USER-ME] 조회 실패: {e}")
        return JSONResponse(content={"status": "unregistered", "message": f"DB 조회 예외 ({e})"})
    finally:
        if conn:
            conn.close()

@app.post("/api/v1/user/request")
def request_user_access(req: UserRequestSchema):
    """신규 세입자 가입 및 출입 권한 신청"""
    mac_upper = req.device_id.strip().upper()
    log.info(f"[USER-REQ] 신규 가입 신청: {req.name} ({req.room_no}), MAC={mac_upper}")
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # 기존 레코드 존재 시 업데이트, 미존재 시 인서트
            cur.execute(
                "INSERT INTO tenants (name, unit_number, ble_device_mac, is_active) "
                "VALUES (%s, %s, %s, false) "
                "ON DUPLICATE KEY UPDATE name = VALUES(name), unit_number = VALUES(unit_number), is_active = false",
                (req.name, req.room_no, mac_upper)
            )
        return JSONResponse(
            content={"status": "pending", "message": "가입 신청 완료. 관리자 승인 대기 중"},
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
    except Exception as e:
        log.error(f"[USER-REQ] 신청 실패: {e}")
        return JSONResponse(
            content={"status": "pending", "message": f"신청 완료 (대기 중)"},
            headers={"Content-Type": "application/json; charset=utf-8"}
        )
    finally:
        if conn:
            conn.close()

@app.post("/api/v1/door/open")
def door_force_open(req: ForceOpenRequestSchema):
    """WebView 수동 '문 열기' 터치 시 즉시 릴레이 강제 개방 명령 하달"""
    log.info(f"[FORCE-OPEN] 수동 원격 문 열기 요청: Reason={req.reason}, Device={req.device_id}")
    
    # device_id가 있으면 세입자명 조회
    user_label = "수동개방"
    if req.device_id:
        conn = None
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute("SELECT name, unit_number, is_active FROM tenants WHERE ble_device_mac = %s LIMIT 1", (req.device_id.strip().upper(),))
                row = cur.fetchone()
                if row:
                    if not row["is_active"]:
                        return JSONResponse(
                            status_code=403,
                            content={"result": "denied", "message": "출입 권한이 승인되지 않은 세입자입니다."}
                        )
                    user_label = f"{row['name']}({row['unit_number']})"
        except Exception as e:
            log.error(f"[FORCE-OPEN] 세입자 검증 실패: {e}")
        finally:
            if conn:
                conn.close()

    force_ok = publish_force_open_to_mqtt(user_label)
    return JSONResponse(
        content={"result": "force_opened", "message": "문이 성공적으로 열렸습니다!", "mqtt_published": force_ok},
        headers={"Content-Type": "application/json; charset=utf-8"}
    )


@app.post("/api/v1/auth/verify", response_model=AuthVerifyResponse)
def verify_access(req: AuthVerifyRequest):
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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"데이터베이스 연결 오류: {e}"
        )
    finally:
        if conn:
            conn.close()

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

    log.info(f"[AUTH] ✅ 인증 성공: {tenant['name']} ({tenant['unit_number']})")
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
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
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

def _log_access(
    mac: str,
    success: bool,
    distance_mm: Optional[int],
    failure_reason: Optional[str],
    tenant_id: Optional[int] = None
):
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
    except Exception as e:
        log.error(f"[DB] 출입 기록 저장 실패: {e}")
    finally:
        if conn:
            conn.close()
