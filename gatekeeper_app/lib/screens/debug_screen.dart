import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import '../services/ble_scanner.dart';
import '../services/error_logger.dart';
import '../services/foreground_service.dart';
import '../services/scan_diagnostics.dart';

class DebugScreen extends StatefulWidget {
  const DebugScreen({super.key, this.embedded = false});

  /// Hides this feature area's own AppBar when hosted by the unified settings
  /// screen. The embedded body retains an explicit refresh control.
  final bool embedded;

  @override
  State<DebugScreen> createState() => _DebugScreenState();
}

class _DebugScreenState extends State<DebugScreen> {
  final BleScanner _scanner = BleScanner();

  // Target 원격 튜닝 입력 변수
  int _selectedTxPower = 9; // dBm (-6, 0, 3, 9)
  double _tofDistanceCm = 50; // cm (5 ~ 200)
  double _durationMs = 60000; // ms (1000 ~ 60000)
  double _relayCooldownMs = 3000; // ms (1000 ~ 10000)

  // Target 현재 적용 상태 변수 (서버/Target 실제 반영 상태)
  int _appliedTxPower = 9;
  double _appliedTofDistanceCm = 50;
  double _appliedDurationMs = 60000;
  double _appliedRelayCooldownMs = 3000;
  String _lastSyncTimeStr = '미동기화';

  bool _isSending = false;
  bool _isFetching = false;
  String _targetResponseMsg = '';

  @override
  void initState() {
    super.initState();
    // 현재 서버/Target에 적용된 실시간 튜닝 설정값 로드
    _fetchAdminConfig();
  }

  @override
  void dispose() {
    super.dispose();
  }

  Future<void> _fetchAdminConfig() async {
    setState(() {
      _isFetching = true;
    });

    try {
      final url = Uri.parse('${_scanner.backendBaseUrl}/admin/config');
      final response = await http.get(url).timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data['result'] == 'success') {
          if (!mounted) return;
          setState(() {
            if (data['tx_power'] != null) {
              _selectedTxPower = data['tx_power'];
              _appliedTxPower = data['tx_power'];
            }
            if (data['tof_distance'] != null) {
              _tofDistanceCm = (data['tof_distance'] as num).toDouble();
              _appliedTofDistanceCm = _tofDistanceCm;
            }
            if (data['duration'] != null) {
              _durationMs = (data['duration'] as num).toDouble();
              _appliedDurationMs = _durationMs;
            }
            if (data['relay_cooldown'] != null) {
              _relayCooldownMs = (data['relay_cooldown'] as num).toDouble();
              _appliedRelayCooldownMs = _relayCooldownMs;
            }
            final now = DateTime.now();
            _lastSyncTimeStr =
                '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}:${now.second.toString().padLeft(2, '0')}';
            _targetResponseMsg =
                '🔄 최신 실시간 설정 동기화 완료 ($_lastSyncTimeStr)\n[적용 상태] Tx: ${_appliedTxPower}dBm | ToF: ${_appliedTofDistanceCm.round()}cm | Duration: ${(_appliedDurationMs / 1000).round()}s | Relay Cooldown: ${(_appliedRelayCooldownMs / 1000).toStringAsFixed(1)}s';
          });
        }
      }
    } catch (e) {
      debugPrint('[DebugScreen] _fetchAdminConfig 에러: $e');
    } finally {
      if (mounted) {
        setState(() {
          _isFetching = false;
        });
      }
    }
  }

  Future<void> _sendAdminConfig() async {
    if (!mounted) return;
    setState(() {
      _isSending = true;
      _targetResponseMsg = '전송 중...';
    });

    try {
      final url = Uri.parse('${_scanner.backendBaseUrl}/admin/config');
      final response = await http
          .post(
            url,
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'tx_power': _selectedTxPower,
              'distance_threshold': _tofDistanceCm.toInt(),
              'tof_distance': _tofDistanceCm.toInt(),
              'duration': _durationMs.toInt(),
              'relay_cooldown': _relayCooldownMs.toInt(),
            }),
          )
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final now = DateTime.now();

        final timeStr =
            '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}:${now.second.toString().padLeft(2, '0')}';
        if (!mounted) return;
        setState(() {
          _appliedTxPower = _selectedTxPower;
          _appliedTofDistanceCm = _tofDistanceCm;
          _appliedDurationMs = _durationMs;
          _appliedRelayCooldownMs = _relayCooldownMs;
          _lastSyncTimeStr = timeStr;
          _targetResponseMsg =
              '✅ Target 파라미터 NVS 영구 저장 & MQTT 2Way 동기화 완료! ($timeStr)\n[NVS 저장 상태] Tx: ${_appliedTxPower}dBm | ToF: ${_appliedTofDistanceCm.round()}cm | Duration: ${(_appliedDurationMs / 1000).round()}s | Relay Cooldown: ${(_appliedRelayCooldownMs / 1000).toStringAsFixed(1)}s';
        });
      } else {
        if (!mounted) return;
        setState(() {
          _targetResponseMsg =
              '❌ 실패 (HTTP ${response.statusCode}): ${response.body}';
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _targetResponseMsg = '🚨 통신 오류: $e';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSending = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF121212),
      appBar: widget.embedded
          ? null
          : AppBar(
              title: const Text('🔧 엔지니어 디버그 & 튜닝'),
              backgroundColor: const Color(0xFF1E1E1E),
              elevation: 0,
              actions: [_buildRefreshButton()],
            ),
      body: SafeArea(
        bottom: true,
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(16.0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (widget.embedded) ...[
                Align(
                  alignment: Alignment.centerRight,
                  child: _buildRefreshButton(),
                ),
                const SizedBox(height: 4),
              ],
              // ─── SECTION 1: 실시간 RSSI 모니터 ───────────────────
              _buildRssiMonitorCard(),

              const SizedBox(height: 16),

              // ─── SECTION 1-B: 스캔 진단 패널 ────────────────────
              _buildDiagnosticsCard(),

              const SizedBox(height: 16),

              // ─── SECTION 2: 로컬 파라미터 조절 UI ─────────────────
              _buildLocalConfigCard(),

              const SizedBox(height: 16),

              // ─── SECTION 3: Target 원격 제어 UI ─────────────────
              _buildTargetRemoteControlCard(),

              const SizedBox(height: 16),

              // ─── SECTION 4: 실시간 이벤트 & 에러 콘솔 UI ──────────────
              _buildAppLogConsoleCard(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildRefreshButton() {
    return IconButton(
      icon: _isFetching
          ? const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: Colors.cyanAccent,
              ),
            )
          : const Icon(Icons.refresh, color: Colors.cyanAccent),
      tooltip: '최신 튜닝 설정 새로고침',
      onPressed: _isFetching ? null : _fetchAdminConfig,
    );
  }

  Widget _buildRssiMonitorCard() {
    // P2-17: 예전에는 isBeaconConnected / packetCount 만 듣고 liveRssi 와
    // lastRssiUpdateTime 은 .value 로 직접 읽었다. 네 값이 항상 동시에
    // 갱신되는 덕에 우연히 동작했을 뿐, 하나라도 단독으로 바뀌면 화면이 굳는다.
    // 표시에 쓰는 모든 알림자를 병합해 듣는다.
    return AnimatedBuilder(
      animation: Listenable.merge([
        _scanner.isBeaconConnected,
        _scanner.liveRssi,
        _scanner.smoothedRssi,
        _scanner.lastRssiUpdateTime,
        _scanner.packetCount,
        _scanner.modeNotifier,
      ]),
      builder: (context, _) {
        final isConnected = _scanner.isBeaconConnected.value;
        final count = _scanner.packetCount.value;
        final rssi = isConnected ? _scanner.liveRssi.value : null;
        final smoothed = isConnected ? _scanner.smoothedRssi.value : null;
        final lastTime = _scanner.lastRssiUpdateTime.value;
        final String timeStr = (isConnected && lastTime != null)
            ? '${lastTime.hour.toString().padLeft(2, '0')}:${lastTime.minute.toString().padLeft(2, '0')}:${lastTime.second.toString().padLeft(2, '0')}.${(lastTime.millisecond ~/ 100)}'
            : '미수신 (연결 안됨)';

        Color badgeColor = Colors.grey;
        String badgeText = '🔴 신호 없음 (연결 안됨)';

        if (isConnected && rssi != null) {
          if (rssi >= -60) {
            badgeColor = Colors.green;
            badgeText = '🟢 매우 강함 (근접)';
          } else if (rssi >= -75) {
            badgeColor = Colors.blue;
            badgeText = '🔵 보통 (감지 범위)';
          } else {
            badgeColor = Colors.orange;
            badgeText = '🟠 약함 (경계)';
          }
        }

        final mode = _scanner.modeNotifier.value;
        final String detail = isConnected
            ? 'UUID: ${_scanner.targetBeaconUuid}\n'
                '수신 시각: $timeStr | 누적 패킷: $count개\n'
                '평활 RSSI(판정용): ${smoothed?.toStringAsFixed(1) ?? '-'} dBm | 모드: ${mode.label}'
            : 'Target 비콘 UUID (${_scanner.targetBeaconUuid}) 미수신 중...\n'
                '모드: ${mode.label} | 누적 패킷: $count개\n'
                '${mode == ScanMode.idle ? '구역 진입이 감지되면 자동으로 계측을 시작합니다.' : '신호를 기다리고 있습니다.'}';

        return Card(
          color: const Color(0xFF1E1E1E),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      '📡 실시간 비콘 RSSI 모니터',
                      style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: Colors.white),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: badgeColor.withValues(alpha: 0.2),
                        border: Border.all(color: badgeColor),
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Text(
                        badgeText,
                        style: TextStyle(
                            color: badgeColor,
                            fontSize: 12,
                            fontWeight: FontWeight.bold),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Text(
                  (isConnected && rssi != null) ? '$rssi dBm' : '연결 안됨',
                  style: TextStyle(
                    fontSize: (isConnected && rssi != null) ? 48 : 36,
                    fontWeight: FontWeight.bold,
                    color: (isConnected && rssi != null)
                        ? Colors.cyanAccent
                        : Colors.redAccent,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  detail,
                  style: const TextStyle(fontSize: 12, color: Colors.grey),
                  textAlign: TextAlign.center,
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  /// 스캔이 왜 동작하지 않는지를 앱 안에서 확인할 수 있는 진단 패널
  /// (issue.md P2-19).
  Widget _buildDiagnosticsCard() {
    return ValueListenableBuilder<ScanDiagnostics>(
      valueListenable: _scanner.diagnostics,
      builder: (context, d, _) {
        final blockers = d.blockingReasons;
        final warnings = d.warningReasons;

        return Card(
          color: const Color(0xFF1E1E1E),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          child: Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      '🩺 스캔 진단',
                      style: TextStyle(
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: Colors.white),
                    ),
                    IconButton(
                      icon: const Icon(Icons.refresh,
                          size: 18, color: Colors.cyanAccent),
                      tooltip: '서비스 상태는 5초마다 자동 갱신됩니다',
                      onPressed: () {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text('서비스 진단 상태는 5초마다 자동 갱신됩니다.'),
                          ),
                        );
                      },
                    ),
                  ],
                ),
                if (blockers.isNotEmpty)
                  _buildReasonBox(
                    title: '스캔 불가 — 아래를 해결해야 합니다',
                    reasons: blockers,
                    color: Colors.redAccent,
                  ),
                if (warnings.isNotEmpty)
                  _buildReasonBox(
                    title: '주의 — 백그라운드/화면 OFF 신뢰성 저하',
                    reasons: warnings,
                    color: Colors.amberAccent,
                  ),
                if (blockers.isEmpty && warnings.isEmpty)
                  _buildReasonBox(
                    title: '모든 전제조건 충족',
                    reasons: const ['스캔에 필요한 권한과 OS 스위치가 모두 정상입니다.'],
                    color: Colors.greenAccent,
                  ),
                const SizedBox(height: 12),
                _buildCheckRow('위치 권한', d.locationWhenInUse, blocking: true),
                _buildCheckRow('백그라운드 위치 권한', d.locationAlways),
                if (d.requiresRuntimeBluetoothPermission) ...[
                  _buildCheckRow('BLUETOOTH_SCAN 권한', d.bluetoothScan,
                      blocking: true),
                  _buildCheckRow('BLUETOOTH_CONNECT 권한', d.bluetoothConnect),
                ],
                _buildCheckRow('알림 권한', d.notification),
                _buildCheckRow('블루투스 ON', d.bluetoothOn, blocking: true),
                _buildCheckRow('위치 서비스(GPS) ON', d.locationServicesOn,
                    blocking: true),
                _buildCheckRow('배터리 최적화 예외', d.ignoringBatteryOptimizations),
                ValueListenableBuilder<ForegroundServiceHealth>(
                  valueListenable: ForegroundServiceManager.health,
                  builder: (context, health, _) => _buildCheckRow(
                    '포그라운드 서비스 실행',
                    health.running ?? d.foregroundServiceRunning,
                  ),
                ),
                ValueListenableBuilder<ForegroundServiceHealth>(
                  valueListenable: ForegroundServiceManager.health,
                  builder: (context, health, _) => _buildInfoRow(
                    '서비스·알림 채널 상태',
                    health.detail,
                  ),
                ),
                _buildCheckRow(
                    '화면 OFF 대응 스캔 설정', d.backgroundScanTuningApplied),
                const Divider(color: Colors.white10),
                _buildCheckRow('monitoring 구독', d.monitoringSubscribed,
                    blocking: true),
                _buildCheckRow('ranging 구독', d.rangingSubscribed),
                const SizedBox(height: 8),
                _buildInfoRow(
                    '현재 모드', d.mode.label + (d.debugForced ? ' · 디버그 강제' : '')),
                _buildInfoRow('Target UUID', d.targetBeaconUuid),
                _buildInfoRow('Android SDK',
                    d.androidSdkInt == 0 ? '미확인' : '${d.androidSdkInt}'),
                _buildInfoRow('마지막 구역 진입', _formatTime(d.lastEnterRegionAt)),
                _buildInfoRow('마지막 구역 이탈', _formatTime(d.lastExitRegionAt)),
                _buildInfoRow(
                    '마지막 ranging 콜백', _formatTime(d.lastRangingCallbackAt)),
                _buildInfoRow('ranging 콜백 누적', '${d.rangingCallbackCount}회'),
                _buildInfoRow(
                  '마지막 Pre-arm',
                  d.lastPrearmAt == null
                      ? '없음'
                      : '${_formatTime(d.lastPrearmAt)} · '
                          '${d.lastPrearmStatusCode ?? '-'} · ${d.lastPrearmMessage ?? '-'}',
                ),
                if (d.lastScanError != null)
                  _buildInfoRow('마지막 스캔 오류', d.lastScanError!),
                _buildInfoRow('진단 시각', _formatTime(d.updatedAt)),
              ],
            ),
          ),
        );
      },
    );
  }

  Widget _buildReasonBox({
    required String title,
    required List<String> reasons,
    required Color color,
  }) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        border: Border.all(color: color.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: TextStyle(
                fontSize: 12, fontWeight: FontWeight.bold, color: color),
          ),
          const SizedBox(height: 4),
          ...reasons.map(
            (r) => Text('· $r',
                style: const TextStyle(fontSize: 11, color: Colors.white70)),
          ),
        ],
      ),
    );
  }

  Widget _buildCheckRow(String label, bool ok, {bool blocking = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        children: [
          Icon(
            ok
                ? Icons.check_circle
                : (blocking ? Icons.cancel : Icons.warning_amber_rounded),
            size: 14,
            color: ok
                ? Colors.greenAccent
                : (blocking ? Colors.redAccent : Colors.amberAccent),
          ),
          const SizedBox(width: 6),
          Expanded(
            child: Text(label,
                style: const TextStyle(fontSize: 12, color: Colors.white70)),
          ),
          Text(
            ok ? 'OK' : (blocking ? '차단' : '경고'),
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.bold,
              color: ok
                  ? Colors.greenAccent
                  : (blocking ? Colors.redAccent : Colors.amberAccent),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInfoRow(String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 130,
            child: Text(label,
                style: const TextStyle(fontSize: 11, color: Colors.grey)),
          ),
          Expanded(
            child: SelectableText(
              value,
              style: const TextStyle(fontSize: 11, color: Colors.white70),
            ),
          ),
        ],
      ),
    );
  }

  static String _formatTime(DateTime? time) {
    if (time == null || time.millisecondsSinceEpoch == 0) return '없음';
    return '${time.hour.toString().padLeft(2, '0')}:'
        '${time.minute.toString().padLeft(2, '0')}:'
        '${time.second.toString().padLeft(2, '0')}';
  }

  Widget _buildLocalConfigCard() {
    return Card(
      color: const Color(0xFF1E1E1E),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '📱 앱 로컬 동작 파라미터 조절',
              style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                  color: Colors.white),
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('동적 RSSI Threshold:',
                    style: TextStyle(color: Colors.white70)),
                Text(
                  '${_scanner.rssiThreshold} dBm',
                  style: const TextStyle(
                      color: Colors.cyanAccent, fontWeight: FontWeight.bold),
                ),
              ],
            ),
            Slider(
              value: _scanner.rssiThreshold.clamp(-100, -30).toDouble(),
              min: -100.0,
              max: -30.0,
              divisions: 70,
              activeColor: Colors.cyan,
              label: '${_scanner.rssiThreshold} dBm',
              onChanged: (val) {
                setState(() {
                  _scanner.setRssiThreshold(val.round());
                });
              },
            ),
            const Divider(color: Colors.white10),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('모바일 앱 비콘 API 쿨다운:',
                    style: TextStyle(color: Colors.white70)),
                Text(
                  '${_scanner.cooldownSeconds} 초',
                  style: const TextStyle(
                      color: Colors.amberAccent, fontWeight: FontWeight.bold),
                ),
              ],
            ),
            Slider(
              // 원격 설정(APP_COOLDOWN_SEC)이 슬라이더 범위를 벗어나면
              // Slider 가 assert 로 죽으므로 클램프한다.
              value: _scanner.cooldownSeconds.clamp(1, 30).toDouble(),
              min: 1.0,
              max: 30.0,
              divisions: 29,
              activeColor: Colors.amber.shade700,
              label: '${_scanner.cooldownSeconds} 초',
              onChanged: (val) {
                setState(() {
                  _scanner.setCooldownSeconds(val.round());
                });
              },
            ),
            const Divider(color: Colors.white10),
            CheckboxListTile(
              title: const Text('스마트 쿨다운 무시 (Ignore Cooldown)',
                  style: TextStyle(color: Colors.white, fontSize: 14)),
              subtitle: const Text('체크 시 문 열기 직후에도 쿨다운 없이 비콘 API 연타 가능',
                  style: TextStyle(color: Colors.grey, fontSize: 12)),
              value: _scanner.ignoreCooldown,
              activeColor: Colors.amber.shade800,
              onChanged: (val) {
                setState(() {
                  _scanner.setIgnoreCooldown(val ?? false);
                });
              },
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildTargetRemoteControlCard() {
    return Card(
      color: const Color(0xFF1E1E1E),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '🎯 Target (ESP32-C6) 원격 튜닝',
              style: TextStyle(
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                  color: Colors.white),
            ),
            const SizedBox(height: 12),
            _buildActiveTargetStatusBox(),
            const SizedBox(height: 16),
            const SizedBox(height: 16),
            const Text('1. BLE Tx Power 출력:',
                style: TextStyle(color: Colors.white70, fontSize: 13)),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: [-6, 0, 3, 9].map((pwr) {
                final isSelected = _selectedTxPower == pwr;
                return ChoiceChip(
                  label: Text('$pwr dBm'),
                  selected: isSelected,
                  selectedColor: Colors.cyan,
                  backgroundColor: Colors.grey.shade800,
                  labelStyle: TextStyle(
                      color: isSelected ? Colors.black : Colors.white),
                  onSelected: (selected) {
                    if (selected) {
                      setState(() {
                        _selectedTxPower = pwr;
                      });
                    }
                  },
                );
              }).toList(),
            ),
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('2. 초음파 감지 기준 거리:',
                    style: TextStyle(color: Colors.white70, fontSize: 13)),
                Text('${_tofDistanceCm.round()} cm',
                    style: const TextStyle(
                        color: Colors.cyanAccent, fontWeight: FontWeight.bold)),
              ],
            ),
            Slider(
              value: _tofDistanceCm < 20 ? 20 : _tofDistanceCm,
              min: 20,
              max: 150,
              divisions: 26,
              activeColor: Colors.cyan,
              label: '${_tofDistanceCm.round()} cm',
              onChanged: (val) {
                setState(() {
                  _tofDistanceCm = val;
                });
              },
            ),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('3. Pre-arm 무장 유지 시간:',
                    style: TextStyle(color: Colors.white70, fontSize: 13)),
                Text(
                    '${(_durationMs / 1000).toStringAsFixed(1)} 초 (${_durationMs.round()} ms)',
                    style: const TextStyle(
                        color: Colors.cyanAccent, fontWeight: FontWeight.bold)),
              ],
            ),
            Slider(
              value: _durationMs,
              min: 3000,
              max: 60000,
              divisions: 57,
              activeColor: Colors.cyan,
              label: '${(_durationMs / 1000).round()}초',
              onChanged: (val) {
                setState(() {
                  _durationMs = val;
                });
              },
            ),
            const SizedBox(height: 8),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('4. Target 릴레이 쿨다운:',
                    style: TextStyle(color: Colors.white70, fontSize: 13)),
                Text(
                    '${(_relayCooldownMs / 1000).toStringAsFixed(1)} 초 (${_relayCooldownMs.round()} ms)',
                    style: const TextStyle(
                        color: Colors.cyanAccent, fontWeight: FontWeight.bold)),
              ],
            ),
            Slider(
              value: _relayCooldownMs,
              min: 1000,
              max: 10000,
              divisions: 18,
              activeColor: Colors.cyan,
              label: '${(_relayCooldownMs / 1000).toStringAsFixed(1)}초',
              onChanged: (val) {
                setState(() {
                  _relayCooldownMs = val;
                });
              },
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: _isFetching ? null : _fetchAdminConfig,
                    icon: _isFetching
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: Colors.cyan))
                        : const Icon(Icons.sync, color: Colors.cyan),
                    label: const Text('현재 설정 불러오기',
                        style: TextStyle(
                            color: Colors.cyan,
                            fontSize: 13,
                            fontWeight: FontWeight.bold)),
                    style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: Colors.cyan),
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8)),
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: _isSending ? null : _sendAdminConfig,
                    icon: _isSending
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                                strokeWidth: 2, color: Colors.black))
                        : const Icon(Icons.send),
                    label: const Text('Target 파라미터 전송',
                        style: TextStyle(
                            fontSize: 13, fontWeight: FontWeight.bold)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.cyan,
                      foregroundColor: Colors.black,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(8)),
                    ),
                  ),
                ),
              ],
            ),
            if (_targetResponseMsg.isNotEmpty) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: Colors.black38,
                  borderRadius: BorderRadius.circular(8),
                  border: Border.all(color: Colors.white24),
                ),
                child: Text(
                  _targetResponseMsg,
                  style: const TextStyle(fontSize: 13, color: Colors.white),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildActiveTargetStatusBox() {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.black45,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: Colors.cyan.withValues(alpha: 0.3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Row(
                children: [
                  Icon(Icons.check_circle_outline,
                      color: Colors.greenAccent, size: 16),
                  SizedBox(width: 6),
                  Text(
                    'Target 현재 적용 상태 (Live Applied)',
                    style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.bold,
                        color: Colors.cyanAccent),
                  ),
                ],
              ),
              Text(
                _lastSyncTimeStr,
                style: const TextStyle(fontSize: 11, color: Colors.grey),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceAround,
            children: [
              _buildActiveParamItem(
                  'Tx Power', '$_appliedTxPower dBm', Colors.amberAccent),
              Container(width: 1, height: 28, color: Colors.white12),
              _buildActiveParamItem('ToF 거리',
                  '${_appliedTofDistanceCm.round()} cm', Colors.greenAccent),
              Container(width: 1, height: 28, color: Colors.white12),
              _buildActiveParamItem(
                  'Pre-arm 시간',
                  '${(_appliedDurationMs / 1000).round()} 초',
                  Colors.cyanAccent),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildActiveParamItem(String label, String value, Color color) {
    return Column(
      children: [
        Text(label, style: const TextStyle(fontSize: 11, color: Colors.grey)),
        const SizedBox(height: 3),
        Text(value,
            style: TextStyle(
                fontSize: 15, fontWeight: FontWeight.bold, color: color)),
      ],
    );
  }

  Widget _buildAppLogConsoleCard() {
    return Card(
      color: const Color(0xFF1E1E1E),
      margin: const EdgeInsets.symmetric(vertical: 8),
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Row(
                  children: [
                    Icon(Icons.terminal, color: Colors.greenAccent, size: 20),
                    SizedBox(width: 8),
                    Text(
                      '실시간 앱 이벤트 & 에러 로그 (Live Console)',
                      style: TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.bold,
                        color: Colors.white,
                      ),
                    ),
                  ],
                ),
                TextButton(
                  onPressed: () => AppErrorLogger().clearLogs(),
                  child: const Text('클리어',
                      style: TextStyle(color: Colors.redAccent, fontSize: 12)),
                ),
              ],
            ),
            const SizedBox(height: 10),
            ValueListenableBuilder<List<String>>(
              valueListenable: AppErrorLogger().logs,
              builder: (context, logList, _) {
                if (logList.isEmpty) {
                  return Container(
                    height: 120,
                    width: double.infinity,
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: Colors.black45,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: Colors.white12),
                    ),
                    child: const Text(
                      '기록된 로그 및 에러가 없습니다.',
                      style: TextStyle(color: Colors.grey, fontSize: 13),
                    ),
                  );
                }
                return Container(
                  height: 180,
                  width: double.infinity,
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: Colors.black,
                    borderRadius: BorderRadius.circular(8),
                    border: Border.all(
                        color: Colors.greenAccent.withValues(alpha: 0.3)),
                  ),
                  child: ListView.builder(
                    itemCount: logList.length,
                    reverse: true,
                    itemBuilder: (context, index) {
                      final item = logList[logList.length - 1 - index];
                      final isError = item.contains('⚠️') ||
                          item.contains('오류') ||
                          item.contains('Error');
                      return SelectableText(
                        item,
                        style: TextStyle(
                          fontSize: 11,
                          fontFamily: 'monospace',
                          color: isError
                              ? Colors.redAccent
                              : Colors.lightGreenAccent,
                        ),
                      );
                    },
                  ),
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}
