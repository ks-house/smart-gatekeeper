import 'dart:async';

import 'package:flutter/material.dart';

import '../l10n/generated/app_localizations.dart';
import '../services/commercial_models.dart';
import '../services/home_message_projection.dart';
import '../services/local_gatt_enrollment_service.dart';
import '../services/mobile_activity_store.dart';
import '../services/mobile_identity_service.dart';
import '../services/native_gatt_worker_health.dart';
import '../services/native_wake_registration.dart';
import '../services/remote_manual_open_service.dart';
import '../services/update_checker.dart';
import 'app_settings_screen.dart';
import 'support_report_screen.dart';
import 'web_view_screen.dart';

class SmartKeyHomeScreen extends StatefulWidget {
  const SmartKeyHomeScreen({super.key});

  @override
  State<SmartKeyHomeScreen> createState() => _SmartKeyHomeScreenState();
}

class _SmartKeyHomeScreenState extends State<SmartKeyHomeScreen> {
  final _identity = MobileIdentityService();
  final _enrollment = LocalGattEnrollmentService();
  final _healthBridge = NativeGattWorkerHealthBridge();
  final _activityStore = MobileActivityStore();
  final _updates = UpdateChecker();
  final _wake = NativeWakeRegistrationBridge();
  final _remoteOpen = RemoteManualOpenService();

  int _tab = 0;
  bool _busy = false;
  MobileIdentityStatus _identityStatus = MobileIdentityStatus.unavailable;
  NativeGattWorkerHealth? _health;
  UpdateExperience? _updateExperience;
  List<MobileActivityItem> _activity = const [];
  List<MobileLifecycleEvent> _lifecycle = const [];
  HomeMessage? _actionMessage;
  Timer? _healthTimer;
  Timer? _identityTimer;

  @override
  void initState() {
    super.initState();
    _updates.downloadProgress.addListener(_refreshUpdateProgress);
    _loadAll();
    _healthTimer = Timer.periodic(
      const Duration(seconds: 1),
      (_) => _refreshHealth(),
    );
    _identityTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => _refreshIdentity(),
    );
  }

  @override
  void dispose() {
    _updates.downloadProgress.removeListener(_refreshUpdateProgress);
    _healthTimer?.cancel();
    _identityTimer?.cancel();
    super.dispose();
  }

  void _refreshUpdateProgress() {
    if (mounted) setState(() {});
  }

  Future<void> _loadAll() async {
    await Future.wait<void>([
      _refreshHealth(),
      _refreshIdentity(),
      _refreshUpdate(),
    ]);
  }

  Future<void> _refreshUpdate() async {
    await _updates.checkForUpdates();
    final experience = await _updates.readExperience();
    if (mounted) setState(() => _updateExperience = experience);
  }

  Future<void> _refreshHealth() async {
    try {
      final health = await _healthBridge.read();
      final activity = await _activityStore.ingest(health);
      if (!mounted) return;
      setState(() {
        _health = health;
        _activity = activity;
      });
    } catch (_) {}
  }

  Future<void> _refreshIdentity() async {
    final status = await _identity.status();
    final lifecycle = await _identity.activity();
    if (!mounted) return;
    setState(() {
      _identityStatus = status;
      _lifecycle = lifecycle;
    });
  }

  Future<void> _runPrimaryAction() async {
    if (_busy) return;
    final action = _identityStatus.nextAction;
    if (action == 'request_registration' ||
        action == 'wait_for_approval' ||
        action == 'contact_administrator' ||
        action == 'renew_credential') {
      await Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const WebViewScreen()),
      );
      await _refreshIdentity();
      return;
    }
    if (action == 'wait_for_acl' || action == 'status_unavailable') {
      setState(() {
        _busy = true;
        _actionMessage = const HomeMessage(HomeMessageKind.statusRefreshing);
      });
      await Future.wait<void>([_refreshIdentity(), _refreshHealth()]);
      if (mounted) {
        setState(() {
          _busy = false;
          _actionMessage = HomeMessage(
            _identityStatus.nextAction == 'status_unavailable'
                ? HomeMessageKind.backendUnavailable
                : HomeMessageKind.statusUpdated,
          );
        });
      }
      return;
    }
    setState(() {
      _busy = true;
      _actionMessage = HomeMessage(
        action == 'enroll_credential'
            ? HomeMessageKind.credentialEnrolling
            : HomeMessageKind.manualOpenRequesting,
      );
    });
    try {
      final enrolled = await _enrollment.ensureEnrolledAndEnabled();
      if (!enrolled.accepted) {
        setState(() {
          _actionMessage = HomeMessage(
            HomeMessageKind.failure,
            reason: enrolled.reason,
          );
        });
        return;
      }
      await _refreshIdentity();
      if (action == 'enroll_credential') {
        setState(() {
          _actionMessage = const HomeMessage(
            HomeMessageKind.credentialEnrollmentComplete,
          );
        });
        return;
      }
      final outcome = await _remoteOpen.request();
      List<MobileActivityItem>? activity;
      try {
        activity = await _activityStore.recordRemoteOpenResult(outcome);
      } catch (_) {
        // A local timeline write failure must not hide the terminal result.
      }
      if (!mounted) return;
      setState(() {
        if (activity != null) _activity = activity;
        _actionMessage = switch (outcome.state) {
          RemoteManualOpenState.requested => const HomeMessage(
              HomeMessageKind.manualOpenCommandExecuted,
            ),
          RemoteManualOpenState.outcomeUnknown => const HomeMessage(
              HomeMessageKind.manualOpenOutcomeUnknown,
            ),
          RemoteManualOpenState.failed => HomeMessage(
              HomeMessageKind.failure,
              reason: outcome.reason,
            ),
        };
      });
      await _refreshHealth();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String _readinessTitle(AppLocalizations strings) {
    if (_identityStatus.nextAction == 'status_unavailable') {
      return strings.statusCheckNeeded;
    }
    if (_identityStatus.accessReady && _health?.handsFreeReady == true) {
      return strings.smartKeyAvailable;
    }
    if (_identityStatus.accessReady) return strings.setupCheckNeeded;
    return switch (_identityStatus.enrollmentState) {
      EnrollmentState.pending => strings.registrationPending,
      EnrollmentState.readyToEnroll => strings.readyToEnroll,
      EnrollmentState.revoked => strings.credentialRevoked,
      EnrollmentState.expired => strings.credentialExpired,
      _ => strings.registrationRequired,
    };
  }

  String _readinessDetail(AppLocalizations strings) {
    if (_identityStatus.accessReady && _health?.handsFreeReady == true) {
      return strings.smartKeyAvailableDetail;
    }
    final blocked = _health?.currentBlockingReasonCode;
    if (blocked != null) return friendlyFailure(blocked, strings);
    if (_identityStatus.nextAction == 'status_unavailable') {
      return strings.backendStatusUnavailableDetail;
    }
    return switch (_identityStatus.nextAction) {
      'request_registration' => strings.requestRegistrationDetail,
      'wait_for_approval' => strings.waitForApprovalDetail,
      'enroll_credential' => strings.enrollCredentialDetail,
      'wait_for_acl' => strings.waitForAclDetail,
      _ => strings.advancedDiagnosticsDetail,
    };
  }

  String _primaryLabel(AppLocalizations strings) =>
      switch (_identityStatus.nextAction) {
        'request_registration' => strings.requestRegistration,
        'wait_for_approval' => strings.checkApprovalStatus,
        'enroll_credential' => strings.registerThisPhone,
        'contact_administrator' => strings.checkRegistration,
        'renew_credential' => strings.viewRenewalGuide,
        'wait_for_acl' => strings.refreshStatus,
        _ => _identityStatus.accessReady
            ? strings.requestOpenCommand
            : strings.checkAgain,
      };

  String _targetState(AppLocalizations strings) {
    final health = _health;
    if (health == null) return 'Target 상태 확인 중';
    return switch (health.detectionStage) {
      TargetDetectionStage.waiting => strings.targetWaiting,
      TargetDetectionStage.detected => strings.targetDetected,
      TargetDetectionStage.authenticating => strings.targetAuthenticating,
      TargetDetectionStage.armed => strings.targetArmed,
      TargetDetectionStage.failed => strings.targetFailed,
      TargetDetectionStage.disabled => strings.automaticAccessDisabled,
    };
  }

  @override
  Widget build(BuildContext context) {
    final strings = AppLocalizations.of(context);
    final titles = [strings.home, strings.activity, strings.settings];
    return Scaffold(
      appBar: AppBar(
        title: Text('${strings.appTitle} · ${titles[_tab]}'),
        actions: [
          IconButton(
            tooltip: strings.refresh,
            onPressed: _loadAll,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: IndexedStack(
        index: _tab,
        children: [_home(), _activityPage(), _settings()],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (value) => setState(() => _tab = value),
        destinations: [
          NavigationDestination(
              icon: const Icon(Icons.home_outlined), label: strings.home),
          NavigationDestination(
              icon: const Icon(Icons.history), label: strings.activity),
          NavigationDestination(
              icon: const Icon(Icons.settings), label: strings.settings),
        ],
      ),
    );
  }

  Widget _home() {
    final strings = AppLocalizations.of(context);
    final ready =
        _identityStatus.accessReady && _health?.handsFreeReady == true;
    return RefreshIndicator(
      onRefresh: _loadAll,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Semantics(
            liveRegion: true,
            label: '${_readinessTitle(strings)}. ${_readinessDetail(strings)}',
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Icon(
                      ready ? Icons.verified_user : Icons.info_outline,
                      size: 48,
                      color: ready ? Colors.greenAccent : Colors.amberAccent,
                    ),
                    const SizedBox(height: 12),
                    Text(_readinessTitle(strings),
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.headlineSmall),
                    const SizedBox(height: 8),
                    Text(_readinessDetail(strings),
                        textAlign: TextAlign.center),
                    const SizedBox(height: 18),
                    FilledButton.icon(
                      onPressed: _busy ? null : _runPrimaryAction,
                      icon: _busy
                          ? const SizedBox.square(
                              dimension: 18,
                              child: CircularProgressIndicator(strokeWidth: 2))
                          : Icon(_identityStatus.accessReady
                              ? Icons.lock_open
                              : Icons.arrow_forward),
                      label: Text(
                          _busy ? strings.processing : _primaryLabel(strings)),
                    ),
                    if (_actionMessage != null) ...[
                      const SizedBox(height: 12),
                      Text(_actionMessage!.resolve(strings),
                          textAlign: TextAlign.center),
                    ],
                  ],
                ),
              ),
            ),
          ),
          const SizedBox(height: 12),
          Card(
            child: ListTile(
              leading: const Icon(Icons.sensors),
              title: Text(_targetState(strings)),
              subtitle: Text(_health?.latestDetection == null
                  ? strings.noRecentDetection
                  : '${strings.recentDetection} '
                      '${_formatTime(_health!.latestDetection!.receivedAt)}'),
              trailing: _health?.detectionStage == TargetDetectionStage.armed
                  ? const Icon(Icons.check_circle, color: Colors.greenAccent)
                  : null,
            ),
          ),
          Card(
            child: ListTile(
              leading: const Icon(Icons.badge_outlined),
              title:
                  Text(_identityStatus.tenantLabel ?? strings.registrationInfo),
              subtitle: Text(
                '${strings.registeredDoors} ${_identityStatus.doorCount} · '
                'ACL ${_identityStatus.aclVersion ?? strings.checking}',
              ),
              trailing: Icon(
                _identityStatus.accessReady ? Icons.verified : Icons.pending,
                color: _identityStatus.accessReady
                    ? Colors.greenAccent
                    : Colors.amberAccent,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _activityPage() {
    final local = _activity;
    return RefreshIndicator(
      onRefresh: _loadAll,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          if (local.isEmpty && _lifecycle.isEmpty)
            const Card(
              child: ListTile(
                leading: Icon(Icons.history_toggle_off),
                title: Text('아직 기록이 없습니다.'),
                subtitle: Text('Target 감지와 스마트키 상태 변경이 여기에 표시됩니다.'),
              ),
            ),
          ...local.map((item) => Card(
                child: ListTile(
                  leading: Icon(
                    item.isFailure
                        ? Icons.error_outline
                        : Icons.check_circle_outline,
                    color:
                        item.isFailure ? Colors.redAccent : Colors.cyanAccent,
                  ),
                  title: Text(item.title),
                  subtitle:
                      Text('${item.detail}\n${_formatTime(item.occurredAt)}'),
                  isThreeLine: true,
                ),
              )),
          if (_lifecycle.isNotEmpty) ...[
            const Padding(
              padding: EdgeInsets.fromLTRB(4, 16, 4, 8),
              child: Text('등록 상태 변경'),
            ),
            ..._lifecycle.map((item) => ListTile(
                  leading: const Icon(Icons.admin_panel_settings_outlined),
                  title: Text(_lifecycleLabel(item.type)),
                  subtitle: Text(_formatTime(item.createdAt.toLocal())),
                )),
          ],
        ],
      ),
    );
  }

  Widget _settings() {
    final strings = AppLocalizations.of(context);
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Card(
          child: Column(
            children: [
              ListTile(
                leading: const Icon(Icons.security),
                title: const Text('백그라운드 출입'),
                subtitle: Text(
                    _health?.handsFreeReady == true ? '사용 가능' : '설정 확인 필요'),
                trailing: const Icon(Icons.chevron_right),
                onTap: () async {
                  await _wake.register();
                  await _refreshHealth();
                },
              ),
              const Divider(height: 1),
              ValueListenableBuilder<UpdateState>(
                valueListenable: _updates.stateNotifier,
                builder: (context, state, _) {
                  final current = _updateExperience;
                  final progress = _updates.downloadProgress.value;
                  final versionLine = current == null
                      ? ''
                      : '${strings.currentVersion} '
                          '${current.installedVersion}+${current.installedBuild}';
                  final availableLine = _updates.remoteVersion == null
                      ? ''
                      : '\n${strings.availableVersion} ${_updates.remoteVersion}';
                  final progressLine = progress == null
                      ? ''
                      : '\n${(progress * 100).toStringAsFixed(0)}%';
                  final healthLine = current?.firstRunHealthy == null
                      ? ''
                      : current!.firstRunHealthy == true
                          ? '\n설치 후 앱 상태 확인 완료'
                          : '\n설치 후 확인 필요: '
                              '${current.firstRunReason ?? 'UNKNOWN'}';
                  return Semantics(
                    button: true,
                    child: ListTile(
                      leading: const Icon(Icons.system_update),
                      title: const Text('앱 업데이트'),
                      subtitle: Text(
                          '$versionLine$availableLine$progressLine$healthLine\n'
                          '${updateStatusMessage(
                        state,
                        version: _updates.remoteVersion,
                        failureReason: _updates.lastFailureReason,
                        mandatory: _updates.updateMandatory,
                      )}'),
                      isThreeLine: true,
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () async {
                        await _refreshUpdate();
                        if (_updates.state == UpdateState.available) {
                          await _updates.downloadUpdate();
                        }
                      },
                    ),
                  );
                },
              ),
              const Divider(height: 1),
              const ListTile(
                leading: Icon(Icons.language),
                title: Text('언어'),
                subtitle: Text('시스템 언어 사용 · 한국어/English'),
              ),
            ],
          ),
        ),
        Card(
          child: ListTile(
            leading: const Icon(Icons.support_agent),
            title: Text(strings.supportReport),
            subtitle: Text(strings.supportReportDescription),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => SupportReportScreen(
                  identity: _identityStatus,
                  health: _health,
                ),
              ),
            ),
          ),
        ),
        Card(
          child: ListTile(
            leading: const Icon(Icons.monitor_heart_outlined),
            title: Text(strings.advancedDiagnostics),
            subtitle: const Text('RSSI, Worker, GATT 단계와 설치자 튜닝'),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const AppSettingsScreen()),
            ),
          ),
        ),
      ],
    );
  }

  String _formatTime(DateTime time) {
    final local = time.toLocal();
    String two(int value) => value.toString().padLeft(2, '0');
    return '${two(local.month)}/${two(local.day)} '
        '${two(local.hour)}:${two(local.minute)}:${two(local.second)}';
  }

  String _lifecycleLabel(String type) => switch (type) {
        'credential_registered' => '이 휴대폰의 스마트키가 등록됨',
        'credential_approved' => '스마트키 승인 완료',
        'credential_disabled' => '스마트키 일시 중지',
        'credential_revoked' => '스마트키 권한 해제',
        'door_granted' => '출입문 권한 추가',
        'door_removed' => '출입문 권한 제거',
        _ => '등록 상태 변경',
      };
}
