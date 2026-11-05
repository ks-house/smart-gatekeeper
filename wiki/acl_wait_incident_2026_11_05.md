# 2026-11-05 출입 권한 동기화 대기·출입 미동작 분석

> 현재 결과: Target이 같은 boot912에서 통신에 복귀했고 ACL9846 APPLIED가 확인됐다. 사용자가 새로고침 후 스마트키 사용 가능 표시를 직접 확인했다. 실제 문 개방·장시간 재발 방지 완료는 아직 확인하지 않았다.
> 조사 범위: 기존 read API, 공개 TLS/MQTT CONNECT 확인, 기존 인증된 NAS/Grafana 화면, Backend 컨테이너의 읽기 전용 SQL. 기기 개방·재부팅·OTA·서비스/권한 설정 변경 없음.

## 1. 핵심 판단

이번 직접 차단 지점은 휴대폰이 읽은 광고의 ready hint=false와 이에 따른 TARGET_NOT_READY다. APK46901은 화면 OFF에서도 정확한 BLE 신호를 받았지만 이 상태를 보고 GATT 인증 작업을 예약하지 않았다. 서버와 Target 사이의 상태 보고 및 새 ACL 적용 확인에는 긴 공백이 있었다.

서버가 발행한 최신 권한 번호와 Target이 적용한 권한 번호는 다르다. 화면의 ACL9843은 최신 발행 번호이며 적용 완료 증거가 아니다. 마지막 확인된 APPLIED9840은20:28:30에 만료되는900초 권한이었다. 후속9841~9845의 적용 ACK가 없었고, 복귀 후9846 APPLIED가 저장되면서 현재 동기화 대기가 해소됐다.

장애 뒤 관측된 MQTT 연결 진단에는 DNS_FAILED4건, 연결 시도141회 증가/실패140회 증가, Wi-Fi generation2→3과 outage2→3이 있다. 이는 반복 연결 실패와 DNS 단계 문제의 증거다. 전체 실패140건이 모두 DNS였다는 기록은 없으며, 최초 원인이나 복귀를 촉발한 정확한 계기는 아직 확정하지 못했다.

## 2. 타임라인 — 모두 KST

| 시각 | 확인한 사실 | 의미 |
|---|---|---|
|20:13:30|ACL9840 발행 및 Target APPLIED ACK|마지막 장애 전 적용 확인, 만료20:28:30|
|20:17:26.632|마지막 장애 전 signed health150656|당시 boot912/IDLE/relay OFF; 이후 당시 상태를 현재로 사용하지 않음|
|20:23:31|ACL9841 발행, 적용 ACK 없음|새 권한 전달·적용 확인이 진행되지 않음|
|20:28:30|적용 확인된9840의 만료 시각|새 유효 ACL이 없으면 Target 인증 준비 조건을 충족할 수 없음|
|20:38:45|9842 발행, 만료20:53:45|이전 만료 job을 대체하는 Backend 복구 흐름|
|20:46:03.803|screen OFF FIRST_MATCH|새 모바일의 BLE 수신 확인|
|20:46:03.834~29.418|DISPATCH_SKIPPED/TARGET_NOT_READY, ready=false|GATT enqueue·proof·ARMED로 진행하지 않음|
|20:46:44|MATCH_LOST/EXIT|도착/출발·실제 문 위치를 이 값만으로 확정하지 않음|
|20:53:59|9843 발행, 만료21:08:59|제보 화면의 권한 번호; APPLIED와 다름|
|약20:57|제보 화면: 출입 권한 동기화 대기, ACL9843|최신 snapshot의 정확한 적용 ACK가 없어 대기|
|21:00:01.032→01.334|신선한 휴대폰 capture→서버 receipt|휴대폰 보고는 계속 도착하나 Target 상태는 오래됨|
|21:39:40|9846 발행, 만료21:54:40|기존 자동 권한 작업이 발행한 snapshot|
|21:40:04.433|첫 복귀 signed health|같은 boot ID/912, 재부팅 증거 없음|
|21:40:16|ACK9528, ACL9846 APPLIED·SHA 일치|최신 권한 적용 확인, 후속 읽기에서 pending job 없음|
|이후 사용자 확인|새로고침 후 스마트키 사용 가능|Home의 대기 표시 해소를 사용자 직접 확인|
|21:55:01.097→01.567|phone report에 ACL9846/synced=true/access_ready=true|보고 identity 캐시일 수 있어 다음 버전 ACK로 해석하지 않음|
|21:57:13.750|최신 health, boot912/552/IDLE/relay OFF, fresh|복귀 이후 연결 유지; BLE ready/applied=true|

마지막 장애 전 저장 시각과 첫 복귀 저장 시각 사이는 약82분38초다. 이는 상태 보고 관측 공백이며, 정확히 같은 길이의 물리 네트워크 단절을 계측했다는 뜻은 아니다.

## 3. 왜 문이 열리지 않았나

자동 출입 흐름은 BLE 수신 → fresh/ready 검사 → native worker → GATT proof → Target ACL 검증·ARMED → 센서 → 릴레이다.

이번20:46에는 첫 수신이 성공했지만 ready=false여서 worker가 예약되지 않았다. 저녁 조회창에 새 모바일 인증 session과 Target access event가 없었다. 센서/릴레이까지 내려간 실패로 분류할 근거는 없다. 과거 성공 알림이나 오전07:34 ARMED 성공을 이번 회차 성공으로 보지 않는다.

Target은 유효한 로컬 ACL이 있어야 인증을 허용한다. 기본 lease는900초(15분)다. 서버와 통신이 안 되어 새 권한을 받지 못하는 동안 이미 확인된 권한의 유효기간까지 지나면 준비 안 됨 상태가 될 수 있다. 이번에는 DB 권한 만료와 미수신 ACK, 실제 ready=false가 이 경로에 부합한다.

권한 만료 검증을 해제하거나 target_synced를 강제로 true로 만들지 않았다. 사용자의 승인/등록 자체가 취소된 증거도 없다.

## 4. 왜 새로고침을 반복해도 안 바뀌었나

Backend personal_mobile_status는 최신 ACL에 해당 credential의 활성 entry가 있고 snapshot이 미만료이며, 정확한 version+SHA의 APPLIED ACK가 있어야 access_ready=true를 반환한다.

Home wait_for_acl 버튼은 상태 조회만 한다. Target을 재접속시키거나 ACL을 강제로 적용하거나 문 개방 요청을 보내지 않는다. 실제 적용이 안 된 상태에서 조회만 반복하면 같은 대기 응답이 유지된다.

당시 Backend/API와 MQTT client/collector의 자체 readiness는12개가 정상으로 보였지만 target_status.fresh=false였다. Target freshness는 현재 personal profile에서 required=false다. API가 살아 있다는 상태와 현관 Target이 현재 출입 가능한 상태는 구분해야 한다. 상태 화면이 연결 공백의 원인·마지막 시각을 더 명확히 보여 줄 필요가 있다.

근거: backend/app/acl_management.py:2229~2273, gatekeeper_app/lib/screens/smart_key_home_screen.dart:499~515. 진단 API는 ACK/lease 자체를 노출하지 않아 NAS의 기존 Backend 컨테이너에서 SQL START TRANSACTION READ ONLY로 조회 후 rollback/close했다.

## 5. DNS·Wi-Fi에 대해 확인된 범위

- 장애 전후 동일 boot912/동일 boot ID다. boot advisory의 SOFTWARE는 오래된 부팅 원인이라 이번에 재부팅됐다는 증거가 아니다.
- 연결 시도505→646, 실패421→561, 연결 generation84→85가 관측됐다. 재시도는 수행됐지만 정상화까지 오랜 시간이 걸렸다.
- 남아 있는 최근4개 연결 실패 edge는 DNS_FAILED(-2)다. DNS는 broker 주소를 IP로 바꾸는 단계다. 이4개로 모든 실패의 세부 원인을 복원할 수는 없다.
- Wi-Fi generation2→3, outage2→3, 복귀 후 현재 CONNECTED/현재 outage0을 확인했다. 물리 공유기/상위 DNS/ESP32 DNS 복구 상태 중 어디서 최초 문제가 시작됐는지는 미확정이다.
- 조사 시점 broker4883은 정상 CA/hostname 및 TLS1.2 검증 후 실제 MQTT CONNACK135로 익명을 거부했다. 단순 TLS 접속만으로 broker 정상이라고 결론내리지 않았다.
-21:35 Grafana의 실제 homeassistant bucket에는21:34:46 SmartBox telemetry가 있었다. 당시 broker→다른 수집기 경로는 살아 있었지만, 이것이 Target 자체의 수신을 증명하지는 않는다.

재발 방지는 Target의 장시간 DNS/연결 실패 원인을 좁히고, 반복 실패가 안전한 네트워크 복구로 이어지는지를 검증하는 일이 우선이다. Wi-Fi 설정/센서 거리/휴대폰 절전을 원인으로 단정하거나 ACL lease를 임의 연장하는 수정은 하지 않았다.

## 6. 어떻게 회복됐고 이번에 무엇을 했나

조사 중 Target의 상태 보고가 같은 부팅 상태에서 다시 도착했다. 휴대폰 보고의 기존 캐시9831은 새 조회 뒤9842/9843 대기 상태로 바뀌었다. 이 캐시는 DB의 마지막 기적용9840과 구분한다. 이후 기존 Backend 자동 갱신 작업이9846에 대한 실제 APPLIED ACK를 받았다. 이후 exact version/digest 조건이 충족돼 대기가 해소됐다.

확인한 작업은 read API·DB·TLS/MQTT CONNECT·기존 UI/Grafana의 읽기 조회다. 코드 배포, NAS 서비스 재시작, 권한 강제 부여, Target 재부팅/OTA 또는 문 개방 명령을 수행하지 않았다. Target의 최초 통신 장애와 복귀를 촉발한 구체적인 계기를 이번 읽기 자료만으로 확정하지 못했다.

현재 해소된 것은 통신 신선도와 권한 동기화 대기다. 실제 물리 문 개방, 모든 OEM/화면 OFF 신뢰성 및 장시간 재발 방지 완료는 별도다.

## 7. 추가 운영·표시 개선점

1. Home에서 Target 마지막 정상 통신·연결 공백과 ACL 대기를 분리해 설명해야 한다. API/스캐너가 살아 있다는 정보만으로 현관 가용성을 표시하지 않는다.
2. PC read API에 최소 ACL 발행/적용 version, expiry, ACK 시각과 판정 이유가 있어야 한다. 이번에는 이 항목이 없어 추가 관리자 읽기가 필요했다.
3. 기존 무인 NAS 관리 키는 SSH 이후 sudo password required로 상세 진단이 막혔다. 동일 문제가11/02에도 기록돼 있어 이번 Target 장애의 원인으로 보지 않는다. 관리자 웹 세션의 기존 컨테이너에서 읽기만 수행했으며 sudo/SSH 권한은 변경하지 않았다.
4. Container Manager의 일부 중지 표시와 실제 MQTT/수집 동작이 일치하지 않았다. 그 표시만 근거로 중지 컨테이너를 시작하지 않았다. 구형 Grafana telemetry bucket의6월 자료도 오늘 근거에서 제외했다.
5. 별도 소스 점검의 ACK 도착 순서·수동 remote capability coupling 후보는 이번 원인으로 확정하지 않았다. 이 사건을 해결했다는 명목으로 ACK 검증을 낮추지 않는다.

## 8. 근거·확인 한계

원본은 /tmp/sgk-acl-wait-incident-20261105/ 및 recovery/, final-renewal/에 보존했다. Raw diagnostic JSON, 개인 이름·호수, 키/암호 원문은 Git에 넣지 않는다. DB 조회 출력은 version/시각/상태/일치 여부와 entry 개수만 포함했다.

연결·상태 core와 ACK 검증, unsigned advisory, 휴대폰 시계/identity cache, 서버 receipt를 구분했다. 최근 수집된 phone 자료는 제보 화면·버전과 부합하지만 read API의 이름/소유자 매핑은 제공되지 않는다. 사용자 직접 확인은 Home 정상 표시까지이며 물리 출입은 확인하지 않았다.

관련: [출입 증거 수집](access_evidence_recovery.md), [매립형 연결 계약](embedded_target_connectivity_policy.md), [모바일46901 배포](mobile_background_recovery_2026_11_04.md), [진단 API](diagnostics_read_api.md).
