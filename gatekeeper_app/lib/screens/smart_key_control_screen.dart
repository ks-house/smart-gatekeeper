import 'dart:async';

import 'package:flutter/material.dart';
import '../services/commercial_models.dart';
import '../services/device_id_service.dart';
import '../services/feature_flag_service.dart';
import '../services/local_gatt_enrollment_service.dart';
import '../services/mobile_activity_store.dart';
import '../services/native_gatt_worker_health.dart';
import '../services/update_checker.dart';

class SmartKeyControlScreen extends StatefulWidget {
  const SmartKeyControlScreen({super.key, this.embedded = false});

  /// Hides this feature area's own AppBar when hosted by the unified settings
  /// screen. Keeping the default preserves direct-route compatibility.
  final bool embedded;

  @override
  State<SmartKeyControlScreen> createState() => _SmartKeyControlScreenState();
}

class _SmartKeyControlScreenState extends State<SmartKeyControlScreen> {
  final FeatureFlagService _flagService = FeatureFlagService();
  final NativeGattWorkerHealthBridge _healthBridge =
      NativeGattWorkerHealthBridge();
  final LocalGattEnrollmentService _enrollmentService =
      LocalGattEnrollmentService();
  final UpdateChecker _updateChecker = UpdateChecker();

  bool _loading = true;
  bool _isRetrying = false;
  bool _liveRefreshInFlight = false;
  NativeGattWorkerHealth? _workerHealth;
  String? _deviceId;
  String _retryMessage = '';
  Timer? _liveStatusTimer;

  @override
  void initState() {
    super.initState();
    _loadAllState();
    _liveStatusTimer = Timer.periodic(
      const Duration(seconds: 1),
      (_) => _refreshLiveWorkerHealth(),
    );
  }

  @override
  void dispose() {
    _liveStatusTimer?.cancel();
    super.dispose();
  }

  Future<void> _refreshLiveWorkerHealth() async {
    if (_liveRefreshInFlight || !mounted) return;
    _liveRefreshInFlight = true;
    try {
      final health = await _healthBridge.read();
      if (mounted) setState(() => _workerHealth = health);
    } catch (_) {
      // Keep the last durable snapshot visible during a transient bridge error.
    } finally {
      _liveRefreshInFlight = false;
    }
  }

  String _twoDigits(int value) => value.toString().padLeft(2, '0');

  String _detectionTime(TargetDetectionSummary detection) {
    final value = detection.receivedAt.toLocal();
    return '${_twoDigits(value.hour)}:${_twoDigits(value.minute)}:'
        '${_twoDigits(value.second)}';
  }

  String _detectionAge(TargetDetectionSummary detection) {
    final elapsed = DateTime.now().difference(detection.receivedAt);
    if (elapsed.isNegative || elapsed.inSeconds < 1) return '방금';
    if (elapsed.inMinutes < 1) return '${elapsed.inSeconds}초 전';
    if (elapsed.inHours < 1) return '${elapsed.inMinutes}분 전';
    return '${elapsed.inHours}시간 전';
  }

  String _detectionLabel(TargetDetectionStage stage) {
    switch (stage) {
      case TargetDetectionStage.waiting:
        return 'Target 감지 대기 중';
      case TargetDetectionStage.detected:
        return 'Target 감지됨';
      case TargetDetectionStage.authenticating:
        return 'Target 감지 · 인증 진행 중';
      case TargetDetectionStage.armed:
        return 'Target 인증 완료 · 센서 대기(ARMED)';
      case TargetDetectionStage.failed:
        return 'Target 감지/인증 실패';
      case TargetDetectionStage.disabled:
        return 'Target 감지 · 자동 인증 비활성';
    }
  }

  Color _detectionColor(TargetDetectionStage stage) {
    switch (stage) {
      case TargetDetectionStage.armed:
        return Colors.greenAccent;
      case TargetDetectionStage.detected:
      case TargetDetectionStage.authenticating:
        return Colors.cyanAccent;
      case TargetDetectionStage.failed:
        return Colors.redAccent;
      case TargetDetectionStage.disabled:
        return Colors.orangeAccent;
      case TargetDetectionStage.waiting:
        return Colors.white70;
    }
  }

  Future<void> _loadAllState() async {
    setState(() => _loading = true);
    _deviceId = await DeviceIdService.getDeviceId();
    await _flagService.loadFlags();
    try {
      _workerHealth = await _healthBridge.read();
      if (_workerHealth!.featureEnabled && _flagService.enableLegacyPrearm) {
        await _flagService.updateFlags(
          legacyPrearm: false,
          killSwitch: _flagService.remoteKillSwitch,
        );
      }
    } catch (_) {
      _workerHealth = null;
    }
    if (mounted) {
      setState(() => _loading = false);
    }
  }

  Future<void> _setNativeGattEnabled(bool enabled) async {
    late final bool accepted;
    late final String reason;
    if (enabled) {
      final enrollment = await _enrollmentService.ensureEnrolledAndEnabled();
      accepted = enrollment.accepted;
      reason = enrollment.reason;
    } else {
      final result = await _healthBridge.setLocalGattEnabled(false);
      accepted = result['accepted'] == true;
      reason = result['reason']?.toString() ?? 'NATIVE_UNAVAILABLE';
    }
    if (accepted && enabled && _flagService.enableLegacyPrearm) {
      await _flagService.updateFlags(
        legacyPrearm: false,
        killSwitch: _flagService.remoteKillSwitch,
      );
    }
    await _loadAllState();
    if (mounted && !accepted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Local GATT setting failed: $reason')),
      );
    }
  }

  Future<void> _triggerManualOpen() async {
    if (_flagService.remoteKillSwitch) {
      setState(() {
        _retryMessage = '⚠️ Remote Kill-Switch가 활성화되어 있어 수동 개방이 차단되었습니다.';
      });
      return;
    }

    setState(() {
      _isRetrying = true;
      _retryMessage = '⚡ Local GATT 자격 및 Target ACL 확인 중...';
    });

    final enrollment = await _enrollmentService.ensureEnrolledAndEnabled();
    if (!enrollment.accepted) {
      if (mounted) {
        setState(() {
          _isRetrying = false;
          _retryMessage = '⚠️ 수동 출입 준비 실패: ${enrollment.reason}';
        });
      }
      return;
    }

    final result = await _healthBridge.triggerLocalGattOpen();
    final outcome = ManualOpenOutcome.fromNative(result);
    try {
      await MobileActivityStore().recordManualOpenResult(result);
    } catch (_) {
      // A local timeline write failure must not hide the terminal result.
    }
    final latency = outcome.latencyMs == null
        ? ''
        : ' (${outcome.latencyMs!.toString()}ms)';
    try {
      _workerHealth = await _healthBridge.read();
    } catch (_) {
      _workerHealth = null;
    }

    if (mounted) {
      setState(() {
        _isRetrying = false;
        _retryMessage = switch (outcome.state) {
          ManualOpenState.commandExecuted =>
            '✅ 개방 명령 실행 완료$latency\n실제 문 열림은 별도 확인이 필요합니다.',
          ManualOpenState.outcomeUnknown =>
            '⚠️ 개방 결과 확인 필요: ${outcome.reason}\n자동 재시도하지 마세요.',
          ManualOpenState.failed => '⚠️ 개방 명령 실패: ${outcome.reason}',
        };
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF121212),
      appBar: widget.embedded
          ? null
          : AppBar(
              title: const Text('Smart Key 대시보드 및 로컬 제어'),
              backgroundColor: const Color(0xFF1E1E1E),
            ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: _loadAllState,
              child: SingleChildScrollView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // 1. 1-Tap terminal action-2 Local GATT open section
                    Card(
                      color: const Color(0xFF1E293B),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                        side: BorderSide(
                          color: _flagService.remoteKillSwitch
                              ? Colors.red
                              : Colors.cyanAccent,
                          width: 1.5,
                        ),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          children: [
                            const Text(
                              '⚡ 수동 로컬 출입 제어',
                              style: TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.bold,
                                color: Colors.white,
                              ),
                            ),
                            const SizedBox(height: 8),
                            const Text(
                              '자동 Wake 또는 BLE 스캔 차단 시 1-Tap으로 수동 Local GATT 인증을 시도합니다.',
                              textAlign: TextAlign.center,
                              style: TextStyle(
                                  color: Colors.white70, fontSize: 12),
                            ),
                            const SizedBox(height: 16),
                            SizedBox(
                              width: double.infinity,
                              height: 52,
                              child: ElevatedButton.icon(
                                style: ElevatedButton.styleFrom(
                                  backgroundColor: _flagService.remoteKillSwitch
                                      ? Colors.grey
                                      : Colors.cyan,
                                  foregroundColor: Colors.black,
                                  shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(8),
                                  ),
                                ),
                                onPressed:
                                    _isRetrying ? null : _triggerManualOpen,
                                icon: _isRetrying
                                    ? const SizedBox(
                                        width: 20,
                                        height: 20,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                          color: Colors.black,
                                        ),
                                      )
                                    : const Icon(Icons.bolt, size: 28),
                                label: Text(
                                  _isRetrying ? '요청 처리 중...' : '1-Tap 수동 로컬 개방',
                                  style: const TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                            ),
                            if (_retryMessage.isNotEmpty) ...[
                              const SizedBox(height: 12),
                              Text(
                                _retryMessage,
                                textAlign: TextAlign.center,
                                style: const TextStyle(
                                  color: Colors.amberAccent,
                                  fontWeight: FontWeight.w600,
                                  fontSize: 13,
                                ),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // 2. Native-authoritative credential and Target ACL card
                    Card(
                      color: const Color(0xFF1E1E1E),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                const Text(
                                  '🔑 Local GATT 자격 상태',
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                    color: Colors.white,
                                  ),
                                ),
                                _buildCredentialStatusBadge(_workerHealth),
                              ],
                            ),
                            const Divider(height: 24, color: Colors.white24),
                            Text('Device ID: ${_deviceId ?? "불러오는 중..."}',
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 12)),
                            const SizedBox(height: 4),
                            Text('기기 키: ${_credentialLabel(_workerHealth)}',
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 12)),
                            const SizedBox(height: 4),
                            Text(
                              'Target ACL: ${_targetAclLabel(_workerHealth)}',
                              style: const TextStyle(
                                  color: Colors.white70, fontSize: 12),
                            ),
                            const SizedBox(height: 8),
                            const Text(
                              'Tenant 승인은 Backend가 관리합니다. 이 화면은 로컬 저장값으로 승인 상태를 추정하지 않습니다.',
                              style: TextStyle(
                                color: Colors.white54,
                                fontSize: 11,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // 3. Real-time privacy-safe Target detection card
                    Builder(builder: (context) {
                      final detection = _workerHealth?.latestDetection;
                      final stage = _workerHealth?.detectionStage ??
                          TargetDetectionStage.waiting;
                      return Card(
                        color: const Color(0xFF102A43),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                          side: BorderSide(
                            color: _detectionColor(stage),
                            width: 1.5,
                          ),
                        ),
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text(
                                '📡 Target 실시간 감지',
                                style: TextStyle(
                                  fontSize: 17,
                                  fontWeight: FontWeight.bold,
                                  color: Colors.white,
                                ),
                              ),
                              const SizedBox(height: 10),
                              Text(
                                _detectionLabel(stage),
                                key: const Key('target-detection-stage'),
                                style: TextStyle(
                                  color: _detectionColor(stage),
                                  fontSize: 16,
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              const SizedBox(height: 8),
                              if (detection != null) ...[
                                Text(
                                  '최근 감지: ${_detectionTime(detection)} '
                                  '(${_detectionAge(detection)})',
                                  style: const TextStyle(color: Colors.white70),
                                ),
                                Text(
                                  '신호: ${detection.strongestRssi != null ? '${detection.strongestRssi} dBm' : '측정 없음'} · '
                                  '화면: ${detection.screenInteractive ? 'ON' : 'OFF'}',
                                  style: const TextStyle(color: Colors.white70),
                                ),
                                Text(
                                  '결과: ${_workerHealth?.lastSession?['state'] ?? 'DETECTED'} · '
                                  '${_workerHealth?.lastPresenceToArmedMs != null ? 'ARMED ${_workerHealth!.lastPresenceToArmedMs} ms' : 'ARMED 미확인'}',
                                  style: const TextStyle(color: Colors.white70),
                                ),
                              ] else
                                const Text(
                                  '등록된 Target 광고를 기다리고 있습니다.',
                                  style: TextStyle(color: Colors.white70),
                                ),
                              const SizedBox(height: 8),
                              const Text(
                                '1초마다 자동 갱신하며 오래된 감지는 대기 상태로 전환합니다. '
                                'BLE 주소와 credential은 표시하지 않습니다.',
                                style: TextStyle(
                                  color: Colors.white54,
                                  fontSize: 11,
                                ),
                              ),
                            ],
                          ),
                        ),
                      );
                    }),
                    const SizedBox(height: 16),

                    // 4. Native GATT Worker Health Card
                    Card(
                      color: const Color(0xFF1E1E1E),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              mainAxisAlignment: MainAxisAlignment.spaceBetween,
                              children: [
                                const Text(
                                  '🛡️ Native Worker Health',
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                    color: Colors.white,
                                  ),
                                ),
                                Container(
                                  padding: const EdgeInsets.symmetric(
                                      horizontal: 8, vertical: 4),
                                  decoration: BoxDecoration(
                                    color: (_workerHealth?.healthy ?? true)
                                        ? Colors.green.shade900
                                        : Colors.red.shade900,
                                    borderRadius: BorderRadius.circular(4),
                                  ),
                                  child: Text(
                                    (_workerHealth?.healthy ?? true)
                                        ? 'HEALTHY'
                                        : 'UNHEALTHY',
                                    style: const TextStyle(
                                        color: Colors.white,
                                        fontSize: 11,
                                        fontWeight: FontWeight.bold),
                                  ),
                                ),
                              ],
                            ),
                            const Divider(height: 24, color: Colors.white24),
                            Text(
                                'BLE Owner: ${_workerHealth?.bleOwner ?? "native_worker"}',
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 12)),
                            const SizedBox(height: 4),
                            Text(
                                'Last Reason: ${_workerHealth?.lastReasonCode ?? "N/A"}',
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 12)),
                            const SizedBox(height: 4),
                            Text(
                                'Target Result: ${_workerHealth?.lastTargetReasonName ?? "NONE"}',
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 12)),
                            const SizedBox(height: 4),
                            Text(
                                'Last Latency: ${_workerHealth?.lastLatencyMs ?? 0} ms',
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 12)),
                            if (_workerHealth?.lastGattPerformance != null) ...[
                              const SizedBox(height: 4),
                              Text(
                                  'GATT phases (ms): connect ${_workerHealth!.lastGattPerformance!.connectSetupMs ?? 0} · '
                                  'hello ${_workerHealth!.lastGattPerformance!.negotiationMs ?? 0} · '
                                  'challenge ${_workerHealth!.lastGattPerformance!.challengeMs ?? 0} · '
                                  'sign ${_workerHealth!.lastGattPerformance!.signingMs ?? 0} · '
                                  'proof ${_workerHealth!.lastGattPerformance!.proofWriteMs ?? 0} · '
                                  'result ${_workerHealth!.lastGattPerformance!.resultWaitMs ?? 0}',
                                  style: const TextStyle(
                                      color: Colors.white70, fontSize: 11)),
                              const SizedBox(height: 4),
                              Text(
                                  'GATT link: MTU ${_workerHealth!.lastGattPerformance!.negotiatedMtu} '
                                  '(${_workerHealth!.lastGattPerformance!.mtuStatus}) · '
                                  'high priority ${_workerHealth!.lastGattPerformance!.highPriorityRequested ? "REQUESTED" : "UNAVAILABLE"}',
                                  style: const TextStyle(
                                      color: Colors.white70, fontSize: 11)),
                            ],
                            const SizedBox(height: 4),
                            Text(
                                'Hands-free: ${_workerHealth?.handsFreeReady == true ? "READY" : "NOT READY"} '
                                '(wake: ${_workerHealth?.wakeRegistrationStatus ?? "unknown"})',
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 12)),
                            const SizedBox(height: 4),
                            Text(
                                'Presence → dispatch/ARMED: '
                                '${_workerHealth?.lastPresenceToDispatchMs ?? 0} / '
                                '${_workerHealth?.lastPresenceToArmedMs ?? 0} ms',
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 12)),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // 5. Feature Flags & Interlocked Control
                    Card(
                      color: const Color(0xFF1E1E1E),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              '⚙️ Feature Flags & Interlocked Fallback',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.bold,
                                color: Colors.white,
                              ),
                            ),
                            const SizedBox(height: 8),
                            SwitchListTile(
                              title: const Text('Hardwareless GATT Local Auth'),
                              subtitle: Text(
                                'Native status: ${_workerHealth?.featureStatus ?? "unavailable"}',
                              ),
                              value: _workerHealth?.featureEnabled ?? false,
                              activeThumbColor: Colors.cyan,
                              onChanged:
                                  _workerHealth?.localBootstrapAllowed == true
                                      ? _setNativeGattEnabled
                                      : null,
                            ),
                            SwitchListTile(
                              title: const Text('Legacy REST Pre-arm Flow'),
                              subtitle: const Text(
                                  '구형 서버 Pre-arm 경로 (중복 ARM 방지 인터락)'),
                              value: _flagService.enableLegacyPrearm,
                              activeThumbColor: Colors.amber,
                              onChanged: (val) async {
                                if (val) {
                                  await _healthBridge
                                      .setLocalGattEnabled(false);
                                }
                                await _flagService.updateFlags(
                                  legacyPrearm: val,
                                  killSwitch: _flagService.remoteKillSwitch,
                                );
                                await _loadAllState();
                              },
                            ),
                            SwitchListTile(
                              title: const Text('Remote Kill-Switch Active'),
                              subtitle:
                                  const Text('원격 차단 스위치 (모든 자동/수동 개방 차단)'),
                              value: _flagService.remoteKillSwitch,
                              activeThumbColor: Colors.red,
                              onChanged: (val) async {
                                if (val) {
                                  await _healthBridge
                                      .setLocalGattEnabled(false);
                                }
                                await _flagService.updateFlags(
                                  legacyPrearm: val
                                      ? false
                                      : _flagService.enableLegacyPrearm,
                                  killSwitch: val,
                                );
                                await _loadAllState();
                              },
                            ),
                            const SizedBox(height: 8),
                            OutlinedButton.icon(
                              style: OutlinedButton.styleFrom(
                                foregroundColor: Colors.orangeAccent,
                                side: const BorderSide(
                                    color: Colors.orangeAccent),
                              ),
                              onPressed: () async {
                                await _healthBridge.setLocalGattEnabled(false);
                                await _flagService.rollbackToLegacy();
                                if (!context.mounted) return;
                                await _loadAllState();
                                if (!context.mounted) return;
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                    content: Text(
                                        '앱 재설치 없이 Legacy Pre-arm 경로로 롤백되었습니다.'),
                                  ),
                                );
                              },
                              icon: const Icon(Icons.undo),
                              label: const Text('앱 재설치 없는 Legacy 롤백'),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // 5. OEM Background & Process Kill Recovery Guidance
                    const Card(
                      color: Color(0xFF1E1E1E),
                      child: Padding(
                        padding: EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '📱 OEM 백그라운드 절전 복구 안내',
                              style: TextStyle(
                                fontSize: 15,
                                fontWeight: FontWeight.bold,
                                color: Colors.amberAccent,
                              ),
                            ),
                            SizedBox(height: 8),
                            Text(
                              '• 삼성 (One UI): 설정 > 배터리 > 백그라운드 사용 제한 > 절전 예외 앱에 추가\n'
                              '• 샤오미 (MIUI): 앱 정보 > 배터리 절약 > "제한 없음" 설정\n'
                              '• 백그라운드 스캔이 차단되면 상단의 "1-Tap 수동 로컬 개방" 버튼을 사용하세요.',
                              style: TextStyle(
                                  color: Colors.white70, fontSize: 12),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // 6. Independent OTA P0 Software Update Manager
                    Card(
                      color: const Color(0xFF1E1E1E),
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              '🔄 OTA 소프트웨어 업데이트 매니저 (독립적 접근)',
                              style: TextStyle(
                                fontSize: 16,
                                fontWeight: FontWeight.bold,
                                color: Colors.white,
                              ),
                            ),
                            const SizedBox(height: 8),
                            const Text(
                              'Target 온라인 상태, WebView, BLE 스캐너와 독립적으로 업데이트 검사 및 다운로드를 수행합니다.',
                              style: TextStyle(
                                  color: Colors.white70, fontSize: 12),
                            ),
                            const SizedBox(height: 12),
                            ValueListenableBuilder<UpdateState>(
                              valueListenable: _updateChecker.stateNotifier,
                              builder: (context, updateState, _) {
                                final available =
                                    updateState == UpdateState.available;
                                final failed =
                                    updateState == UpdateState.failed;
                                return Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      updateStatusMessage(
                                        updateState,
                                        version: _updateChecker.remoteVersion,
                                        failureReason:
                                            _updateChecker.lastFailureReason,
                                        mandatory:
                                            _updateChecker.updateMandatory,
                                      ),
                                      style: TextStyle(
                                        color: failed
                                            ? Colors.redAccent
                                            : available
                                                ? Colors.amber
                                                : updateState ==
                                                        UpdateState.healthy
                                                    ? Colors.green
                                                    : Colors.white70,
                                        fontWeight: FontWeight.bold,
                                      ),
                                    ),
                                    const SizedBox(height: 8),
                                    Row(
                                      children: [
                                        ElevatedButton.icon(
                                          onPressed: () async {
                                            await _updateChecker
                                                .checkForUpdates();
                                            if (mounted) setState(() {});
                                          },
                                          icon: const Icon(Icons.refresh),
                                          label: const Text('수동 업데이트 검사'),
                                        ),
                                        const SizedBox(width: 8),
                                        if (available)
                                          ElevatedButton.icon(
                                            style: ElevatedButton.styleFrom(
                                              backgroundColor: Colors.amber,
                                              foregroundColor: Colors.black,
                                            ),
                                            onPressed: () =>
                                                _updateChecker.downloadUpdate(),
                                            icon: const Icon(Icons.download),
                                            label: const Text('APK 다운로드'),
                                          ),
                                      ],
                                    ),
                                  ],
                                );
                              },
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
    );
  }

  String _credentialLabel(NativeGattWorkerHealth? health) {
    if (health == null) return 'Native 상태 확인 불가';
    if (!health.credentialProvisioned) return '등록 필요';
    if (!health.localConsentValid) return '등록됨 · Local consent 확인 필요';
    return 'AndroidKeyStore 등록됨 · Local consent 유효';
  }

  String _targetAclLabel(NativeGattWorkerHealth? health) {
    if (health == null) return '확인 불가';
    if (!health.credentialRegistered) return '키 등록 후 확인 가능';
    final version = health.lastActiveAclVersion;
    return version != null && version > 0
        ? 'v$version 최근 인증 세션에서 확인'
        : '아직 성공 세션에서 확인되지 않음';
  }

  Widget _buildCredentialStatusBadge(NativeGattWorkerHealth? health) {
    final Color color;
    final String text;
    if (health == null) {
      color = Colors.grey;
      text = '상태 확인 불가';
    } else if (health.targetAclConfirmed) {
      color = Colors.green;
      text = '등록 · ACL 확인됨';
    } else if (health.credentialRegistered) {
      color = Colors.amber;
      text = '키 등록됨 · ACL 미확인';
    } else {
      color = Colors.redAccent;
      text = '기기 키 등록 필요';
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.2),
        border: Border.all(color: color),
        borderRadius: BorderRadius.circular(4),
      ),
      child: Text(
        text,
        style:
            TextStyle(color: color, fontSize: 11, fontWeight: FontWeight.bold),
      ),
    );
  }
}
