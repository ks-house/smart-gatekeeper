# backend/app/main.py
# =============================================================
# smart-gatekeeper — FastAPI 기반 출입 통제 API 서버 (Step 2)
# =============================================================
import os
from typing import Optional, List
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, Query, status
from pydantic import BaseModel, Field

app = FastAPI(
    title="Smart Gatekeeper API",
    description="시놀로지 NAS 백엔드 연동형 스마트폰 BLE + ToF 출입 통제 API",
    version="0.1.0"
)

# ─────────────────────────────────────────────────────────────
# Pydantic Schemas (요청 / 응답 데이터 모델)
# ─────────────────────────────────────────────────────────────
class AuthVerifyRequest(BaseModel):
    ble_mac: str = Field(..., example="AA:BB:CC:DD:EE:01", description="스마트폰/태그 BLE MAC 주소")
    auth_key: Optional[str] = Field(None, example="secret_key_101", description="인증 토큰/키")
    distance_mm: Optional[int] = Field(None, example=350, description="ToF 센서 측정 거리(mm)")

class AuthVerifyResponse(BaseModel):
    granted: bool = Field(..., description="출입 허가 여부 (True: 문 열림, False: 거부)")
    tenant_name: Optional[str] = Field(None, example="홍길동")
    unit_number: Optional[str] = Field(None, example="101호")
    message: str = Field(..., example="출입 자격 확인 완료")

class AccessLogItem(BaseModel):
    id: int
    tenant_id: Optional[int]
    auth_method: str
    is_success: bool
    distance_mm: Optional[int]
    failure_reason: Optional[str]
    created_at: datetime

# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────
@app.get("/health", status_code=status.HTTP_200_OK)
def health_check():
    """서버 헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "service": "smart-gatekeeper-api",
        "timestamp": datetime.now().isoformat()
    }

@app.post("/api/v1/auth/verify", response_model=AuthVerifyResponse)
def verify_access(req: AuthVerifyRequest):
    """
    스마트폰/ESP32 gateway로부터 넘어온 BLE/ToF 정보 기반 출입 자격 검증 API (뼈대 구현)
    """
    # TODO: DB 연동 (MySQL / MariaDB 연결하여 세입자 조회)
    # 현재는 PoC 뼈대로 더미 로직 제공
    
    # 예시: 특정 MAC 주소 허용
    if req.ble_mac.upper() in ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]:
        return AuthVerifyResponse(
            granted=True,
            tenant_name="홍길동" if "01" in req.ble_mac else "김철수",
            unit_number="101호" if "01" in req.ble_mac else "102호",
            message="출입 허가: 자격 검증 성공"
        )
    
    return AuthVerifyResponse(
        granted=False,
        tenant_name=None,
        unit_number=None,
        message="출입 거부: 등록되지 않은 디바이스 또는 자격 미달"
    )

@app.get("/api/v1/logs", response_model=List[AccessLogItem])
def get_access_logs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """
    출입 기록 최근 로그 조회 API (뼈대 구현)
    """
    # 더미 로그 반환 (추후 DB 연결 예정)
    dummy_logs = [
        AccessLogItem(
            id=1,
            tenant_id=1,
            auth_method="BLE",
            is_success=True,
            distance_mm=320,
            failure_reason=None,
            created_at=datetime.now()
        )
    ]
    return dummy_logs
