# smart-gatekeeper 🚪🔍

**smart-gatekeeper**는 **ESP32-C6 기반의 BLE 5.0 RSSI 스캔**, **VL53L0X ToF 레이저 거리 센서**, 그리고 **시놀로지 NAS(Synology NAS) 백엔드**를 결합한 차세대 IoT 스마트 출입 통제 시스템입니다. 

세입자가 스마트폰을 주머니나 가방에서 꺼내지 않아도 공동 현관문 앞에 서면 자동으로 인식하여 문을 열어주는 안전하고 편리한 **'워크스루(Walk-through)'** 출입 경험을 제공합니다. 안드레 카파시(Andrej Karpathy)의 **LLM Wiki 구조**를 채택하여 AI 에이전트(Antigravity 등)와 지속적으로 지식을 축적하며 공동 개발할 수 있도록 설계되었습니다.

## 🛠️ 기술 스택 (Tech Stack)
- **하드웨어:** ESP32-C6-DevKitC (RISC-V 아키텍처, Type-C), VL53L0X ToF 센서, 1채널 5V 릴레이 모듈
- **네트워크:** Wi-Fi 6 (802.11ax), Bluetooth 5.0 (BLE)
- **펌웨어 환경:** PlatformIO (VS Code Extension)
- **백엔드 서버:** 시놀로지 NAS (Container Manager / Docker 기반 가벼운 API 서버)
- **데이터베이스:** MariaDB / PostgreSQL
- **보안/인프라:** 시놀로지 역방향 프록시(Reverse Proxy)를 통한 HTTPS 암호화, SHA-256 전화번호 비식별화 해싱, 엄격한 `X-API-KEY` 검증

## 📐 핵심 아키텍처 (Core Architecture)
1. **BLE 5.0 스캔 (Edge):** ESP32-C6가 주변의 블루투스 신호를 상시 스캔하여, 사전에 등록된 세입자의 암호화된 비콘 신호(전화번호 해시 기반 UUID/Major/Minor)와 RSSI(신호 세기) 임계값을 검증합니다.
2. **ToF 거리 측정 (Edge):** 신호가 확인되면 VL53L0X 레이저 센서가 활성화되어 문 앞 50cm 이내에 사람이 실제로 멈춰 섰는지 정밀하게 측정합니다. 단순 통과자로 인한 오작동을 원천 차단합니다.
3. **중앙 자격 검증 (Cloud/NAS):** 두 조건이 충족되면 ESP32-C6가 외부 인터넷망을 거쳐 집 안의 시놀로지 나스 API 서버로 보안 요청을 보냅니다. 서버는 데이터베이스(DB)를 조회하여 실시간으로 승인된 세입자인지 판단합니다.
4. **접점 제어 (Door):** 검증 완료 응답을 받으면 1채널 5V 릴레이가 구동되어 기존 자동문 컨트롤러의 개방 접점을 안전하게 쇼트(무전압 제어)시킵니다.

## 📌 하드웨어 핀 맵 (ESP32-C6 DevKitC 기준)
> ⚠️ **주의:** 클래식 ESP32 보드와 달리, ESP32-C6는 기본 I2C 핀 배열이 다릅니다. 배선 시 반드시 하단을 준수하세요.
- **VL53L0X ToF 거리 센서:**
  - SDA ➡️ GPIO 6
  - SCL ➡️ GPIO 7
- **1채널 5V 릴레이 모듈:**
  - Signal ➡️ GPIO 3 (설정에서 변경 가능)

## 📁 저장소 구조 (Repository Structure)

- schema.md 파일 참조 할 것 

```text
smart-gatekeeper/
├── .agents/
│   └── AGENTS.md          # IDE 자동 로드 핵심 규칙 (압축본)
├── raw/                   # 읽기 전용 참조 문서 (데이터시트, 사양서 등)
│   ├── ST_VL53L0X_Specs.md
│   ├── Espressif_ESP32C6_BoardSpec.md
│   └── BOM_SmartGatekeeper_Step1.md
├── wiki/                  # AI 에이전트가 관리하는 지식 저장소 (마크다운 전용)
│   ├── index.md           # 내비게이션 맵 — 에이전트 진입 시 필독
│   ├── log.md             # 연대기별 작업 및 변경 로그
│   ├── env_setup.md       # 개발 환경 및 툴체인 가이드
│   ├── pin_mapping.md     # 하드웨어 핀 할당 기록
│   ├── hardware_test.md   # 테스트 절차 및 결과 기록
│   └── architecture.md    # 시스템 오버뷰 및 향후 로드맵
├── src/                   # PlatformIO 소스 코드 (.cpp)
├── include/               # 헤더 파일 (.h)
├── platformio.ini         # PlatformIO 프로젝트 설정 파일
├── AGENTS.md              # 에이전트 협업 전체 지침 (각 에이전트 작업 시 필독)
├── schema.md              # 위키 거버넌스 및 유지보수 규칙
└── README.md              # 프로젝트 메인 안내서