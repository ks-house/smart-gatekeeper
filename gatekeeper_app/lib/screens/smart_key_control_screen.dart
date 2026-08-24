import 'package:flutter/material.dart';
import '../services/credential_service.dart';
import '../services/feature_flag_service.dart';
import '../services/local_gatt_enrollment_service.dart';
import '../services/native_gatt_worker_health.dart';
import '../services/update_checker.dart';

class SmartKeyControlScreen extends StatefulWidget {
  const SmartKeyControlScreen({super.key});

  @override
  State<SmartKeyControlScreen> createState() => _SmartKeyControlScreenState();
}

class _SmartKeyControlScreenState extends State<SmartKeyControlScreen> {
  final CredentialService _credentialService = CredentialService();
  final FeatureFlagService _flagService = FeatureFlagService();
  final NativeGattWorkerHealthBridge _healthBridge =
      NativeGattWorkerHealthBridge();
  final LocalGattEnrollmentService _enrollmentService =
      LocalGattEnrollmentService();
  final UpdateChecker _updateChecker = UpdateChecker();

  bool _loading = true;
  bool _isRetrying = false;
  NativeGattWorkerHealth? _workerHealth;
  String _retryMessage = '';

  final TextEditingController _nameController = TextEditingController();
  final TextEditingController _roomController = TextEditingController();

  @override
  void initState() {
    super.initState();
    _loadAllState();
  }

  @override
  void dispose() {
    _nameController.dispose();
    _roomController.dispose();
    super.dispose();
  }

  Future<void> _loadAllState() async {
    setState(() => _loading = true);
    await _credentialService.loadCredentialInfo();
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
      setState(() {
        _nameController.text = _credentialService.tenantName;
        _roomController.text = _credentialService.roomNumber;
        _loading = false;
      });
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

  Future<void> _triggerManualRetry() async {
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

    final result = await _healthBridge.triggerLocalGattRetry();
    final success = result['accepted'] == true;
    final reason = result['reason']?.toString() ?? 'NATIVE_UNAVAILABLE';
    try {
      _workerHealth = await _healthBridge.read();
    } catch (_) {
      _workerHealth = null;
    }

    if (mounted) {
      setState(() {
        _isRetrying = false;
        _retryMessage = success
            ? '✅ Target 인증 요청이 durable queue에 등록되었습니다.'
            : '⚠️ 수동 출입 실패: $reason (기존 credential/legacy 경로는 보존됩니다)';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF121212),
      appBar: AppBar(
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
                    // 1. 1-Tap Explicit Manual Local GATT Retry Section
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
                                    _isRetrying ? null : _triggerManualRetry,
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

                    // 2. Credential & Tenant Status Card
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
                                  '🔑 Key & Tenant 상태',
                                  style: TextStyle(
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold,
                                    color: Colors.white,
                                  ),
                                ),
                                _buildStatusBadge(
                                    _credentialService.approvalStatus),
                              ],
                            ),
                            const Divider(height: 24, color: Colors.white24),
                            Text(
                                'Device ID: ${_credentialService.deviceId ?? "불러오는 중..."}',
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 12)),
                            const SizedBox(height: 4),
                            Text(
                                'ACL Lease Version: ${_credentialService.aclVersion}',
                                style: const TextStyle(
                                    color: Colors.white70, fontSize: 12)),
                            const SizedBox(height: 12),
                            TextField(
                              controller: _nameController,
                              decoration: const InputDecoration(
                                labelText: '사용자 이름',
                                labelStyle: TextStyle(color: Colors.white70),
                                border: OutlineInputBorder(),
                                isDense: true,
                              ),
                              style: const TextStyle(color: Colors.white),
                            ),
                            const SizedBox(height: 8),
                            TextField(
                              controller: _roomController,
                              decoration: const InputDecoration(
                                labelText: '호수 (Room)',
                                labelStyle: TextStyle(color: Colors.white70),
                                border: OutlineInputBorder(),
                                isDense: true,
                              ),
                              style: const TextStyle(color: Colors.white),
                            ),
                            const SizedBox(height: 12),
                            OutlinedButton.icon(
                              onPressed: () async {
                                await _credentialService
                                    .saveRegistrationRequest(
                                  _nameController.text,
                                  _roomController.text,
                                );
                                if (!context.mounted) return;
                                setState(() {});
                                ScaffoldMessenger.of(context).showSnackBar(
                                  const SnackBar(
                                      content: Text('등록 요청이 저장되었습니다.')),
                                );
                              },
                              icon: const Icon(Icons.send),
                              label: const Text('Tenant 승인 요청 제출'),
                            ),
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // 3. Native GATT Worker Health Card
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
                          ],
                        ),
                      ),
                    ),
                    const SizedBox(height: 16),

                    // 4. Feature Flags & Interlocked Control
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

  Widget _buildStatusBadge(TenantApprovalStatus status) {
    Color color;
    String text;
    switch (status) {
      case TenantApprovalStatus.approved:
        color = Colors.green;
        text = 'APPROVED (승인 완료)';
        break;
      case TenantApprovalStatus.pending:
        color = Colors.amber;
        text = 'PENDING (승인 대기)';
        break;
      case TenantApprovalStatus.revoked:
        color = Colors.red;
        text = 'REVOKED (권한 회수)';
        break;
      case TenantApprovalStatus.unregistered:
        color = Colors.grey;
        text = 'UNREGISTERED (미등록)';
        break;
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
