# OTA 운영 runbook

> Last updated: 2026-08-01
> Scope: Android mobile, ESP32-C6 Target, Backend/NAS distribution, CI
> Status: 절차 확정; OTA-G1~G4 실기기 증거 pending

## 1. 배포 전 판정

1. `python scripts/ota_contract_gate.py contract`와 OTA 단위 테스트를 실행한다.
2. release commit에서 mobile/Target N/N-1 조합과 `ota/fault-injection-plan.json`의
   모든 physical Gate 증거를 수집한다.
3. `ota/release-evidence.json`에 증거 위치, 승인자, 승인 시각을 기록한다. 실제 증거 없이
   `pending`을 `passed`로 바꾸지 않는다.
4. release manifest와 pinned production public key를 전달한
   `python scripts/ota_contract_gate.py release`가 통과한 경우에만 production NAS 배포를
   허용한다. 현재 CI는 canary artifact를 먼저 보존하고 이 단계에서 production SFTP를
   차단한다.
5. mobile과 Target을 동시에 강제하지 않는다. 먼저 canary를 배포하고 N/N-1 telemetry를
   확인한 뒤 각 artifact를 독립적으로 확대한다.

## 2. Target canary 절차

1. 현재 slot, firmware version, boot ID, reset reason, NVS schema를 기록한다.
2. relay가 OFF이고 gate FSM이 IDLE인지 확인한다.
3. signed manifest의 board, flash layout, protocol 범위, size, digest, signing key를 확인한다.
4. inactive slot에만 기록하고 pending boot로 전환한다.
5. 재부팅 뒤 제한된 health window에서 relay default OFF, self-test, version/boot ID,
   Wi-Fi와 최소 하나의 update control plane을 확인한다.
6. 모든 조건을 만족한 뒤에만 valid mark한다. timeout, crash, reset loop 또는 health 실패는
   이전 slot rollback을 기대한다.
7. MQTT 차단 상태의 periodic HTTPS와 Backend/DNS 차단 상태의 authenticated local AP를
   별도로 시험한다.

## 3. Mobile canary 절차

1. 기존 APK version code, signing certificate digest, credential/preferences schema를 기록한다.
2. BLE scanner, foreground service, WebView를 각각 고장 주입해도 cold start/resume/settings의
   update control이 접근 가능한지 확인한다.
3. primary endpoint를 503으로 만들고 secondary metadata/APK를 사용한다.
4. metadata signature, APK SHA-256, APK signing certificate를 installer 호출 전에 확인한다.
5. 사용자 거부, 저장 공간 부족, 50% 다운로드 중단, 손상 APK에서 기존 앱과 credential이
   유지되는지 확인한다.
6. 설치 후 first-run health와 N/N-1 Target 통신을 확인한다. Android의 사용자 설치 승인은
   우회하지 않는다.

## 4. 중단·rollback 판단

다음 중 하나면 rollout을 즉시 중단한다.

- relay가 boot/OTA 중 ON이 되거나 one-shot cutoff가 지연됨
- artifact signature/digest 불일치가 installer/boot 선택 전에 차단되지 않음
- Target health 실패인데 valid mark되거나 이전 slot이 부팅되지 않음
- mobile 설치 실패가 기존 APK/credential을 손상함
- periodic HTTPS, local recovery, stable mobile fallback 중 약속된 경로가 막힘
- N/N-1에서 update UI 또는 OTA control plane이 접근 불가

Target은 새 slot valid mark 전이면 재부팅해 bootloader rollback을 관찰한다. valid mark 뒤
문제가 발견되면 마지막 정상 signed image를 새 OTA로 재배포하며 임의 partition erase를 하지
않는다. Mobile은 마지막 정상 서명 APK의 stable fallback URL을 제공하고 사용자의 package
installer 승인을 받는다. DB/NVS migration은 expand 단계 또는 copy-on-write 사본으로 되돌린다.

## 5. 장애별 운영 경로

| 장애 | 1차 | 2차 | 성공 증거 |
|---|---|---|---|
| MQTT 장애 | Target periodic HTTPS | authenticated local AP | install→reboot→health→valid |
| primary NAS 장애 | secondary distribution | local AP 또는 stable browser landing | 검증된 artifact 설치 |
| Target reset loop | bootloader rollback | local AP로 정상 image | 이전 version boot + health |
| mobile scanner/WebView 장애 | settings/manual update | stable browser landing | installer + new first-run health |
| 잘못된 signature/hash | 배포 중단 | signing pipeline/key ID 감사 | installer/boot 미호출 |
| 전원 차단 | 이전 정상 버전 부팅 확인 | local recovery | slot/APK 보존 증거 |

## 6. 필수 telemetry와 사후 기록

secret 원문 없이 component, device ID, current/target version, protocol range, stage, attempt,
error code, artifact digest, signing key ID, boot/install confirmation, rollback reason, boot ID를
기록한다. 성공은 upload/PUBACK/download가 아니라 mobile install 또는 Target
install→reboot→health confirmation이다. 모든 실기기 결과는 `wiki/hardware_test.md`에 날짜,
commit/build, 반복 횟수와 원시 증거 위치를 추가한다.
