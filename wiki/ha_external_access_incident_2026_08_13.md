# Home Assistant 외부 접속 502 incident — 2026-08-13

> 상태: 2026-08-13 장애 기록. 2026-08-24 Home Assistant upstream과 Target telemetry 복구를 확인했다.

## 1. 당시 결론

2026-08-13의 외부 접속 실패는 공인 IP 변경이나 Synology DDNS 갱신 실패가 아니었다. DDNS A record와 당시 회선의 egress 공인 IP가 일치했고, 서로 다른 외부 지역의 probe가 같은 nginx endpoint까지 도달했지만 모두 HTTP `502 Bad Gateway`를 받았다.

NAS는 LAN에서 응답했고 외부 reverse-proxy listener도 열려 있었지만 Home Assistant 기본 upstream인 TCP 8123은 닫혀 있었다. 따라서 당시 원인은 공유기나 DDNS가 아니라 Home Assistant service/container 정지 또는 upstream listen 실패로 격리됐다. 운영 주소와 NAS volume의 구체적인 host 경로는 공개 위키에 기록하지 않는다.

## 2. 2026-08-13 관측 증거

| 경계 | 결과 | 판정 |
|---|---|---|
| System/Cloudflare/Google DNS | 동일 A record | DNS 전파 불일치 아님 |
| 회선 공인 IP | 두 독립 조회에서 DDNS A record와 동일 | 공인 IP 변경 아님 |
| 외부 HTTP probe 3개 지역 | 모두 nginx `502 Bad Gateway` | 단일 모바일 통신사 또는 hairpin 문제 아님 |
| NAS LAN 경로 | ping/ARP 정상 | NAS 자체 또는 LAN 주소 변경 아님 |
| reverse-proxy listener | open, nginx 502 | 외부 ingress가 NAS nginx까지 도달 |
| NAS TCP 8123 | closed | HA upstream service/listener 장애 유력 |
| 별도 backend endpoint | nginx 응답 | NAS nginx 전체 장애 아님 |
| DSM 관리 endpoint | HTTP 200 | DSM 자체는 동작 중 |

## 3. 안전한 복구 순서

1. DSM Container Manager에서 Home Assistant container 상태와 최근 종료 시각을 확인한다.
2. 중지 상태면 종료 원인, volume mount와 설정 오류를 먼저 확인한 뒤 Home Assistant container만 한 번 시작한다.
3. 실행 중인데 8123이 닫혀 있으면 startup log의 configuration, database, permission 오류를 확인한다.
4. NAS LAN의 TCP 8123 listener와 Home Assistant HTTP 응답을 확인한다.
5. 외부 reverse-proxy endpoint가 502 대신 Home Assistant 응답을 주는지 확인한다.
6. 마지막으로 휴대폰 Wi-Fi를 끈 이동통신망에서 접속을 확인한다.

이 경계가 확인되기 전에는 공유기 포트 범위, DDNS 주소 또는 nginx reverse-proxy 규칙을 변경하지 않는다. HA upstream 복구 전에 주변 설정을 바꾸면 원인을 추가할 수 있다.

## 4. DSM 확인 결과

사용자가 DSM Container Manager에서 Home Assistant container가 실제 중지 상태였음을 확인했다. 화면의 `met.no` weather API timeout과 과거 Android Chrome frontend `Suspend promise not set` 예외는 각각 외부 날씨 통합과 브라우저 UI 오류이며, container 종료 원인을 증명하지 않았다.

container를 한 번 수동 시작한 뒤 startup log와 8123 listen을 확인하고, 정상 기동이 확인된 경우에만 DSM 자동 재시작 정책을 활성화하는 순서를 선택했다. 즉시 다시 중지되면 반복 재시작 대신 종료 직전 log, exit code, NAS OOM, `/config` volume과 `configuration.yaml` 검증을 우선한다.

## 5. Computer Use 확인

2026-08-13에 DSM Container Manager 화면을 읽기 전용으로 확인했다. `homeassistant` container는 중지 상태였고 시작 버튼이 활성화되어 있었다. 일반 탭에서 공식 Home Assistant image, host network, `/config` volume과 자동 재시작 비활성 상태를 확인했다.

같은 시점에 NAS LAN의 TCP 8123은 closed, reverse-proxy listener는 open, 외부 endpoint는 HTTP 502였다. 이는 당시 장애가 DDNS나 공유기 포트 전달보다 중지된 HA upstream과 자동 복구 비활성 상태로 설명됨을 지지했다.

## 6. 2026-08-24 복구 상태

2026-08-24에는 Home Assistant upstream과 외부 reverse-proxy 응답이 복구됐다. SmartGatekeeper Target의 15개 read-only entity가 모두 available이었고, firmware, RSSI와 uptime이 실시간으로 갱신됐다. 따라서 이 문서는 현재 장애 경보가 아니라 2026-08-13의 원인 격리와 안전한 복구 순서를 보존하는 역사적 incident 기록이다.
