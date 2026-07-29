import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_beacon/flutter_beacon.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:device_info_plus/device_info_plus.dart';

import 'device_id_service.dart';
import 'update_checker.dart';
import 'error_logger.dart';
import 'scan_diagnostics.dart';

/// iBeacon 수신 · RSSI 계측 · Pre-arm 요청을 담당하는 싱글톤.
///
/// ## 전력 모델 (issue.md §2.2 / P0-5)
///
/// ```
///   IDLE  ── didEnterRegion / didDetermineStateForRegion(INSIDE) ──▶  ACTIVE
///     ▲                                                                 │
///     └── didExitRegion / ranging N회 연속 무수신 ──────────────────────┘
/// ```
///
/// * **IDLE** — monitoring 만 구독. ranging 콜백·타임아웃 타이머·알림 갱신·
///   prearm HTTP 가 모두 멈춘다. RSSI 는 나오지 않는다.
/// * **ACTIVE** — ranging 을 추가 구독해 약 1Hz 로 RSSI 를 계측한다.
/// * **디버그 강제 모드** — 사용자가 화면을 보고 있으므로 IDLE 강등을 막는다.
///
/// AltBeacon 에서 monitoring 과 ranging 은 **같은 스캔 사이클을 공유**하므로,
/// ranging 을 끄는 것이 라디오를 끄는 것은 아니다. IDLE 에서 실제로 절감되는
/// 것은 콜백 파싱 · ValueNotifier 갱신 · 알림 IPC · 주기 타이머 · HTTP 시도다.
/// 스캔 자체의 전력은 [_kScanPeriodMs] / [_kBetweenScanPeriodMs] 와
/// `setBackgroundMode` 가 선택하는 ScanSettings 모드가 결정한다.
class BleScanner {
  static final BleScanner _instance = BleScanner._internal();
  factory BleScanner() => _instance;
  BleScanner._internal();

  // ── 스캔 파라미터 (issue.md P0-2) ────────────────────────────────────────
  // betweenScanPeriod 를 0(연속 스캔)으로 두는 이유: 반응 지연 3초 목표 때문에
  // 호스트 측 듀티 사이클을 늘릴 수 없다. 전력은 setBackgroundMode(true) 가
  // 선택하는 컨트롤러 측 듀티 사이클(SCAN_MODE_LOW_POWER)에 맡긴다.
  static const int _kScanPeriodMs = 1100;
  static const int _kBetweenScanPeriodMs = 0;

  // ── 신호 소실 판정 (issue.md P1-6) ──────────────────────────────────────
  // AltBeacon 스캔 주기가 약 1100ms 이고 SCAN_MODE_LOW_POWER 에서는 사이클 간
  // 편차가 커진다. 단발 미수신으로 뒤집지 않고 연속 카운트로 판정한다.
  static const int _kRangingTimeoutMs = 6000;

  // ── RSSI 평활 / 히스테리시스 (issue.md P2-15) ───────────────────────────
  static const double _kRssiEmaAlpha = 0.3;
  static const int _kRssiHysteresisDb = 8;

  // ── 알림 갱신 스로틀 (issue.md P2-14) ───────────────────────────────────
  static const int _kNotificationMinIntervalMs = 2000;

  // ── Pre-arm 재시도 / 억제 (issue.md P2-16) ──────────────────────────────
  static const int _kPrearmFailureRetryMs = 2000;
  static const int _kPrearmInFlightGuardMs = 2000;
  static const int _kRecentArmSuppressMs = 4000;

  // ── 워치독 (issue.md P0-4 부분) ─────────────────────────────────────────
  static const Duration _kWatchdogInterval = Duration(seconds: 30);

  static const String _kDefaultBeaconUuid = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
  static final RegExp _kUuidPattern = RegExp(
      r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$');

  final String backendBaseUrl = const String.fromEnvironment('BACKEND_URL',
      defaultValue: 'https://tworimpa.synology.me:4442/api/v1');

  /// 문 제어 API 인증 키 (issue.md P3-22).
  ///
  /// 빌드 시 `--dart-define=GATEKEEPER_API_KEY=...` 로 주입하고, 서버의
  /// 동명 환경변수와 같은 값이어야 한다. 비어 있으면 헤더를 보내지 않으며,
  /// 서버가 키를 설정한 상태라면 Pre-arm 이 401 로 거부된다.
  static const String _apiKey = String.fromEnvironment('GATEKEEPER_API_KEY');

  bool get hasApiKey => _apiKey.isNotEmpty;

  String targetBeaconUuid = _kDefaultBeaconUuid;
  bool ignoreCooldown = false;
  int rssiThreshold = -75;
  int cooldownSeconds = 10;

  /// 사용자가 쿨다운을 직접 조정한 적이 있으면 원격 설정이 덮어쓰지 않는다.
  /// (issue.md P1-12)
  bool _cooldownOverriddenByUser = false;

  // ── UI 바인딩용 알림자 ───────────────────────────────────────────────────
  final ValueNotifier<int?> liveRssi = ValueNotifier<int?>(null);
  final ValueNotifier<double?> smoothedRssi = ValueNotifier<double?>(null);
  final ValueNotifier<DateTime?> lastRssiUpdateTime = ValueNotifier<DateTime?>(null);
  final ValueNotifier<int> packetCount = ValueNotifier<int>(0);
  final ValueNotifier<bool> isBeaconConnected = ValueNotifier<bool>(false);
  final ValueNotifier<ScanMode> modeNotifier = ValueNotifier<ScanMode>(ScanMode.stopped);
  final ValueNotifier<ScanDiagnostics> diagnostics =
      ValueNotifier<ScanDiagnostics>(ScanDiagnostics.unknown(_kDefaultBeaconUuid));

  // ── 내부 상태 ────────────────────────────────────────────────────────────
  ScannerState _currentState = ScannerState.stopped;
  ScanMode _mode = ScanMode.stopped;
  bool _debugForced = false;
  bool _backgroundTuningApplied = false;

  StreamSubscription<MonitoringResult>? _streamMonitoring;
  StreamSubscription<RangingResult>? _streamRanging;
  Timer? _timeoutTimer;
  Timer? _watchdogTimer;

  /// 모드 전환을 직렬화하는 뮤텍스 (issue.md P1-7).
  ///
  /// `ranging()` 은 매 호출마다 새 broadcast stream 을 만들지만 네이티브는
  /// `eventSinkRanging` 필드 하나만 갖는다. 두 구독이 겹치면 두 번째가 sink 를
  /// 덮어쓰고, 첫 번째를 cancel 하면 네이티브 `stopRanging()` 이 호출되어
  /// **두 번째까지 함께 죽는다.** 따라서 모든 전환은
  /// `필드 null 대입 → await cancel → 재구독` 순서로 겹치지 않게 수행해야 한다.
  Future<void> _transitionLock = Future<void>.value();

  double? _smoothedRssiValue;
  bool _aboveThreshold = false;

  String? _lastNotificationKey;
  DateTime? _lastNotificationAt;

  DateTime? _lastEnterRegionAt;
  DateTime? _lastExitRegionAt;
  DateTime? _lastRangingCallbackAt;
  int _rangingCallbackCount = 0;
  String? _lastScanError;

  DateTime? _nextPrearmAllowedAt;
  DateTime? _lastArmSuccessTime;
  bool _isPrearmInProgress = false;
  int? _lastPrearmStatusCode;
  DateTime? _lastPrearmAt;
  String? _lastPrearmMessage;

  int? _androidSdkInt;

  bool get isScanning => _mode != ScanMode.stopped;
  ScanMode get mode => _mode;
  bool get isDebugForced => _debugForced;

  List<Region> get _regions => <Region>[
        Region(identifier: 'SmartGatekeeper', proximityUUID: targetBeaconUuid),
      ];

  // ═══════════════════════════════════════════════════════════════════════
  // 전환 직렬화
  // ═══════════════════════════════════════════════════════════════════════

  /// 전환을 큐에 넣어 순차 실행한다. 실패해도 체인을 끊지 않으며
  /// 반환 Future 는 절대 오류로 완료되지 않는다(fire-and-forget 안전).
  Future<void> _synchronized(String label, Future<void> Function() action) {
    final completer = Completer<void>();
    _transitionLock = _transitionLock.then((_) async {
      try {
        await action();
      } catch (e, s) {
        AppErrorLogger().logError('스캔 상태 전환 실패 ($label)', e, s);
        _lastScanError = '$label: $e';
      } finally {
        if (!completer.isCompleted) completer.complete();
      }
    });
    return completer.future;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 설정 로드/저장
  // ═══════════════════════════════════════════════════════════════════════

  Future<void> loadSavedPreferences() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      ignoreCooldown = prefs.getBool('ignore_cooldown') ?? false;
      rssiThreshold = prefs.getInt('rssi_threshold') ?? -75;
      cooldownSeconds = prefs.getInt('cooldown_seconds') ?? 10;
      _cooldownOverriddenByUser = prefs.getBool('cooldown_seconds_user_set') ?? false;
    } catch (e) {
      debugPrint('[BleScanner] SharedPreferences 로드 실패: $e');
    }
  }

  Future<void> setCooldownSeconds(int value) async {
    cooldownSeconds = value;
    _cooldownOverriddenByUser = true;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt('cooldown_seconds', value);
      await prefs.setBool('cooldown_seconds_user_set', true);
    } catch (_) {}
  }

  Future<void> setIgnoreCooldown(bool value) async {
    ignoreCooldown = value;
    // 진짜 리셋 — 기존 구현은 DateTime.now() 를 넣어 "새 쿨다운을 시작"했다.
    _nextPrearmAllowedAt = null;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool('ignore_cooldown', value);
    } catch (_) {}
  }

  Future<void> setRssiThreshold(int value) async {
    rssiThreshold = value;
    // 임계값이 바뀌면 히스테리시스 상태를 다시 판정해야 한다.
    _aboveThreshold = false;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt('rssi_threshold', value);
    } catch (_) {}
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 초기화
  // ═══════════════════════════════════════════════════════════════════════

  /// 스캔을 네트워크에 블로킹시키지 않는다 (issue.md P2-18).
  /// 원격 설정과 업데이트 확인은 스캔이 시작된 뒤 백그라운드로 진행한다.
  Future<void> initialize() async {
    await loadSavedPreferences();
    await startScanning();
    // 의도적으로 await 하지 않는다.
    // ignore: unawaited_futures
    _loadRemoteConfigAndCheckUpdates();
  }

  Future<void> _loadRemoteConfigAndCheckUpdates() async {
    try {
      await fetchRemoteConfig();
    } catch (e) {
      debugPrint('[BleScanner] fetchRemoteConfig 예외: $e');
    }
    try {
      await UpdateChecker().checkForUpdates();
    } catch (e) {
      debugPrint('[BleScanner] checkForUpdates 예외: $e');
    }
  }

  static bool _isValidBeaconUuid(String value) => _kUuidPattern.hasMatch(value.trim());

  Future<void> fetchRemoteConfig() async {
    try {
      final response = await http
          .get(Uri.parse('$backendBaseUrl/config'))
          .timeout(const Duration(seconds: 5));

      if (response.statusCode != 200) return;

      final data = jsonDecode(response.body);

      // ── beacon_uuid ── 형식 검증 없이 대입하면 네이티브 Region 생성이 실패해
      //    monitoring 이 죽는다 (issue.md P1-11).
      final rawUuid = data['beacon_uuid']?.toString();
      if (rawUuid != null && rawUuid.isNotEmpty) {
        if (_isValidBeaconUuid(rawUuid)) {
          final normalized = rawUuid.trim().toLowerCase();
          if (normalized != targetBeaconUuid) {
            targetBeaconUuid = normalized;
            AppErrorLogger().log('원격 설정으로 Target UUID 변경 → 스캔 재시작 ($normalized)');
            // Region 이 바뀌었으므로 반드시 재구독해야 한다.
            await startScanning(forceRestart: true);
          }
        } else {
          AppErrorLogger()
              .logError('원격 설정의 beacon_uuid 형식이 올바르지 않아 무시했습니다: "$rawUuid"');
        }
      }

      // ── cooldown_sec ── 원격 값은 기본값으로만 사용한다 (issue.md P1-12).
      final remoteCooldown = data['cooldown_sec'];
      if (remoteCooldown is num && !_cooldownOverriddenByUser) {
        cooldownSeconds = remoteCooldown.toInt();
      }

      final apkVersionUrl = data['apk_version_url']?.toString();
      final apkDownloadUrl = data['apk_download_url']?.toString();
      if (apkVersionUrl != null && apkVersionUrl.isNotEmpty) {
        await UpdateChecker().checkForUpdates(
          customVersionUrl: apkVersionUrl,
          customDownloadUrl: apkDownloadUrl,
        );
      }
    } catch (e) {
      debugPrint('[BleScanner] Remote Config 로드 실패 (기본값 사용): $e');
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 진단 (issue.md P1-8, P2-19)
  // ═══════════════════════════════════════════════════════════════════════

  Future<int> _resolveAndroidSdkInt() async {
    if (!Platform.isAndroid) return 0;
    if (_androidSdkInt != null) return _androidSdkInt!;
    try {
      final info = await DeviceInfoPlugin().androidInfo;
      _androidSdkInt = info.version.sdkInt;
    } catch (e) {
      debugPrint('[BleScanner] Android SDK 레벨 확인 실패: $e');
      _androidSdkInt = 0;
    }
    return _androidSdkInt!;
  }

  Future<bool> _isGranted(Permission permission) async {
    try {
      return await permission.isGranted;
    } catch (_) {
      return false;
    }
  }

  /// 현재 상태를 수집해 [diagnostics] 에 반영한다.
  Future<ScanDiagnostics> refreshDiagnostics() async {
    final sdkInt = await _resolveAndroidSdkInt();

    bool bluetoothOn = false;
    try {
      final state = await flutterBeacon.bluetoothState;
      bluetoothOn = state.value == 'STATE_ON';
    } catch (e) {
      debugPrint('[BleScanner] bluetoothState 확인 실패: $e');
    }

    bool locationServicesOn = false;
    try {
      locationServicesOn = await flutterBeacon.checkLocationServicesIfEnabled;
    } catch (e) {
      debugPrint('[BleScanner] 위치 서비스 확인 실패: $e');
    }

    bool batteryExempt = false;
    bool serviceRunning = false;
    try {
      batteryExempt = await FlutterForegroundTask.isIgnoringBatteryOptimizations;
    } catch (_) {}
    try {
      serviceRunning = await FlutterForegroundTask.isRunningService;
    } catch (_) {}

    final snapshot = ScanDiagnostics(
      locationWhenInUse: await _isGranted(Permission.locationWhenInUse),
      locationAlways: await _isGranted(Permission.locationAlways),
      bluetoothScan: await _isGranted(Permission.bluetoothScan),
      bluetoothConnect: await _isGranted(Permission.bluetoothConnect),
      notification: await _isGranted(Permission.notification),
      bluetoothOn: bluetoothOn,
      locationServicesOn: locationServicesOn,
      ignoringBatteryOptimizations: batteryExempt,
      foregroundServiceRunning: serviceRunning,
      mode: _mode,
      debugForced: _debugForced,
      monitoringSubscribed: _streamMonitoring != null,
      rangingSubscribed: _streamRanging != null,
      backgroundScanTuningApplied: _backgroundTuningApplied,
      targetBeaconUuid: targetBeaconUuid,
      androidSdkInt: sdkInt,
      updatedAt: DateTime.now(),
      lastEnterRegionAt: _lastEnterRegionAt,
      lastExitRegionAt: _lastExitRegionAt,
      lastRangingCallbackAt: _lastRangingCallbackAt,
      rangingCallbackCount: _rangingCallbackCount,
      lastPrearmStatusCode: _lastPrearmStatusCode,
      lastPrearmAt: _lastPrearmAt,
      lastPrearmMessage: _lastPrearmMessage,
      lastScanError: _lastScanError,
    );

    diagnostics.value = snapshot;
    return snapshot;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 알림 (issue.md P2-14)
  // ═══════════════════════════════════════════════════════════════════════

  void _updateNotification({
    required String title,
    required String text,
    bool force = false,
  }) {
    final key = '$title $text';
    final now = DateTime.now();

    if (!force) {
      // 동일 내용 반복 갱신 차단
      if (key == _lastNotificationKey) return;
      // 서로 다른 내용이라도 최소 간격을 지킨다. ranging 이 약 1Hz 로 돌기 때문에
      // 여기서 누락된 메시지는 다음 콜백에서 다시 시도된다.
      if (_lastNotificationAt != null &&
          now.difference(_lastNotificationAt!).inMilliseconds <
              _kNotificationMinIntervalMs) {
        return;
      }
    }

    _lastNotificationKey = key;
    _lastNotificationAt = now;

    try {
      FlutterForegroundTask.updateService(
        notificationTitle: title,
        notificationText: text,
      );
    } catch (e) {
      debugPrint('[BleScanner] Notification update error: $e');
    }
  }

  void _notifyIdleWatching() {
    _updateNotification(
      title: '💤 저전력 감시 중',
      text: 'Target 비콘 신호를 저전력으로 탐색하고 있습니다.',
      force: true,
    );
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 스캔 시작 / 정지
  // ═══════════════════════════════════════════════════════════════════════

  Future<void> startScanning({bool forceRestart = false}) {
    return _synchronized('startScanning', () async {
      if (_mode != ScanMode.stopped && !forceRestart) return;

      await _teardownStreamsLocked();

      // ── 1. 프리플라이트 게이트 (issue.md P1-8) ──────────────────────────
      final snapshot = await refreshDiagnostics();
      if (!snapshot.canScan) {
        final reason = snapshot.blockingReasons.join(' / ');
        AppErrorLogger().logError('스캔을 시작할 수 없습니다 — $reason');
        _updateNotification(
          title: '⚠️ 비콘 감지를 시작할 수 없습니다',
          text: reason,
          force: true,
        );
        _setMode(ScanMode.stopped);
        _startWatchdog(); // 사유가 해소되면 자동 복구
        await refreshDiagnostics();
        return;
      }
      for (final warning in snapshot.warningReasons) {
        AppErrorLogger().log('⚠️ $warning');
      }

      // ── 2. JobScheduler 위임 차단 — 반드시 바인딩 전 (issue.md P0-2) ────
      await _disableScheduledScanJobs();

      // ── 3. 네이티브 스캔 초기화 ─────────────────────────────────────────
      try {
        await flutterBeacon.initializeScanning;
      } catch (e, s) {
        debugPrint('[BleScanner] flutterBeacon 초기화 실패: $e');
        AppErrorLogger().logError('BLE 비콘 스캔 초기화 실패', e, s);
        _lastScanError = 'initializeScanning: $e';
        _updateNotification(
          title: '⚠️ BLE 비콘 스캔 초기화 실패',
          text: '블루투스/위치 서비스 또는 권한 상태를 확인해주세요 ($e)',
          force: true,
        );
        _setMode(ScanMode.stopped);
        _startWatchdog();
        await refreshDiagnostics();
        return;
      }

      // ── 4. 화면 OFF 대응 스캔 설정 (issue.md P0-2) ──────────────────────
      await _applyBackgroundScanTuning();

      // ── 5. monitoring 구독 → IDLE 진입 ─────────────────────────────────
      final regions = _regions;
      AppErrorLogger()
          .log('🛡️ iBeacon 구역 감시(monitoring) 시작 (UUID: $targetBeaconUuid)');
      _subscribeMonitoringLocked(regions);
      _setMode(ScanMode.idle);
      _notifyIdleWatching();

      // 디버그 화면이 열린 상태에서 재시작된 경우(예: 워치독 복구) ranging 강제
      // 유지를 복원해야 한다. 그러지 않으면 화면은 열려 있는데 RSSI 가 멈춘다.
      if (_debugForced) {
        _subscribeRangingLocked();
        _setMode(ScanMode.active);
      }

      _startWatchdog();
      await refreshDiagnostics();
    });
  }

  Future<void> stopScanning() {
    return _synchronized('stopScanning', () async {
      _watchdogTimer?.cancel();
      _watchdogTimer = null;
      await _teardownStreamsLocked();
      _setMode(ScanMode.stopped);
      debugPrint('[BleScanner] 비콘 스캐닝 중지됨.');
      _syncStateAndNotify();
      await refreshDiagnostics();
    });
  }

  /// 모든 스트림/타이머를 정리한다. **반드시 뮤텍스 안에서 호출**할 것.
  Future<void> _teardownStreamsLocked() async {
    _timeoutTimer?.cancel();
    _timeoutTimer = null;

    // ⚠️ cancel() 전에 필드를 비워 재진입/중복 구독을 원천 차단한다. (P0-1, P1-7)
    final ranging = _streamRanging;
    final monitoring = _streamMonitoring;
    _streamRanging = null;
    _streamMonitoring = null;
    await ranging?.cancel();
    await monitoring?.cancel();

    _resetSignalState();
  }

  void _resetSignalState() {
    liveRssi.value = null;
    smoothedRssi.value = null;
    isBeaconConnected.value = false;
    _smoothedRssiValue = null;
    _aboveThreshold = false;
  }

  void _setMode(ScanMode next) {
    _mode = next;
    modeNotifier.value = next;
  }

  Future<void> _disableScheduledScanJobs() async {
    if (!Platform.isAndroid) return;
    try {
      await flutterBeacon.setEnableScheduledScanJobs(false);
    } catch (e) {
      debugPrint('[BleScanner] setEnableScheduledScanJobs 실패: $e');
    }
  }

  /// 화면 OFF 상태에서도 스캔 결과를 받기 위한 설정 (issue.md P0-2).
  ///
  /// Android 8.1+ 는 화면이 꺼진 동안 **ScanFilter 없는 스캔**의 결과를 앱에
  /// 전달하지 않는다. AltBeacon 에서 ScanFilter 를 켜는 유일한 방법이
  /// `setBackgroundMode(true)` 이며, 이때 ScanSettings 는
  /// SCAN_MODE_LOW_POWER 가 된다.
  ///
  /// 화면이 켜져 있을 때도 `true` 로 유지한다 — `false` 로 되돌리면 필터가
  /// 사라져 화면 OFF 에서 다시 죽는다.
  Future<void> _applyBackgroundScanTuning() async {
    if (!Platform.isAndroid) {
      _backgroundTuningApplied = false;
      return;
    }
    try {
      await flutterBeacon.setBackgroundMode(true);
      // 기본값 10000ms / 300000ms(5분)를 그대로 두면 RSSI 가 5분에 한 번 온다.
      await flutterBeacon.setBackgroundScanPeriod(_kScanPeriodMs);
      await flutterBeacon.setBackgroundBetweenScanPeriod(_kBetweenScanPeriodMs);
      // backgroundMode 가 어떤 이유로 false 로 되돌아가도 주기는 유지되도록.
      await flutterBeacon.setScanPeriod(_kScanPeriodMs);
      await flutterBeacon.setBetweenScanPeriod(_kBetweenScanPeriodMs);
      _backgroundTuningApplied = true;
      AppErrorLogger().log(
          '⚙️ 스캔 설정 적용: backgroundMode=true, scan=${_kScanPeriodMs}ms, between=${_kBetweenScanPeriodMs}ms');
    } catch (e, s) {
      _backgroundTuningApplied = false;
      AppErrorLogger().logError('화면 OFF 대응 스캔 설정 적용 실패', e, s);
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // monitoring — 구역 진입/이탈
  // ═══════════════════════════════════════════════════════════════════════

  void _subscribeMonitoringLocked(List<Region> regions) {
    _streamMonitoring = flutterBeacon.monitoring(regions).listen(
      (MonitoringResult result) {
        switch (result.monitoringEventType) {
          case MonitoringEventType.didEnterRegion:
            _onRegionEntered('didEnterRegion');
            break;
          case MonitoringEventType.didExitRegion:
            _onRegionExited('didExitRegion');
            break;
          case MonitoringEventType.didDetermineStateForRegion:
            // ⚠️ 필수 처리 (issue.md P0-5 함정 1).
            // 이미 구역 안에 있는 상태로 앱을 켜면 didEnterRegion 이 오지 않고
            // didDetermineStateForRegion(INSIDE) 만 온다. 이걸 무시하면
            // "문 앞에 서 있는 상태로 앱을 켜면 영구히 IDLE" 이 된다.
            if (result.monitoringState == MonitoringState.inside) {
              _onRegionEntered('didDetermineStateForRegion(INSIDE)');
            } else if (result.monitoringState == MonitoringState.outside) {
              _onRegionExited('didDetermineStateForRegion(OUTSIDE)');
            }
            break;
        }
      },
      onError: (dynamic error, StackTrace? stack) {
        debugPrint('[BleScanner] ⚠️ Monitoring stream error: $error');
        AppErrorLogger().logError('Monitoring 스트림 오류', error, stack);
        _lastScanError = 'monitoring: $error';
      },
    );
  }

  void _onRegionEntered(String source) {
    _lastEnterRegionAt = DateTime.now();
    if (_mode == ScanMode.active) return; // 이미 계측 중
    AppErrorLogger().log('🔔 구역 진입 감지 ($source) → 고속 계측 모드로 승격');
    // ignore: unawaited_futures
    _enterActiveMode(reason: source);
  }

  void _onRegionExited(String source) {
    _lastExitRegionAt = DateTime.now();
    if (_mode != ScanMode.active) return;
    AppErrorLogger().log('🚪 구역 이탈 감지 ($source) → 저전력 감시 모드로 강등');
    // ignore: unawaited_futures
    _enterIdleMode(reason: source);
  }

  void _syncStateAndNotify() {
    ScannerState newState = ScannerState.stopped;
    String title = '';
    String text = '';
    bool force = false;

    if (_mode == ScanMode.stopped) {
      newState = ScannerState.stopped;
      title = '❌ 스캔 중지됨';
      text = '블루투스 권한이나 설정 오류로 중지되었습니다.';
    } else if (_mode == ScanMode.idle) {
      newState = ScannerState.idleMonitoring;
      title = '💤 저전력 감시 중';
      text = 'Target 비콘 구역 진입 대기 중...';
    } else if (_mode == ScanMode.active) {
      final now = DateTime.now();
      
      final isCooldown = !ignoreCooldown && _nextPrearmAllowedAt != null && now.isBefore(_nextPrearmAllowedAt!);
      final isRecentArm = _lastArmSuccessTime != null && now.difference(_lastArmSuccessTime!).inMilliseconds < _kRecentArmSuppressMs;
      
      final last = lastRssiUpdateTime.value;
      final isStale = last == null 
          ? (_lastEnterRegionAt != null && now.difference(_lastEnterRegionAt!).inMilliseconds > _kRangingTimeoutMs)
          : now.difference(last).inMilliseconds > _kRangingTimeoutMs;

      if (isRecentArm) {
        // 이미 승인 성공 알림을 보냈으므로, 여기서는 쿨다운 상태로 전이만 기록하고 알림은 덮어쓰지 않는다.
        newState = ScannerState.cooldown;
      } else if (isCooldown) {
        newState = ScannerState.cooldown;
        final remainSec = (_nextPrearmAllowedAt!.difference(now).inMilliseconds / 1000).ceil();
        title = '⏳ 출입 쿨다운 대기 중 ($remainSec초)';
        text = 'Target 비콘 감지됨 — 연속 개방 방지 대기 중';
        force = true; // 초 단위 카운트다운을 위해 강제 갱신
      } else if (isStale || last == null) {
        newState = ScannerState.activeSearching;
        title = '🔴 Target 비콘 신호 탐색 중';
        text = '구역 내에 있지만 신호가 일시적으로 약합니다...';
      } else if (!_aboveThreshold) {
        newState = ScannerState.activeWeak;
        final ema = _smoothedRssiValue ?? liveRssi.value?.toDouble() ?? 0.0;
        title = '🟡 Target 비콘 신호 약함 (${liveRssi.value} dBm)';
        text = '센서 근접 필요 (평활 ${ema.toStringAsFixed(1)} dBm / 기준 $rssiThreshold dBm)';
      } else {
        newState = ScannerState.activeConnected;
        title = '🟢 Target 비콘 감지됨 (RSSI: ${liveRssi.value} dBm)';
        text = '출입 통제 구역에 연결되었습니다.';
      }
    }

    if (_currentState != newState) {
      AppErrorLogger().log('[BleScanner State] ${_currentState.name} ➡️ ${newState.name}');
      _currentState = newState;
    }

    // isRecentArm 일 때는 기존 "승인 완료" 알림을 유지하기 위해 업데이트를 건너뛴다.
    if (newState == ScannerState.cooldown && _lastArmSuccessTime != null && 
        DateTime.now().difference(_lastArmSuccessTime!).inMilliseconds < _kRecentArmSuppressMs) {
      return;
    }

    // 서버 통신 오류(401, 403, 500 등)로 인해 특별한 알림이 떠있는 경우도 덮어쓰지 않는다.
    // _isPrearmInProgress 가 끝난 직후 에러 상태를 2초 정도 유지한다.
    final bool isRecentError = _lastPrearmAt != null && 
        _lastPrearmStatusCode != 200 && 
        DateTime.now().difference(_lastPrearmAt!).inMilliseconds < _kRecentArmSuppressMs;
    if (isRecentError) {
      return;
    }

    _updateNotification(title: title, text: text, force: force);
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 모드 전환
  // ═══════════════════════════════════════════════════════════════════════

  List<Region> get _rangingRegions {
    return [
      Region(
        identifier: 'GatekeeperRangingRegion',
        proximityUUID: targetBeaconUuid,
      )
    ];
  }

  /// ranging 구독을 시작한다. **반드시 뮤텍스 안에서 호출**할 것.
  void _subscribeRangingLocked() {
    if (_streamRanging != null) return;

    _streamRanging = flutterBeacon.ranging(_rangingRegions).listen(
      (RangingResult result) {
        _lastRangingCallbackAt = DateTime.now();
        _rangingCallbackCount++;
        for (final beacon in result.beacons) {
          _processBeacon(beacon);
        }
      },
      onError: (dynamic error, StackTrace? stack) {
        debugPrint('[BleScanner] ⚠️ Ranging stream error: $error');
        AppErrorLogger().logError('Ranging 스트림 오류', error, stack);
        _lastScanError = 'ranging: $error';
      },
    );

    _startTimeoutCheckTimer();
  }

  Future<void> _enterActiveMode({required String reason}) {
    return _synchronized('enterActive($reason)', () async {
      if (_mode == ScanMode.stopped) return;

      final bool alreadyRanging = _streamRanging != null;
      _subscribeRangingLocked();
      _setMode(ScanMode.active);
      _syncStateAndNotify();
      await refreshDiagnostics();
    });
  }

  Future<void> _enterIdleMode({required String reason}) {
    return _synchronized('enterIdle($reason)', () async {
      if (_mode == ScanMode.stopped) return;

      if (_debugForced) {
        // 디버그 화면을 보고 있는 동안에는 강등하지 않는다.
        AppErrorLogger().log('🔧 디버그 강제 모드 — IDLE 강등 보류 ($reason)');
        return;
      }

      _timeoutTimer?.cancel();
      _timeoutTimer = null;

      final ranging = _streamRanging;
      _streamRanging = null;
      await ranging?.cancel();

      _resetSignalState();
      _setMode(ScanMode.idle);
      _syncStateAndNotify();
      await refreshDiagnostics();
    });
  }

  /// 디버그 화면 진입 — IDLE 이어도 ranging 을 강제로 유지한다.
  Future<void> enterDebugMode() async {
    _debugForced = true;
    if (_mode == ScanMode.stopped) {
      await startScanning();
    }
    await _enterActiveMode(reason: '디버그 화면 진입');
  }

  /// 디버그 화면 이탈 — 신호가 없으면 저전력 모드로 돌아간다.
  Future<void> exitDebugMode() async {
    _debugForced = false;
    if (!isBeaconConnected.value) {
      await _enterIdleMode(reason: '디버그 화면 이탈');
    }
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 신호 소실 감시 (issue.md P1-6)
  // ═══════════════════════════════════════════════════════════════════════

  void _startTimeoutCheckTimer() {
    _timeoutTimer?.cancel();
    _timeoutTimer = Timer.periodic(const Duration(milliseconds: 1000), (_) {
      final last = lastRssiUpdateTime.value;
      final now = DateTime.now();
      
      final isStale = last == null 
          ? (_lastEnterRegionAt != null && now.difference(_lastEnterRegionAt!).inMilliseconds > _kRangingTimeoutMs)
          : now.difference(last).inMilliseconds > _kRangingTimeoutMs;

      // 타임아웃(6초 초과) 발생 시 처리
      if (isStale && (isBeaconConnected.value || liveRssi.value != null)) {
        _resetSignalState();
        debugPrint('[BleScanner] ⚠️ Target 비콘 신호 미수신 (${_kRangingTimeoutMs}ms 초과)');
        AppErrorLogger().log('⚠️ ranging 신호 미수신 (${_kRangingTimeoutMs}ms 초과). 네이티브 구역 이탈(didExitRegion) 대기 중...');
      }

      // 4층 등 물리적으로 신호가 불가능한 곳에서 앱을 켰을 때, 
      // 디버그 모드가 켜져있더라도 IDLE 강등을 막으면 상태가 영원히 ACTIVE(계측 중)에 빠지게 된다.
      // 이를 방지하기 위해 isStale 이고 초기 패킷 유실 상태면 디버그 여부와 상관없이 IDLE 로 강등한다.
      if (isStale && last == null && _mode == ScanMode.active) {
        AppErrorLogger().log('🔧 초기 패킷 완전 유실 감지 — IDLE 모드로 강제 복귀하여 리셋 유도');
        // 디버그 강제 모드 무시용 flag 를 줘서 강등시키거나 직접 끈다.
        _setMode(ScanMode.idle);
        _streamRanging?.cancel();
        _streamRanging = null;
      }

      _syncStateAndNotify();
    });
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 비콘 처리
  // ═══════════════════════════════════════════════════════════════════════

  void _processBeacon(Beacon beacon) {
    if (beacon.proximityUUID.isEmpty) return;

    // UUID 정규화 (하이픈 제거 + 소문자). 네이티브는 대문자로 올려준다.
    final String cleanBeaconUuid =
        beacon.proximityUUID.replaceAll(RegExp(r'[^a-zA-Z0-9]'), '').toLowerCase();
    final String cleanTargetUuid =
        targetBeaconUuid.replaceAll(RegExp(r'[^a-zA-Z0-9]'), '').toLowerCase();

    if (cleanBeaconUuid != cleanTargetUuid) return;

    final int rssi = beacon.rssi;
    if (rssi == 0 || rssi == -1) return; // Invalid RSSI

    // ── 표시용: 순간값 ──────────────────────────────────────────────────
    liveRssi.value = rssi;
    lastRssiUpdateTime.value = DateTime.now();
    isBeaconConnected.value = true;
    packetCount.value++;

    // ── 판정용: EMA 평활 (issue.md P2-15) ────────────────────────────────
    final double ema = _smoothedRssiValue == null
        ? rssi.toDouble()
        : (_kRssiEmaAlpha * rssi + (1 - _kRssiEmaAlpha) * _smoothedRssiValue!);
    _smoothedRssiValue = ema;
    smoothedRssi.value = ema;

    if (_isPrearmInProgress) return;

    final isRecentArm = _lastArmSuccessTime != null &&
        DateTime.now().difference(_lastArmSuccessTime!).inMilliseconds <
            _kRecentArmSuppressMs;

    // ── 히스테리시스 판정 ────────────────────────────────────────────────
    // 진입은 threshold, 이탈은 threshold - 8dB. 문 앞에서 판정이 튀는 것을 막는다.
    if (_aboveThreshold) {
      if (ema < rssiThreshold - _kRssiHysteresisDb) _aboveThreshold = false;
    } else {
      if (ema >= rssiThreshold) _aboveThreshold = true;
    }

    if (!_aboveThreshold) {
      _syncStateAndNotify();
      return;
    }

    // ── 쿨다운 (issue.md P2-16) ─────────────────────────────────────────
    final now = DateTime.now();
    if (!ignoreCooldown &&
        _nextPrearmAllowedAt != null &&
        now.isBefore(_nextPrearmAllowedAt!)) {
      _syncStateAndNotify();
      return;
    }

    // 요청이 진행되는 동안의 연타를 막는 짧은 가드. 결과에 따라 아래에서 덮어쓴다.
    _nextPrearmAllowedAt =
        now.add(const Duration(milliseconds: _kPrearmInFlightGuardMs));
    // ignore: unawaited_futures
    _sendPrearmRequest(rssi);
  }

  Future<void> _sendPrearmRequest(int rssi) async {
    if (_isPrearmInProgress) return;
    _isPrearmInProgress = true;

    try {
      final deviceId = await DeviceIdService.getDeviceId();
      final response = await http
          .post(
            Uri.parse('$backendBaseUrl/door/prearm'),
            headers: {
              'Content-Type': 'application/json',
              // 키가 비어 있으면 헤더를 아예 보내지 않는다 (issue.md P3-22).
              if (_apiKey.isNotEmpty) 'X-API-KEY': _apiKey,
            },
            body: jsonEncode({
              'beacon_uuid': targetBeaconUuid,
              'device_id': deviceId,
              'rssi': rssi,
              'timestamp': DateTime.now().toIso8601String(),
            }),
          )
          .timeout(const Duration(seconds: 4));

      _lastPrearmAt = DateTime.now();
      _lastPrearmStatusCode = response.statusCode;

      if (response.statusCode == 200) {
        _lastArmSuccessTime = DateTime.now();
        _lastPrearmMessage = '승인 완료';
        // 성공했을 때만 정상 쿨다운을 적용한다.
        _nextPrearmAllowedAt =
            DateTime.now().add(Duration(seconds: cooldownSeconds));
        _updateNotification(
          title: '🟢 Smart Key 출입문 승인 완료!',
          text: 'Target 비콘 감지 ($rssi dBm) → 센서로 다가가면 문이 열립니다!',
          force: true,
        );
      } else if (response.statusCode == 401) {
        // 앱 빌드의 API 키가 서버 설정과 다르다 — 재설치/업데이트가 필요하다.
        _lastPrearmMessage = 'API 키 인증 실패 (401)';
        _nextPrearmAllowedAt =
            DateTime.now().add(Duration(seconds: cooldownSeconds));
        AppErrorLogger().logError(
            '출입 승인 거부 (HTTP 401) — 앱의 API 키가 서버 설정과 일치하지 않습니다. 앱 업데이트가 필요합니다.');
        _updateNotification(
          title: '⛔ 앱 인증 실패 (401)',
          text: '앱을 최신 버전으로 업데이트해주세요.',
          force: true,
        );
      } else if (response.statusCode == 403) {
        _lastPrearmMessage = '권한 거부/미승인';
        // 권한 문제는 즉시 재시도해도 결과가 같으므로 정상 쿨다운을 적용한다.
        _nextPrearmAllowedAt =
            DateTime.now().add(Duration(seconds: cooldownSeconds));
        AppErrorLogger().logError('출입 권한 거부 (HTTP 403)');
        _updateNotification(
          title: '⛔ 출입 권한 거부/미승인',
          text: '관리자 승인이 필요한 세입자 기기입니다.',
          force: true,
        );
      } else {
        _lastPrearmMessage = 'HTTP ${response.statusCode}';
        _scheduleFailureRetry();
        AppErrorLogger()
            .logError('출입 승인 실패 (HTTP ${response.statusCode})', response.body);
        _updateNotification(
          title: '⚠️ 출입 승인 실패 (HTTP ${response.statusCode})',
          text: '서버 통신 오류가 발생했습니다. 잠시 후 재시도합니다.',
          force: true,
        );
      }
    } catch (e, s) {
      // 실패를 사용자에게 알리지 않으면 문 앞에서 아무 반응이 없는 것처럼 보인다.
      _lastPrearmAt = DateTime.now();
      _lastPrearmStatusCode = null;
      _lastPrearmMessage = '통신 오류: $e';
      _scheduleFailureRetry();
      debugPrint('[BleScanner] Pre-arm API 통신 오류: $e');
      AppErrorLogger().logError('Pre-arm API 통신 오류', e, s);
      _updateNotification(
        title: '⚠️ 서버 통신 실패',
        text: '출입 승인 요청을 보내지 못했습니다. 잠시 후 재시도합니다.',
        force: true,
      );
    } finally {
      _isPrearmInProgress = false;
    }
  }

  /// 실패 시에는 전체 쿨다운(최대 30초)이 아니라 짧은 재시도 간격만 적용한다.
  /// 문 앞에 선 사용자를 수십 초 기다리게 하지 않기 위한 것이다.
  void _scheduleFailureRetry() {
    _nextPrearmAllowedAt =
        DateTime.now().add(const Duration(milliseconds: _kPrearmFailureRetryMs));
  }

  // ═══════════════════════════════════════════════════════════════════════
  // 워치독 / 생애주기 (issue.md P0-4 부분)
  // ═══════════════════════════════════════════════════════════════════════

  void _startWatchdog() {
    _watchdogTimer?.cancel();
    _watchdogTimer = Timer.periodic(_kWatchdogInterval, (_) {
      // ignore: unawaited_futures
      _watchdogTick();
    });
  }

  /// 스캔이 죽었거나 차단 사유가 해소된 경우를 주기적으로 확인해 복구한다.
  ///
  /// 완전한 해결책은 스캐너를 포그라운드 서비스 isolate 로 옮기는 것이다
  /// (issue.md P0-4 안 A). 그 작업이 완료될 때까지의 안전망이다.
  Future<void> _watchdogTick() async {
    final snapshot = await refreshDiagnostics();

    if (_mode == ScanMode.stopped) {
      if (snapshot.canScan) {
        AppErrorLogger().log('🔄 워치독: 차단 사유 해소 감지 → 스캔 재시작');
        await startScanning(forceRestart: true);
      }
      return;
    }

    if (_streamMonitoring == null) {
      AppErrorLogger().logError('🔄 워치독: monitoring 구독이 사라짐 → 스캔 재시작');
      await startScanning(forceRestart: true);
      return;
    }

    if (!snapshot.canScan) {
      final reason = snapshot.blockingReasons.join(' / ');
      AppErrorLogger().logError('🔄 워치독: 스캔 전제조건 상실 — $reason');
      _setMode(ScanMode.idle);
      _syncStateAndNotify();
    }
  }

  /// 앱이 포그라운드로 복귀했을 때 스캔 상태를 점검·복구한다.
  Future<void> onAppResumed() async {
    final snapshot = await refreshDiagnostics();
    if (_mode == ScanMode.stopped) {
      if (snapshot.canScan) {
        await startScanning();
      }
      return;
    }
    if (_streamMonitoring == null) {
      AppErrorLogger().logError('앱 복귀: monitoring 구독이 사라짐 → 스캔 재시작');
      await startScanning(forceRestart: true);
    }
  }
}
