# hardware_test.md — 테스트 증거와 현재 검증 상태
> Last updated: 2026-08-24 (H5 encrypted OTA manifest rejection and fail-closed Ed25519 provider correction)

## 1. 판정 원칙

과거 VL53L0X/ESP32 BLE scanner 아키텍처의 PASS는 변경 이력으로 보존하지만, 현재 **iBeacon → Android → FastAPI → MQTT → AJ-SR04T → Relay** 경로의 합격 근거로 간주하지 않습니다. 소프트웨어 빌드 통과와 실기기 E2E 통과도 분리합니다.

## 2026-08-23 N16 USB 설치 및 최초 부팅 확인

| 항목 | 관찰 결과 | 판정 |
|---|---|---|
| 칩/플래시 식별 | ESP32-C6 rev 0.2, JEDEC flash 16 MB | PASS |
| bootloader/partition | bootloader header 16 MB, dual OTA `0x700000` x2, 모든 write hash verified | PASS |
| application 크기 | 1,696,896 bytes / 7,340,032-byte slot = 23.12%, headroom 5,643,136 bytes | PASS |
| NVS 보존 설치 | `erase_flash` 없이 0x0/0x8000/0xe000/0x10000 이미지 기록 | PASS |
| 부팅 안정성 | 16 KiB loop stack 적용 후 stack panic/boot loop 없음; 마지막 45초 오류 출력 없음 | PASS (관찰창) |
| Wi-Fi 최초 연결 | disconnect reason 201 (`NO_AP_FOUND`) 반복 후 AP+STA fallback; DHCP/IP 성공 미관찰 | FAIL/PENDING (AP/RF) |
| MQTTS | production transport/verifier/command provisioning 거부 로그는 제거됐으나 Wi-Fi 부재로 broker online 미관찰 | PENDING |
| OTA | 런타임 크기/SHA/image/slot 검사와 CI 80% size gate 확인; 실제 download→install→reboot→health 미수행 | PENDING |

이 표는 연결된 개발대의 USB 관찰이다. Wi-Fi/MQTTS/OTA의 PASS나 최종 벽 매립 승인을 의미하지 않는다.

## 2026-08-23 Home Assistant secure discovery migration 검증

| 항목 | 관찰 결과 | 판정 |
|---|---|---|
| 기존 entity identity | historical discovery의 device identifier와 read-only unique ID 15개를 고정하고, runtime Target ID는 인자로만 주입 | PASS (software) |
| secure state namespace | read-only 15개 모두 per-Target 10초 `/status`와 30초 만료를 사용; boot-only non-retained `/availability`와 `/config-state`는 discovery에서 참조하지 않음 | PASS (software) |
| legacy write control 제거 | button 3개와 number 4개는 read-only 갱신보다 먼저 빈 retained payload로 삭제하며 새 config에 `command_topic`/`payload_press` 없음 | PASS (software) |
| publish semantics | fake broker client 경계에서 총 22건 모두 QoS 1, retain=true와 ACK 대기 경로 확인 | PASS (host test) |
| credential 경계 | 기본 dry-run은 network-free; username/password 직접 CLI 옵션 없음, env/file 값 출력 없음, credentialed apply는 TLS 필수 | PASS (host test) |
| live broker/HA registry | 실제 broker retained read-back 및 Home Assistant entity registry 확인은 수행하지 않음 | PENDING |

이 검증은 discovery payload 생성과 publish 경계의 host 증거다. live broker의 retained 수락,
Home Assistant registry의 in-place migration 및 stale control 제거를 증명하지 않으며, Target Wi-Fi/MQTTS,
문 열기, signed command bridge 또는 OTA 동작 증거로 승격하지 않는다.

### 같은 날 live Home Assistant 관찰

| 항목 | 관찰 결과 | 판정 |
|---|---|---|
| secure discovery live publish | 운영 internal broker에 15개 read-only retained config를 적용하고 기존 device identity에서 UI 갱신 확인 | PASS (live) |
| 주기 status | Target `c0feffe6ebac`의 `/status`로 firmware `2.1.0-gd06519e`, IDLE, IP `192.168.35.19`, distance 9990 mm, RSSI를 HA에서 확인 | PASS (live) |
| config-state | 현 Target가 boot 시 발행한 값을 관찰한 뒤 동일 값을 1회 non-retained로 seed하여 4개 설정 sensor 표시 확인 | PASS (live, seeded) |
| legacy controls | retained tombstone 7개를 live broker에 적용하고 retained read-back에서 button/number 0개 확인; current signed command bridge는 별도 미구현 | PASS removal / PENDING bridge |
| public MQTTS TLS | Mosquitto restart 뒤 `tworimpa.synology.me:4883`이 RSA SHA-256 `f2c90a2b4a8b3181bb0ae6863618a0101139593ff55105518726a10c78a94e23`, SAN hostname, public chain, TLS 1.3과 2026-10-19 만료를 검증 client에 제공 | PASS (live renewal; expiry monitoring still required) |

이 live 관찰은 read-only 상태 가시성 복구 증거다. 문 열기, reboot, OTA, 설정 변경은 backend signed
command bridge 없이 동작한다고 간주하지 않으며, live migration에서는 legacy control tombstone을 아직
적용했으며 retained read-back에서 legacy control config가 남지 않은 것을 확인했다. 새 write control은
만들지 않았고 실제 문 열기나 설정 변경도 수행하지 않았다.

## 2. 현재 코드 기준 검증표

| 영역 | 마지막 증거 | 판정 | 비고 |
|---|---|---|---|
| Flutter format/analyze/unit test | 2026-07-30 Docker, 5 tests | 🟢 PASS | Flutter 3.44.8 / Dart 3.12.2 |
| Android release APK build | 2026-07-30 Docker | 🟢 PASS | 당시 APK SHA-256은 `wiki/log.md` 기록 참조 |
| Backend syntax/Compose config | 2026-07-30 | 🟢 PASS | 실 broker/DB E2E와는 별개 |
| ESP32 v2.1 diagnostics build | Actions `30566577543` | 🟢 PASS | `2.1.0-g93cee8d`, NAS SFTP와 metadata 검증 성공 |
| iBeacon raw UUID/interval | 실측 없음 | 🔴 REQUIRED | nRF Connect/btmon으로 manufacturer payload 확인 |
| 화면 OFF·앱 swipe-away 접근 | 실기기 없음 | 🔴 REQUIRED | force-stop은 지원 불가 |
| Backend MQTT QoS1 PUBACK fail-closed | 코드/단위 정적 확인 | 🟡 DEVICE/BROKER TEST | 성공 200, 실패 503 확인 |
| Target MQTTS heartbeat/reset | 2026-07-31 remote, `g8eb7cac` | 🔴 RESET REPRODUCED | 세 번째 reset 직접 포착: uptime 919→7, gap 8.288초; 직전 heap 200,648 B/RSSI -58 |
| MQTT reset command correlation | 12분 read-only subscribe | 🟡 MQTT PATH EXCLUDED | 세 번째 reset 전 cmd/arm/force/config 입력 0; retained는 config state뿐 |
| AJ-SR04T 거리·ghost filter | 과거 현장 로그 존재 | 🟡 RE-TEST | 현재 전체 경로에서 20–50 cm 재검증 |
| 릴레이 High-Z OFF/노이즈 내성 | freeze 이력 있음 | 🔴 REQUIRED | 전원 재인가 없이 반복 동작 확인 |
| Wi-Fi/BLE coexistence | watchdog 수정됨 | 🔴 REQUIRED | 장기 soak test 필요 |
| v2.1 OTA 설치/재부팅 | 2026-07-31 remote MQTT/status | 🟢 PASS | `g8eb7cac` → `g93cee8d`, target/boot/reset telemetry 확인 |
| retained flash coredump | v2.1 boot payload | 🔴 PANIC CONFIRMED | loopTask `udp_new_ip_type` core-lock assertion, 11,044 B valid coredump |
| Target OTA rollback/16 MB partition | 과거 OTA 성공 기록 | 🔴 P0 BLOCKER | #23: 양 slot, health mark, 실패 자동 rollback, power-loss 검증 필요 |
| 모바일 APK update 비회귀 | 과거 NAS APK 다운로드 기록 | 🔴 P0 BLOCKER | #23: scanner 독립 update, hash/signing identity, fallback, N/N-1 검증 필요 |
| OTA artifact/schema/semantic negative vectors | 2026-08-01 host unit test 18건 | 🟢 CONTRACT PASS | 실제 artifact size/SHA-256·APK certificate binding과 invariant/recovery fail-closed 검증; 물리 install/boot/rollback 증거 아님 |
| OTA-G1~G4 physical matrix | 실측 없음 | 🔴 RELEASE BLOCKED | periodic HTTPS/local AP, Android fallback, N/N-1, power-loss/rollback 실기기 필요 |
| Epic #13 implementation authorization | 2026-08-02 사용자 승인 + machine-readable contract | 🟢 G0-SW ONLY | #17~#22 software 구현/리뷰/merge 허용; production·물리 완료 증거 아님 |
| #18 core/adapter host tests and builds | 2026-08-02, 87 repository tests + default-OFF/feature-ON ESP32-C6 builds | 🟢 SOFTWARE PASS | connection generation, second peer, reconnect race, overflow ordering, indication ACK/error/timeout, provisioned/cross-door binding, WAIT_SAFE_STATE contract; no radio/GPIO/relay/OTA physical evidence |
| Epic #13 production authorization | 실측 없음 | 🔴 G0-HW BLOCKED | Samsung/OEM, ESP32-C6 real BLE, relay/sensor, bootloader, OTA-G1~G4, RELAY-G0~G2 필요 |

## 3. 현재 E2E 인수 절차

1. 보드 부팅 후 Wi-Fi, MQTT TLS, iBeacon 광고를 동시에 확인합니다.
2. 광고 payload의 `4C 00 02 15` 뒤 UUID 16바이트와 100 ms interval을 캡처합니다.
3. 승인/미승인 Android 기기로 화면 ON, 화면 OFF, task swipe-away를 각각 시험합니다.
4. 승인 요청 성공 시 서버가 QoS 1 PUBACK을 받은 경우에만 HTTP 200과 `mqtt_published=true`를 반환하는지 확인합니다.
5. ARMED 동안 20 cm 미만은 무시되고 20–50 cm 접근은 릴레이를 정확히 1초 구동하는지 확인합니다.
6. 기본 3초 cooldown, 60초 arm expiry, 중복 요청 억제를 검증합니다.
7. MQTT 단절, NAS 단절, 잘못된 API key에서 문이 열리지 않고 앱이 진단 가능한 오류를 표시하는지 확인합니다.
8. 최소 100회 릴레이 반복과 24시간 Wi-Fi/BLE soak 동안 freeze/reset/광고 중단 여부를 기록합니다.

## 4. 과거 검증 이력

| 날짜 | 당시 아키텍처 | 결과 | 현재 적용 범위 |
|---|---|---|---|
| 2026-07-24 | VL53L0X + relay Local PoC | PASS | 릴레이/보드 초기 PoC 이력만 인정 |
| 2026-07-24 | ESP32 → NAS HTTPS → relay | PASS | 현재 역할 반전 흐름과 다름 |
| 2026-07-24 | MQTTS/HA/OTA 통합 | PASS | 인프라 선행 증거, current regression 필요 |
| 2026-07-28 이후 | AJ-SR04T 필터·모바일 beacon 수정 | 코드 변경 다수 | 최신 통합 실기기 재검증 필요 |
| 2026-07-31 | 공인 MQTTS → Target status 관측 | PARTIAL | certificate/hostname·CONNACK·SUBACK 확인; 분리된 20초+30초 안정성만 증명하며 reset 원인은 미확인 |
| 2026-07-31 | 12분 status/control 연속 감시 | FAIL/DIAG | status 678건 뒤 uptime 919→7 reset; 정상 RSSI/heap, MQTT command 없음 |
| 2026-07-31 | retained config/command wildcard 감사 | PASS | `gatekeeper/config/state`만 retained, destructive/config command 없음 |
| 2026-07-31 | v2.1 CI → NAS → MQTT OTA | PASS | run `30566577543`, status의 firmware/reset/boot identity로 설치 확인 |
| 2026-07-31 | OTA 후 retained coredump 회수 | FAIL/ROOT CAUSE | 이전 firmware의 loopTask lwIP UDP core-lock assertion 확인 |

새 하드웨어 결과는 날짜, firmware commit, 앱 build, 환경, 반복 횟수, 원시 로그/캡처 위치와 함께 이 표에 추가합니다.
## 2026-08-09 Target command/OTA security evidence

| Date | Test | Result | Evidence boundary |
|---|---|---|---|
| 2026-08-09 | Signed command mutation, replay, crash, and storage-fault host tests | PASS (software) | Target/tenant/door/boot/freshness/signature mutations rejected; completed and uncertain duplicates do not repeat effects |
| 2026-08-09 | OTA contract/state/fault and insecure-path host tests | PASS (software) | Verifier/state/static seams exercised without a physical ESP32-C6 or deployed NAS broker |
| 2026-08-09 | #50 independent-review remediation mutations | PASS (software) | Delayed first command stays clock-untrusted; STA-preserving bounded recovery AP seam covers DNS/Backend outage; transient health resets; late recovery rolls back; prerelease/equal-precedence/reboot storage replays reject |
| 2026-08-09 | `pio run -e esp32c6 -j 4` | PASS (software build) | RAM 53,728/327,680; flash 1,600,194/7,340,032; no upload or device execution |
| 2026-08-09 | Authenticated current-boot registry and strict command parser | PASS (software) | Root 102 tests and backend 49 tests (one opt-in MariaDB skip); WSL/Linux production-core seam passed; final ESP32-C6 build used 53,888/327,680 RAM and 1,606,490/7,340,032 flash; no broker or device execution |
| 2026-08-09 | Exact-head duplicate/deadline review mutations | PASS (software) | Every signed-command field rejects same/different duplicate raw JSON members before DOM parsing; health tests cover deadline-1, exact equality, deadline+1, and stalled samples; ESP32-C6 build used 53,888/327,680 RAM and 1,606,546/7,340,032 flash |
| Pending | Physical Target OTA and hardening | OPEN | ESP32-C6 inactive-slot boot, health-valid, power-loss, rollback, periodic HTTPS, local recovery, eFuses/debug locks, radio/relay, N/N-1, operator soak, and production authorization remain unproven |

## 2026-08-23 Recovery portal scan and production connectivity evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Candidate identity | `main` `21107958` plus the unmerged recovery-scan fix, version `2.1.0-g2110795-scanfix`; app-only write at `0x10000`, NVS preserved, flash write hash verified | PASS for field candidate; exact merged-main reinstall still required |
| Recovery scan driver | The previous field image returned `-2` while stale STA authentication retried. The candidate returned 11, 13, 12, 13 and 9 visible AP records in repeated authenticated scans | PASS |
| Recovery portal UI | The phone rendered the explicit network list, selected `SK_WiFiGIGAA947`, and Target logged the matching credential-save request without logging the password | PASS |
| Wi-Fi association | After reboot the AP+STA recovery path obtained DHCP address `192.168.35.19` and logged `provisioning AP station recovery succeeded` | PASS for association and DHCP; long soak pending |
| MQTTS | Target connected to the provisioned TLS broker, subscribed to exact per-Target topics, and published retained boot diagnostics/config state | PASS for current boot; WAN/broker failure soak pending |
| Runtime reconnect | One later beacon timeout (`reason 200`) closed the stale TLS socket; Target regained `192.168.35.19`, reconnected MQTTS, resubscribed and republished boot/config diagnostics without a reboot | PASS for one automatic recovery; repeated/long soak pending |
| OTA capacity | Candidate app 1,699,616 bytes in each 7,340,032-byte slot, 23.16% usage and 5,640,416-byte headroom | PASS for capacity only; periodic HTTPS install, reboot health, rollback and power-loss tests remain pending |

This evidence supersedes the earlier same-day `NO_AP_FOUND` first-boot attempt only
for recovery scan, Wi-Fi association, DHCP and MQTTS. It does not promote the
candidate to production release approval or close the physical OTA/relay/soak gates.

## 2026-08-23 Target OTA rollback and download safety host evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Failed-floor quarantine | Native C++ version-policy tests reject the exact persisted failed floor after a lower slot boots, retain equal-precedence identity-conflict rejection, and accept a strictly newer recovery version | PASS (host software) |
| Bounded remote download | Static Target contract confirms 30-second no-progress and five-minute total deadlines, inactive-write abort, explicit timeout reason and 15-minute retry scheduling | PASS (host/static software) |
| WAIT_SAFE_STATE failure | Static Target contract confirms failure status, reason, retry scheduling and immediate return before any network request | PASS (existing behavior, regression guarded) |
| ESP32-C6 build/capacity | Default N16 build succeeded; app image 1,662,160 bytes in a 7,340,032-byte slot, 22.65% usage and 5,677,872-byte headroom | PASS (compile/capacity only) |
| Physical install/rollback | No firmware was uploaded by this change; inactive-slot install, timeout injection, bootloader rollback and failed-version quarantine remain unobserved on ESP32-C6 | PENDING physical evidence |

## 2026-08-23 Public MQTTS certificate recovery evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Export validation | The selected RSA leaf covered `tworimpa.synology.me` and `*.tworimpa.synology.me`, matched its private key, verified against the exported two-certificate chain, and expires 2026-10-19 | PASS (offline material validation) |
| NAS replacement | The audited Mosquitto `certfile`, `cafile`, and `keyfile` were backed up and replaced; replacement readback matched the approved certificate/key/chain before restart | PASS (on-disk recovery) |
| Live TLS after restart | A default-trust client completed hostname and public-chain validation on port 4883, observed TLS 1.3 and the approved replacement certificate fingerprint | PASS (live endpoint) |
| Authenticated MQTT | The provisioned broker principal received CONNACK success and SUBACK for the exact Target status topic over verified TLS | PASS (live transport/authentication) |
| Target reconnection | A fresh periodic status from Target `c0feffe6ebac` reported boot ID `c2f1ce127f0d5a3a296bb781319dc904`, state IDLE and IP `192.168.35.19` after the broker restart | PASS for current reconnect; outage soak remains pending |

This recovery proves the current public TLS endpoint and one authenticated Target
reconnection. It does not prove automatic certificate renewal, expiry alerting,
long broker/WAN outage recovery, Target OTA installation, reboot health, rollback,
relay safety or final wall-install acceptance.

## 2026-08-24 exact-main encrypted Target USB bootstrap

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact release identity | GitHub Actions Target run `32655789147` published exact main `9e9114b7ddc93e54adab1230341a3bc520b1aa68` as `2.1.233+main.g9e9114b`; signed manifest, encrypted artifact, public HTTPS exact-byte readback and local authenticated decryption all passed | PASS for CI/NAS artifact identity |
| N16 capacity | Plaintext application was 1,703,392 bytes in a 7,340,032-byte slot (23.21%); headroom 5,636,640 bytes. ESP32-C6 image checksum and appended hash were valid and the image declared 16 MB, 80 MHz, DIO | PASS |
| Pre-write preservation | Read-only backup captured the 16 MB partition table, 20 KiB NVS, 8 KiB OTA data and both valid application headers. `app0` was selected and `app1` remained a bootable fallback | PASS |
| USB write | Wrote only the exact application to `app0` at `0x10000`; no erase, bootloader, partition-table, NVS, OTA-data, SPIFFS or `app1` write occurred. esptool verified the written-data hash and hard-reset the Target | PASS for NVS-preserving bootstrap |
| First boot Wi-Fi | Serial identified `2.1.233+main.g9e9114b`, restored the saved SSID from NVS, associated and received `192.168.35.19` | PASS for one boot; three-cycle and outage soak remain pending |
| MQTTS | The Target completed verified TLS broker authentication, subscribed to both exact per-Target command/ACL topics and published boot diagnostics plus current config state | PASS for one boot/session; broker/WAN soak remains pending |
| Authenticated recovery UI and scan | A connected Android device on the same Wi-Fi received HTTP 200 for the authenticated controller page. The page included the explicit list renderer and automatic `/scan`; `/scan` returned a JSON array with 13 visible networks including the active SSID, and serial logged the same count | PASS for STA-local portal/scan; AP-only upload recovery remains pending |
| Home Assistant convergence | After refresh, the existing Smart Gatekeeper device showed `2.1.233+main.g9e9114b`, `192.168.35.19`, `IDLE`, closed door and current distance, RSSI, heap, uptime and four config values | PASS for read-only live telemetry |
| Legacy Home Assistant controls | Seven historical button/number registry entries were still visible even though their retained discovery configs had been tombstoned. They were not invoked; the authenticated backend signed-command bridge remains absent | PENDING registry cleanup / signed bridge |
| Inactive-slot OTA and health | This installation was a direct app-only USB bootstrap into the already selected slot, not a periodic HTTPS write to inactive `app1`; bootloader pending-verify, 30-second health-valid mark and rollback were not exercised | PENDING second exact-main physical OTA |

Immediately after this observation the Target content-encryption key was rotated
without recording its value. GitHub `personal-auto-ota`, GitHub `production` and
the ignored local headers share the policy-pinned key ID
`personal-target-content-20260824-1`. The key material changed while this label
remained fixed because the exact workflow contract rejected a different ID; the
label alone therefore does not identify the material epoch. Exact firmware
commit and manifest binding are required when auditing this emergency rotation.

## 2026-08-24 rotated-key H4 Target USB bootstrap and recovery

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact release identity | GitHub Actions Target run `32657300554`, attempt 2, published exact main `3927a978a8727eac086e88d20bfaa2d414908dbc` as `2.1.234+main.g3927a97`; signed manifest, encrypted artifact and public HTTPS exact-byte readback passed | PASS for CI/NAS artifact identity |
| Artifact binding and capacity | The encrypted artifact was 1,703,428 bytes with SHA-256 `45ff37d858d5fb38a4f2aa397e5809e66be7b42be9cc1b10d97fe32acd18da7f`; authenticated local decryption produced a 1,703,392-byte ESP32-C6 N16 image with SHA-256 `8910bc7cfeef47713c5be57fbc4ab72d379b7435f84949ec49181a4e769dfbcb`, using 23.21% of one 7,340,032-byte OTA slot | PASS |
| Rotated-key bootstrap | Wrote only the exact H4 application to selected `app0` at `0x10000`; NVS, OTA data, partition table, bootloader and `app1` were not erased or overwritten | PASS for the one required NVS-preserving USB bootstrap |
| AP+STA automatic recovery | The initial saved-credential STA attempt timed out and opened `SmartGatekeeper-Recovery`. Without credential entry or physical intervention, AP+STA retry obtained `192.168.35.19` about 54 seconds after the first attempt, then closed the recovery condition | PASS for one boot-failure recovery path; repeated power/AP outage soak remains pending |
| MQTTS after late Wi-Fi | About five seconds after DHCP recovery, the Target completed verified MQTTS authentication, subscribed to both exact per-Target topics and published boot diagnostics/config | PASS for late-Wi-Fi MQTT initialization and one recovered session |
| Home Assistant convergence | Live read-only entities reported `2.1.234+main.g3927a97`, `192.168.35.19`, IDLE/closed, RSSI about -84 dBm and current diagnostics/config. The HA device-card metadata header still showed an older static discovery version | PASS for live sensor convergence; discovery metadata and seven stale legacy controls remain cleanup work |
| Inactive-slot OTA and health | H4 was intentionally the USB bootstrap carrying the rotated key material. The strictly newer main release created by this documentation change is the first eligible encrypted periodic HTTPS update to inactive `app1` | PENDING physical H5 install/reboot/health-valid proof |

## 2026-08-24 H5 encrypted OTA manifest rejection

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact H5 publication | Target run `32658670039` published exact main `6517caa957dcf1c42ece49d15e38a428c81262e5` as `2.1.235+main.g6517caa`. NAS immutable artifact/pointer publication and exact HTTPS readback completed | PASS for CI/NAS transport only |
| Offline cryptographic binding | The 1,703,428-byte envelope SHA-256 `5e09d67e1c0798a87e2fc319f7f249d64346702504d1f9d2602bfa27cf2d9a16` passed Ed25519 manifest verification and AES-256-GCM authentication locally. The decrypted 1,703,392-byte image SHA-256 `67d037c0b824b628e52f16e8b41a559f86a46e4a5b3b4298ff2e319a8a9388e8` matched the manifest and passed ESP32-C6 N16 image/checksum/hash inspection | PASS for exact offline bytes; not Target runtime evidence |
| Periodic HTTPS attempt | H4 remained online with Wi-Fi, MQTTS and Home Assistant status continuing, but did not reboot to H5 after the periodic check window | FAIL for H5 install |
| Authenticated local recovery attempt | An authenticated same-LAN recovery request enabled the bounded recovery window, but posting the exact H5 manifest returned HTTP 400 before artifact upload/download | FAIL at Target manifest validation |
| Slot preservation | No firmware payload was uploaded and no write to inactive `app1` occurred. H4 remained the running image, so the active slot, NVS and existing fallback were not displaced | PASS for fail-closed preservation |
| Root cause | H4 called PSA PureEdDSA, but the actual ESP32-C6 Arduino/ESP-IDF Mbed TLS configuration did not provide that Ed25519 algorithm at runtime even though the PSA constant was present in headers. The exact manifest was therefore rejected before artifact processing | ROOT CAUSE CONFIRMED |
| H6 candidate correction | Manifest verification now uses the bundled Espressif libsodium `sodium_init()` and `crypto_sign_verify_detached()` path, retains exact 32-byte public-key/64-byte signature contracts and fails closed on provider or signature failure | PASS for source/build/host tests only; physical H6 pending |

H5 publication, readback and offline cryptographic verification are not OTA
completion evidence. H4 cannot authenticate a corrective signed image with its
unavailable provider, so exact merged-main H6 must first be installed app-only
over USB while preserving NVS, OTA data and the fallback slot. A strictly newer
H7 must then prove signed manifest acceptance, inactive-slot write, planned
reboot, new version and boot ID, continuous health-window completion and valid
mark. Rollback and power-loss injection remain separate pending tests.

## 2026-08-24 H6 bootstrap and H7 encrypted-stream failure evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact H6 USB bootstrap | Exact main `02090c31b6813d6d1691262809dfc86330283a9d`, version `2.1.237+main.g02090c3`, was written app-only to selected `app0`; no full-chip erase or NVS erase was used | PASS for corrective USB bootstrap; not OTA |
| H6 Wi-Fi/MQTTS | After reboot H6 restored the saved SSID, acquired `192.168.35.19`, authenticated MQTTS, subscribed to exact per-Target topics and published diagnostics/config | PASS for one current boot/session; soak remains pending |
| Exact H7 CI/NAS | Run `32662983244` published exact main `e00ebe84dbd7a4c9323b21e393429c9d44f4cdb3` as `2.1.238+main.ge00ebe8`; latest and immutable manifests were byte-identical and Ed25519/AES-256-GCM/ciphertext/plaintext/image verification passed | PASS for CI/NAS bytes |
| H7 capacity | Plaintext was 1,795,248 bytes, SHA-256 `fc939b690f0418a917172393abb35ba769910b8e5b540c93884053df5e9b9b4e`; encrypted artifact was 1,795,284 bytes. Each 7,340,032-byte slot retained 5,544,784 bytes headroom | PASS; 24.46% slot usage |
| Target manifest/download | H6 accepted the exact H7 signed manifest and began the full encrypted download on three fresh boots | PASS for embedded Ed25519 verifier and HTTPS reachability |
| Inactive-slot completion | All three attempts ended with `[OTA-ERROR] image write/hash`; boot partition was never changed and active H6 plus NVS remained usable | FAIL for H7 install; fail-closed active-slot preservation PASS |
| Failed `app1` readback | First full readback SHA-256 was `ffa311011453f871bca9e85468416c890b337e7acc5f37a1f1a4416f842ccfeb`. Two attempts matched expected plaintext through offset 3804 and first differed at offset 3805 (`0xEDD`, `mod 16 = 13`) | ROOT CAUSE BOUNDARY CONFIRMED |
| GCM implementation root cause | Pinned Arduino 3.3.9 / ESP-IDF libs 5.5.4 GCM ALT resets multipart CTR residual and zero-pads partial GHASH per call. The exact `3841 + 437×4096 + 1491` transport sequence reproduced every failed-slot byte | ROOT CAUSE CONFIRMED; not RF/HTTPS corruption |
| Correction candidate | Runtime now carries 0..15 ciphertext bytes across calls, feeds only 16-byte multiples to non-final GCM updates, validates final carry modulo, and emits stage-specific safe error counters | PASS for source/host contract; production build and USB→next-OTA physical proof required |

The H7 failure deliberately invalidated only inactive `app1`; H6 remained the
active bootable slot and MQTTS recovered after each abort. Repeating H7 would
only rewrite the same inactive slot, so the Target was left in the USB stub
bootloader without flash mutation while the corrected image is built. The
current authenticated local upload path shares the same pre-fix GCM engine and
is not a valid workaround.

## 2026-08-24 exact H7 Android installation and Home Assistant observation

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Signed APK identity | GitHub run `32662983256` produced package `com.kshouse.gatekeeper_app`, version `1.0.0-ge00ebe8`, build `16001`; manifest Ed25519, APK v2/v3 signatures and expected certificate SHA-256 passed | PASS |
| Connected-device install | `adb install -r` on SM-F966N/Android 16 succeeded, the cold-started `MainActivity` became `topResumedActivity`, process remained alive and filtered fatal logs were empty | PASS for install/launch; OEM background access remains separate |
| Installed-byte identity | Pulling installed `base.apk` returned 55,770,265 bytes and SHA-256 `1e60e0cb878aab7f176807de2fb7284b653fd704cbef8c49e9dbcf71a281beae`, exactly matching the signed Actions artifact | PASS for exact installed APK |
| HA telemetry vs legacy controls | Live HA state showed 15 current read-only Target entities and six restored/unavailable historical control entities. Target firmware no longer publishes those unsigned command/config discovery records | PARTIAL: telemetry usable; stale registry cleanup pending |

The Android result proves exact H7 installation and one foreground launch, not
the NAS updater's end-user install flow, background scan reliability or mobile
rollback. The six HA controls must be removed from retained discovery/registry;
they must not be re-enabled without the separately reviewed signed backend
command bridge.

## 2026-08-24 H9-H11 Target OTA, RF isolation and HA migration

| Test | Observed result | Verdict / boundary |
|---|---|---|
| H9 NVS-preserving bootstrap | Exact-main H9 was written only to app0; pre/post readback verified bootloader, partition table, NVS, OTA data and app1 prefix were unchanged before first application boot | PASS for app-only bootstrap |
| H10 CI/NAS identity | Run `32667129968` published `2.1.241+main.g3311ad6`; the 1,796,080-byte plaintext and 1,796,116-byte encrypted artifact passed signature, GCM, digest and ESP32-C6 N16 checks with 5,543,952 bytes slot headroom | PASS for exact bytes/capacity |
| H9 → H10 periodic HTTPS | On a nearby 2.4 GHz AP the Target accepted the signed H10 manifest, downloaded the full encrypted artifact, verified the inactive image and rebooted to the exact H10 banner | PASS for signed encrypted install/reboot |
| H11 CI/NAS identity | Run `32668550147` published exact main `7a55a667b9d30f7929176997010d7ab71abaf833` as `2.1.242+main.g7a55a66`; manifest SHA-256 `280db36e2fe1b4a42e92a3a06c591887f95436d28cca114539d3263f5922647f`, encrypted SHA-256 `bd6274253224720e9c655bcf9e25609255516a5da8d7786973f6825789a155ef`, plaintext SHA-256 `ec5e24684f806c25f547be0f768932e419d6d5e4c4a0815f4a2b7b1d8faf0a6`; N16 headroom remained 5,543,952 bytes | PASS for exact CI/NAS bytes/capacity |
| H11 runtime | H11 booted, obtained `10.71.25.196` from the nearby AP, completed verified MQTTS, subscribed to exact Target topics, published diagnostics/config and reported `already current` for H11 | PASS for one live Wi-Fi/MQTT/current session |
| Intended home AP | Target scan observed the relevant 2.4 GHz signals around `-80~-82 dBm`; repeated reason 2/4/201 prevented stable association. Android freshly authenticated to the same SSID, while the Target connected immediately to the nearby AP around `-42 dBm` | FAIL for wall RF margin; credential/firmware path independently PASS |
| Recovery portal save | Android joined the authenticated recovery AP over USB-controlled Wi-Fi, sent `/save` with local auth and received HTTP 200; Target rebooted with the new NVS credential and later recovered station/MQTT service | PASS; no credential value logged |
| Home Assistant discovery | Applied 15 retained read-only discovery configs and seven legacy tombstones; an independent subscriber saw exactly 15 valid retained configs. With H11 online, HA showed firmware, IP, RSSI, IDLE/door state and config values live | PASS for read-only telemetry migration |
| Legacy HA controls | Historical button/number entities remain `restored/unavailable` in the HA registry after retained tombstones. They were not invoked or revived because no signed-command bridge exists | PENDING registry cleanup; fail-closed |
| OTA health/rollback | No `pending image health window started` or `running image marked VALID` log was observed on the retained bootloader/OTA-data path | PENDING; install/reboot/current does not prove health-valid or rollback |

The weak-link STA profile added after this observation must be tested on the
same hardware and position. Passing at `-81 dBm` would still not authorize wall
installation; section 5 of the connectivity policy requires RF improvement and
repeated outage/boot evidence.

## 2026-08-24 quiet recovery-AP arbitration candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Host timing/transitions | Native C++ policy tests cover the initial 30-second quiet interval, client/auth/operation blockers, one 10-second attempt, failure-to-quiet, request interruption, idle-client 10-minute expiry/deauth action, persistent reassociation before and throughout a forced bounded attempt, authenticated interruption, station success, `millis()` wrap and the timed-window zero-sentinel edge | PASS for deterministic policy logic |
| Firmware integration contracts | Focused connectivity/security tests verify one WebServer service call per loop, authenticated attempt pause, scan/save/local-OTA leases, no immediate post-scan reconnect, idle-client release, active-operation deadline deferral before AP close, AP-exit auto-reconnect restoration and unchanged MQTTS/OTA health gates | PASS for source integration; not radio runtime |
| ESP32-C6 compile/capacity | Default `esp32c6` compile with non-secret compile-only placeholders succeeded on Arduino 3.3.9 / ESP-IDF libs 5.5.4. `firmware.bin` is 1,786,336 bytes, leaving 5,553,696 bytes in either 7,340,032-byte OTA slot; the temporary ignored header was removed after the build | PASS for build and capacity; not a production-secret artifact |
| Boot recovery AP visibility | No physical Target was flashed from this candidate in this task | PENDING: verify at least 30 seconds of uninterrupted SSID discovery and association |
| Portal scan/list/save | No Android AP-only request/response or NVS-preserving reboot was exercised from this candidate | PENDING: authenticate, render list, select/manual fallback, save, reboot and read back without logging credentials |
| STA/MQTTS/OTA recovery | No physical late-STA association, MQTTS reconnect, periodic HTTPS OTA, signed local OTA, health-valid or rollback sequence was exercised | PENDING; wall installation Gate remains open |

The build proves that `esp_wifi_deauth_sta(0)` and the policy adapter compile for
ESP32-C6. It does not prove beacon continuity or coexistence behavior. Physical
testing must also leave a phone associated but idle through the bounded hold,
confirm that active authenticated upload is not interrupted, and verify that
normal pure-STA auto-reconnect, MQTTS, and signed OTA resume after AP exit.

## 2026-08-24 exact-main Target connectivity and recovery-path evidence

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact runtime identity | The ESP32-C6 serial banner reported exact main `af779e1e61cd6c5c25b9b11e9aab9d1197ca094d` as `2.1.251+main.gaf779e1` | PASS for the observed running image |
| NVS Wi-Fi recovery | The Target restored the saved Fold7 hotspot profile from NVS, recovered from one transient authentication failure and obtained `10.71.25.196`; the SSID is intentionally omitted | PASS for this boot and reconnect only |
| Relay boot state | Serial reported the relay OFF before and after application initialization | PASS for logged software state; no physical relay actuation or electrical measurement |
| MQTTS | The Target authenticated, subscribed to the exact per-Target topics and successfully published retained boot diagnostics and config state | PASS for this live session |
| Periodic signed OTA | The periodic signed manifest check completed with an already-current result for the running exact release | PASS for manifest reachability/validation/current-version handling; no inactive-slot write or reboot |
| Authenticated local recovery | The same-LAN recovery path returned HTTP 401 without authentication, HTTP 200 with authentication and HTTP 202 for authenticated `enable-ap` | PASS for authentication enforcement and bounded AP enable request |
| AP+STA service continuity | During the recovery AP+STA window, Home Assistant kept all 15 read-only entities available while Target uptime advanced from 234 to 302 seconds | PASS for the observed 68-second coexistence interval |
| Post-reset convergence | After the final reset, Home Assistant again showed all 15 read-only entities available while uptime advanced from 51 to 101 seconds | PASS for one reset/reconnect interval |
| Default-disabled security state | NVS had no ACL signer or hardwareless-door override; the Target logged ACL verification fail-closed and Hardwareless GATT disabled | PASS for default-disabled behavior; provisioning/functionality was not exercised |

This run does not prove a real inactive-slot OTA installation, the continuous
health-valid mark, bootloader rollback, power-loss recovery, physical relay
operation/electrical safety, AJ-SR04T behavior or final wall-install acceptance.

## 2026-08-25 exact-main Android artifact pre-install verification

| Test | Observed result | Verdict / boundary |
|---|---|---|
| CI artifact identity | GitHub Actions run `32747024524`, artifact `personal-mobile-ota-7c2764a1a16492ec1620079c8211b47287b1b3fd-attempt-1`, supplied a 55,786,649-byte APK with SHA-256 `afb0cdc5eb95d8c0dd8c34597b180ddb803b6d8b35b9b1e130da7db13f054f42` | PASS for downloaded CI bytes |
| APK manifest | `aapt` reported package `com.kshouse.gatekeeper_app`, `versionCode=18201`, `versionName=1.0.0-g7c2764a` | PASS |
| APK signing continuity | `apksigner verify --verbose --print-certs` passed and reported signing-certificate SHA-256 `8bdbcf86c2530d424758a37b5a678de02b8f35587143d820c730b83cfe1d7ba0` | PASS for APK signature and expected production signer |
| Embedded source identity | `assets/flutter_assets/assets/source_commit.txt` contained exact source commit `7c2764a1a16492ec1620079c8211b47287b1b3fd` | PASS |
| Connected-device installation | The APK was intentionally not installed during this verification-only step | PENDING: preserve the installed app and use same-signature `adb install -r` in the controlled device step |

This proves that the downloaded CI APK is internally consistent and eligible
for the same-signature replacement check. It does not prove Android package
installation, first launch, credential preservation, enrollment, native GATT,
background behavior or rollback.

## 2026-08-25 personal GATT and signed Home Assistant live baseline

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Android replacement install | The run `32747024524` production-signed APK was installed with `adb install -r`; package data remained present and the app reported `1.0.0-g7c2764a` / build 18201 | PASS for same-signature install and launch; uninstall/data clear was not used |
| Android native state | Bluetooth/location permissions, background location, Bluetooth ON, battery allowlist, local consent, Keystore credential and native GATT ownership were all present; the prior `NATIVE_GATT_DISABLED` reason disappeared | PASS for enablement prerequisites |
| Target exact-main OTA | Run `32749448224` published `2.1.256+main.g7c2764a`; the 1,844,800-byte image fit either 7,340,032-byte N16 OTA slot with 5,495,232 bytes headroom. Target installed/rebooted, obtained `192.168.35.19`, connected MQTTS, provisioned the production ACL signer, applied ACL v3 and started connectable GATT | PASS for this install, boot and transport state; rollback/power-loss remains pending |
| NAS Backend and HA bridge | Recreated the live Backend after correcting the paho MQTTv5 callback. Readiness passed, bridge retained availability became online, and Home Assistant rendered reboot/open/OTA/config controls enabled | PASS for discovery/availability; no HA command or relay was invoked |
| Android exact wake | The OS PendingIntent exact iBeacon scan was registered but reported zero filtered results; unfiltered Bluetooth state still saw `SmartGatekeeper`, and manual local retry returned `TARGET_UNAVAILABLE` because no locator existed | FAIL at advertisement matching, before GATT connection |
| Root cause | Pinned pioarduino swaps the `BLEBeacon` manufacturer setter argument. Target `0x004C` emitted company bytes `00 4C`, while Android correctly filters Apple `0x004C` as standard on-air `4C 00` | ROOT CAUSE CONFIRMED |
| Correction candidate | Target now passes `0x4C00`; source regression passed 9/9 and personal-production compile produced 1,779,430 bytes with 5,560,602 bytes slot headroom | PASS for source/build only; CI/NAS OTA and physical Android/GATT result pending |

The two feature planes are enabled, but this baseline does not yet claim local
door authorization: the corrected Target must advertise on air, Android must
record a locator, and the exact challenge/proof/result must reach the Target
FSM. Physical relay actuation and electrical safety remain separate Gates.

## 2026-08-25 exact wake, HA OTA and GATT callback-stack investigation

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact-main Target publication/install | GitHub Actions run `32768108034` published `2.1.259+main.gbc9bb5d`; the live HA OTA button delivered the signed command, after which Target downloaded, verified, installed and rebooted into that exact version | PASS for HA control → signed Target OTA → install/reboot/current-version; rollback and power-loss remain pending |
| Exact-main Android replacement | Run `32768108110` published production-signed `1.0.0-gbc9bb5d` / `versionCode=18501`; its manifest/artifact identity and APK signature verified, and `adb install -r` preserved package data and the enrolled credential | PASS for exact APK identity, same-signature replacement and state preservation |
| Android exact iBeacon delivery | Corrected company bytes produced ten OS PendingIntent exact-filter results with callback latency 6–20 ms and observed RSSI about -46 to -50 dBm | PASS for this connected, screen-on observation; background/OEM repetition remains pending |
| Exact-main GATT connection | Android connected, Target emitted Target Hello and ACK-gated multi-fragment Challenge, then exact-main `2.1.259` repeatedly reset with a stack-protection fault in task `nimble_host` | FAIL for exact-main local authentication; no proof/result/FSM/relay success |
| Root cause | ELF frames were about 2,736 bytes for output draining and 3,216 bytes for canonical JSON/MQTTS emission while the prebuilt NimBLE host task stack is 5,120 bytes. Both could execute from BLE callbacks | ROOT CAUSE CONFIRMED for the observed reset path |
| Stack-safe Target candidate | App-only USB flash of `2.1.260-test.g163610d` preserved bootloader, partitions, NVS, OTA data and fallback slot. It booted with Wi-Fi `192.168.35.19`, MQTTS, current ACL and GATT enabled; the same phone reached Target Hello/Challenge without a reset | PASS for the observed connection and reset non-recurrence; candidate is not exact-main signed OTA evidence |
| Candidate capacity | The candidate binary was 1,845,616 bytes and PlatformIO reported 1,780,006 bytes used in a 7,340,032-byte OTA slot (24.3%) | PASS with 5,560,026 bytes slot headroom |
| Android challenge stream | The installed bc9 APK subscribed to Challenge indications and also read the same characteristic. A single-frame read could interleave with indicated fragments sharing a message ID; the strict reassembler returned `MALFORMED_PROOF` | FAIL at Android transport framing, before proof/FSM/relay |
| Android correction candidate | Source now consumes Target Hello and Challenge only from the already-subscribed ordered indication mailbox and forbids a simultaneous Challenge read; focused source regression passed 11/11 and the focused JDK17 Android build/JUnit run completed 209 Gradle tasks successfully | PASS for local source/JVM coverage; hosted exact-toolchain CI, signed APK installation and physical proof/result remain pending |
| Hardened Target source build | Authentication control was separated from best-effort telemetry, callback-originated abort/advertising restart was moved to loopTask, and `esp32c6_personal_production` compiled with 1,780,268/7,340,032 bytes flash and 67,088/327,680 bytes RAM; `firmware.bin` was 1,845,984 bytes | PASS for local build/capacity only; these additional bytes were not yet installed |
| Home Assistant controls | Bridge availability remained online and reboot/open/OTA/config controls rendered enabled. OTA was exercised successfully; remote open was not invoked | PASS for availability and one OTA command; relay/open remains untested |

The physical target is currently running the USB stack-safe candidate so that
the deterministic reset can be tested without erasing Wi-Fi, ACL or OTA state.
The release Gate remains open until the same Target bytes and the corrected
Android transport are merged, CI-built, NAS-published, installed from exact
main, and one authenticated proof/result completes without a reboot. No relay
actuation or wall-install acceptance is claimed by this section.

## 2026-08-25 exact-main db37bc2 foreground evidence recovered from PR #132

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact source/artifacts | Runs `32777471683` and `32777471718` built and published exact main `db37bc2390efbf94bf1a9fca261834c3728606b5` as Target `2.1.262+main.gdb37bc2` and Android `1.0.0-gdb37bc2` / 19001 | PASS for exact historical identities |
| Target OTA/runtime | HA signed OTA installed/rebooted the Target; Wi-Fi `192.168.35.19`, MQTTS, current ACL and GATT returned | PASS for install/reboot/runtime; rollback and power loss not exercised |
| Android replacement | Production-signed APK was installed with `adb install -r` on SM-F966N, preserving package data, consent and AndroidKeyStore credential | PASS for same-signature replacement |
| Foreground local GATT | One foreground action-1 request completed service/indication/framed proof/result exchange; fresh health was `HEALTHY`, no failure/Target denial, 4,599 ms. HA independently recorded `AUTH_PENDING` 06:27:33, `ARMED` 06:27:36 and `IDLE` 06:28:35; Target did not reset | PASS for this historical foreground authenticated proof/result and FSM ARM |
| Physical boundary | No AJ-SR04T threshold, GPIO3 relay/contact, electrical, screen-off/OEM, rollback or power-loss measurement was captured | PENDING; no physical-open or wall-install claim |

Issue #133 later split the mobile manual button into action 2 immediate relay
and bound successful Result to the actual FSM transition. Consequently this
historical action-1 ARM evidence is not evidence for the current action-2 button
or pocket/background behavior.

## 2026-08-26 current a9 deployment boundary

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Target CI/NAS/install | Run `32872303874` published exact main `a9b68222f8c7d47a1ed36f4395c636f959bfb15d` as `2.1.266+main.ga9b6822`; 1,846,624-byte plaintext and 1,846,660-byte encrypted artifact fit a 7,340,032-byte slot at 25.16%, leaving 5,493,408 bytes. Signed OTA installed/rebooted it and Wi-Fi/MQTTS/ACL v147/GATT returned | PASS for exact Target publication and connected runtime |
| Android CI/NAS | Run `32872303799` published production-signed `1.0.0-ga9b6822` / 19801, 55,786,649 bytes, to primary/fallback NAS paths with HTTPS readback | PASS for artifact publication only; no phone installation |
| Current access E2E | Phone, AJ-SR04T and relay were not connected | PENDING action-2 manual button, pocket action-1, sensor and contact evidence |

## 2026-08-26 issue #133 manual local-open software candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Target action contract | Native host tests accept action 1 and 2, reject unsupported actions, and verify `RESULT OK` is not emitted when the application control gate rejects the transition | PASS for deterministic host logic |
| Target FSM | action 1 reaches `ARMED` with relay OFF; action 2 reaches `RELAY_HOLD` and invokes the relay callback immediately; pending/action rejection returns non-OK and cleanup | PASS for host callback/FSM behavior; no physical GPIO/contact evidence |
| Android action contract | `GattSessionEngine` signs the selected action into canonical byte 56 and proof wire byte 34; background worker passes action 1 and foreground manual executor passes action 2 | PASS for source/unit candidate; hosted Android CI pending |
| Manual UI truthfulness | WebView no longer treats queue acceptance as open success. It calls terminal `triggerLocalGattOpen` and displays success only after Target reason 0; an already enrolled credential has no per-tap backend status GET | PASS for source contract; no connected-phone timing evidence |
| ESP32-C6 build/capacity | `esp32c6_personal_production` compiled with 1,780,836/7,340,032 bytes flash (24.3%) and 67,088/327,680 bytes RAM (20.5%) | PASS for local build and dual-slot capacity headroom |

Phone, AJ-SR04T and physical relay were not connected during this candidate
test. Exact-main CI artifacts, NAS publication, Target OTA/install/reboot and
manual button-to-contact timing remain pending. The hands-free path is tracked
separately in issue #134.

## 2026-08-26 issue #134 pocket-approach software candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Activation wiring | Native GATT enable attempts the exact OS PendingIntent registration in the same control call; disable stops it, and health recomputes current permission/Bluetooth readiness | PASS for deterministic source/control wiring; OS registration survival requires a phone |
| Background dispatch | Android 12+ first presence work is expedited with `RUN_AS_NON_EXPEDITED_WORK_REQUEST` fallback, Android 8~11 retain regular work, no network constraint is added, and the worker signs only `ARM_FOR_SENSOR(1)` | PASS for Android source/unit contract; OEM scheduling latency is pending |
| Stale wake safety | Presence work older than 45 seconds terminates as non-retryable `PRESENCE_EXPIRED` before BLE ownership/proof; process clock rollback does not falsely expire new work | PASS for policy/JVM logic |
| End-to-end observability | Durable redacted state records presence-to-dispatch and presence-to-Target-ARMED separately from GATT session latency | PASS for codec/health/UI source; no connected measurement yet |
| Target sensor interlock | Native host regression holds relay OFF through `AUTH_PENDING -> ARMED`, then permits `RELAY_HOLD` only after a valid ultrasonic trigger; main loop samples only while `ARMED` at 100 ms intervals | PASS for deterministic Target host/source behavior; no AJ-SR04T/GPIO3 timing evidence |
| Focused local suite | Pocket source contract plus Target native host suite: 15/15; implementation/mobile contract suites: 21/21 | PASS for 36 local software tests; hosted Android/Target CI pending |

No phone, AJ-SR04T or physical relay was connected. Screen-off/pocket success
rate, OS delivery delay, presence-to-ARMED distribution, sensor threshold and
GPIO3 contact timing remain pending and must not be inferred from these tests.

## 2026-08-26 exact-main b6 action-2 abort and issue #143 candidate

| Test | Observed result | Verdict / boundary |
|---|---|---|
| Exact Target OTA | Run `32881540989` published exact main `b6cf6ec1a725e734d67df1ae8729e02f3ade0a9c` as `2.1.267+main.gb6cf6ec`. The connected a9 Target accepted the signed manifest, downloaded the 1,846,660-byte encrypted artifact, verified the inactive slot and rebooted into b6; Wi-Fi `192.168.35.19`, MQTTS, GATT and ACL v159 returned | PASS for signed install/reboot/current runtime; the retained OTA-data path again emitted no pending-health/valid-mark log, so rollback remains pending |
| Exact Android replacement | Run `32881541103` supplied a 55,786,649-byte production-signed APK. SHA-256 was `d0d3ae4b193b5a42e1003197019d865841d1f461ebf012bffab77ceff91e62f7`, signer SHA-256 matched the installed app, and embedded source was exact b6. `adb install -r` produced `1.0.0-gb6cf6ec` / 19901 while preserving first-install time, app data and AndroidKeyStore | PASS for exact identity and same-signature replacement |
| Main `문 열기` action 2 | Android connected, discovered the service and enabled Hello/Challenge/Result indications. Proof processing then reset the Target before any `RELAY_HOLD`, relay ON/OFF or successful Result; Android reported `PROOF_OUTCOME_UNCERTAIN` | FAIL; issue #143 release blocker |
| Crash decode | Physical trace reported `abort()` at `0x40801c75`; production-equivalent ELF mapped the call chain through `TargetAccessFsm::handleLocalManualOpen`, `ProtocolCore::processProof` and the relay callback. `relayOn()` reached `LOGF` while `GattServer::update()` still held the `core_mux` FreeRTOS critical section, and newlib aborted while acquiring its recursive stdout lock | ROOT CAUSE CONFIRMED |
| Issue #143 source candidate | The protocol/adapter serialization lock is a task-context `std::recursive_mutex`, so the synchronous Result-to-FSM action commit may safely reach GPIO, failsafe timer, diagnostics and logging while remaining serialized with NimBLE callbacks. Focused Hardwareless/pocket tests passed 16/16 | PASS for source/host regression only |
| ESP32-C6 candidate capacity | `esp32c6_personal_production` compiled successfully with 1,781,874/7,340,032 bytes flash (24.3%) and 67,088/327,680 bytes RAM (20.5%) | PASS for local build/capacity; exact CI/NAS publication, install and connected action-2 repetition remain pending |

The board-only setup proves the commanded GPIO/FSM path only when the serial
trace reaches it; it does not prove a relay contact or electrical load. Issue
#143 cannot close until the exact merged signed image completes terminal action
2 without reset and logs one relay command ON/OFF sequence. Physical contact,
sensor threshold and power behavior remain separate #54 Gates.
