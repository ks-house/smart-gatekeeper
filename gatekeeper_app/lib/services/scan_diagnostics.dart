import 'package:flutter/foundation.dart';

/// 스캐너의 전력/동작 모드 (issue.md §2.2 2단 전력 모델).
///
/// * [stopped] — 스캔하지 않음. 권한/OS 스위치 문제로 시작조차 못 한 상태도 포함.
/// * [idle]    — monitoring 만 구독. RSSI 가 나오지 않는 저전력 감시 상태.
/// * [active]  — monitoring + ranging. RSSI 는 이 모드에서만 갱신된다.
enum ScanMode { stopped, idle, active }

extension ScanModeLabel on ScanMode {
  String get label {
    switch (this) {
      case ScanMode.stopped:
        return '정지 (STOPPED)';
      case ScanMode.idle:
        return '저전력 감시 (IDLE)';
      case ScanMode.active:
        return '고속 계측 (ACTIVE)';
    }
  }
}

/// 스캔이 왜 동작하지 않는지를 앱 안에서 확인할 수 있게 하는 진단 스냅샷
/// (issue.md P1-8, P2-19).
///
/// 기존 구조에서는 위치 서비스(GPS)가 꺼져 있거나 BLUETOOTH_SCAN 권한이 없으면
/// Android 가 스캔 결과를 **오류 없이 0건으로** 반환했고, 앱은 이를 감지할
/// 수단이 전혀 없었다.
@immutable
class ScanDiagnostics {
  // ── 런타임 권한 ──────────────────────────────────────────────
  final bool locationWhenInUse;
  final bool locationAlways;
  final bool bluetoothScan;
  final bool bluetoothConnect;
  final bool notification;

  // ── OS 스위치 ────────────────────────────────────────────────
  final bool bluetoothOn;
  final bool locationServicesOn;

  // ── 앱/서비스 상태 ───────────────────────────────────────────
  final bool ignoringBatteryOptimizations;
  final bool foregroundServiceRunning;

  // ── 스캔 상태 ────────────────────────────────────────────────
  final ScanMode mode;
  final bool debugForced;
  final bool monitoringSubscribed;
  final bool rangingSubscribed;

  /// `setBackgroundMode(true)` 등 화면 OFF 대응 스캔 설정이 실제로 적용됐는지.
  final bool backgroundScanTuningApplied;

  final String targetBeaconUuid;
  final DateTime? lastEnterRegionAt;
  final DateTime? lastExitRegionAt;
  final DateTime? lastRangingCallbackAt;
  final int rangingCallbackCount;

  final int? lastPrearmStatusCode;
  final DateTime? lastPrearmAt;
  final String? lastPrearmMessage;

  final String? lastScanError;

  /// Android SDK 레벨. 0 이면 미확인(또는 비 Android).
  final int androidSdkInt;

  final DateTime updatedAt;

  const ScanDiagnostics({
    required this.locationWhenInUse,
    required this.locationAlways,
    required this.bluetoothScan,
    required this.bluetoothConnect,
    required this.notification,
    required this.bluetoothOn,
    required this.locationServicesOn,
    required this.ignoringBatteryOptimizations,
    required this.foregroundServiceRunning,
    required this.mode,
    required this.debugForced,
    required this.monitoringSubscribed,
    required this.rangingSubscribed,
    required this.backgroundScanTuningApplied,
    required this.targetBeaconUuid,
    required this.androidSdkInt,
    required this.updatedAt,
    this.lastEnterRegionAt,
    this.lastExitRegionAt,
    this.lastRangingCallbackAt,
    this.rangingCallbackCount = 0,
    this.lastPrearmStatusCode,
    this.lastPrearmAt,
    this.lastPrearmMessage,
    this.lastScanError,
  });

  factory ScanDiagnostics.unknown(String targetBeaconUuid) => ScanDiagnostics(
        locationWhenInUse: false,
        locationAlways: false,
        bluetoothScan: false,
        bluetoothConnect: false,
        notification: false,
        bluetoothOn: false,
        locationServicesOn: false,
        ignoringBatteryOptimizations: false,
        foregroundServiceRunning: false,
        mode: ScanMode.stopped,
        debugForced: false,
        monitoringSubscribed: false,
        rangingSubscribed: false,
        backgroundScanTuningApplied: false,
        targetBeaconUuid: targetBeaconUuid,
        androidSdkInt: 0,
        updatedAt: DateTime.fromMillisecondsSinceEpoch(0),
      );

  /// Android 12(API 31)부터 BLUETOOTH_SCAN / BLUETOOTH_CONNECT 가 런타임 권한이 된다.
  /// 그 이전 버전에서는 permission_handler 의 결과와 무관하게 차단 사유로 보지 않는다.
  bool get requiresRuntimeBluetoothPermission => androidSdkInt >= 31;

  /// 스캔이 물리적으로 불가능한 사유들. 비어 있으면 스캔을 시작할 수 있다.
  List<String> get blockingReasons {
    final reasons = <String>[];
    if (!bluetoothOn) {
      reasons.add('블루투스가 꺼져 있습니다');
    }
    if (!locationServicesOn) {
      // Android 는 위치 서비스가 꺼져 있으면 BLE 스캔 결과를 조용히 0건으로 반환한다.
      reasons.add('위치 서비스(GPS)가 꺼져 있습니다');
    }
    if (!locationWhenInUse) {
      reasons.add('위치 권한이 없습니다');
    }
    if (requiresRuntimeBluetoothPermission && !bluetoothScan) {
      reasons.add('블루투스 스캔 권한이 없습니다');
    }
    return reasons;
  }

  /// 동작은 하지만 백그라운드/화면 OFF 신뢰성을 떨어뜨리는 사유들.
  List<String> get warningReasons {
    final warnings = <String>[];
    if (!locationAlways) {
      warnings.add('백그라운드 위치 권한이 없어 화면 OFF/백그라운드 감지가 불안정할 수 있습니다');
    }
    if (!notification) {
      warnings.add('알림 권한이 없어 상태 알림이 표시되지 않습니다');
    }
    if (!ignoringBatteryOptimizations) {
      warnings.add('배터리 최적화 예외가 적용되지 않았습니다');
    }
    if (!foregroundServiceRunning) {
      warnings.add('포그라운드 서비스가 실행 중이 아닙니다');
    }
    if (!backgroundScanTuningApplied) {
      warnings.add('화면 OFF 대응 스캔 설정(setBackgroundMode)이 적용되지 않았습니다');
    }
    if (requiresRuntimeBluetoothPermission && !bluetoothConnect) {
      warnings.add('BLUETOOTH_CONNECT 권한이 없습니다');
    }
    return warnings;
  }

  bool get canScan => blockingReasons.isEmpty;

  ScanDiagnostics copyWith({
    bool? locationWhenInUse,
    bool? locationAlways,
    bool? bluetoothScan,
    bool? bluetoothConnect,
    bool? notification,
    bool? bluetoothOn,
    bool? locationServicesOn,
    bool? ignoringBatteryOptimizations,
    bool? foregroundServiceRunning,
    ScanMode? mode,
    bool? debugForced,
    bool? monitoringSubscribed,
    bool? rangingSubscribed,
    bool? backgroundScanTuningApplied,
    String? targetBeaconUuid,
    int? androidSdkInt,
    DateTime? updatedAt,
    DateTime? lastEnterRegionAt,
    DateTime? lastExitRegionAt,
    DateTime? lastRangingCallbackAt,
    int? rangingCallbackCount,
    int? lastPrearmStatusCode,
    DateTime? lastPrearmAt,
    String? lastPrearmMessage,
    String? lastScanError,
  }) {
    return ScanDiagnostics(
      locationWhenInUse: locationWhenInUse ?? this.locationWhenInUse,
      locationAlways: locationAlways ?? this.locationAlways,
      bluetoothScan: bluetoothScan ?? this.bluetoothScan,
      bluetoothConnect: bluetoothConnect ?? this.bluetoothConnect,
      notification: notification ?? this.notification,
      bluetoothOn: bluetoothOn ?? this.bluetoothOn,
      locationServicesOn: locationServicesOn ?? this.locationServicesOn,
      ignoringBatteryOptimizations:
          ignoringBatteryOptimizations ?? this.ignoringBatteryOptimizations,
      foregroundServiceRunning:
          foregroundServiceRunning ?? this.foregroundServiceRunning,
      mode: mode ?? this.mode,
      debugForced: debugForced ?? this.debugForced,
      monitoringSubscribed: monitoringSubscribed ?? this.monitoringSubscribed,
      rangingSubscribed: rangingSubscribed ?? this.rangingSubscribed,
      backgroundScanTuningApplied:
          backgroundScanTuningApplied ?? this.backgroundScanTuningApplied,
      targetBeaconUuid: targetBeaconUuid ?? this.targetBeaconUuid,
      androidSdkInt: androidSdkInt ?? this.androidSdkInt,
      updatedAt: updatedAt ?? this.updatedAt,
      lastEnterRegionAt: lastEnterRegionAt ?? this.lastEnterRegionAt,
      lastExitRegionAt: lastExitRegionAt ?? this.lastExitRegionAt,
      lastRangingCallbackAt:
          lastRangingCallbackAt ?? this.lastRangingCallbackAt,
      rangingCallbackCount: rangingCallbackCount ?? this.rangingCallbackCount,
      lastPrearmStatusCode: lastPrearmStatusCode ?? this.lastPrearmStatusCode,
      lastPrearmAt: lastPrearmAt ?? this.lastPrearmAt,
      lastPrearmMessage: lastPrearmMessage ?? this.lastPrearmMessage,
      lastScanError: lastScanError ?? this.lastScanError,
    );
  }
}
