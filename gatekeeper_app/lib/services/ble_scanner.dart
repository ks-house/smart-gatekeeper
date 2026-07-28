import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter_beacon/flutter_beacon.dart';

import 'device_id_service.dart';
import 'update_checker.dart';

class BleScanner {
  static final BleScanner _instance = BleScanner._internal();
  factory BleScanner() => _instance;
  BleScanner._internal();

  final String backendBaseUrl = const String.fromEnvironment('BACKEND_URL',
      defaultValue: 'https://tworimpa.synology.me:4442/api/v1');

  String targetBeaconUuid = 'a1b2c3d4-e5f6-7890-abcd-ef1234567890';
  bool ignoreCooldown = false;
  int rssiThreshold = -75;
  int cooldownSeconds = 10;

  final ValueNotifier<int?> liveRssi = ValueNotifier<int?>(null);
  final ValueNotifier<DateTime?> lastRssiUpdateTime = ValueNotifier<DateTime?>(null);
  final ValueNotifier<int> packetCount = ValueNotifier<int>(0);
  final ValueNotifier<bool> isBeaconConnected = ValueNotifier<bool>(false);

  DateTime? _lastPrearmTime;
  DateTime? _lastArmSuccessTime;
  Timer? _timeoutTimer;
  bool _isPrearmInProgress = false;

  bool _isScanning = false;
  StreamSubscription<MonitoringResult>? _streamMonitoring;
  StreamSubscription<RangingResult>? _streamRanging;

  bool get isScanning => _isScanning;

  void _updateNotification({required String title, required String text}) {
    try {
      FlutterForegroundTask.updateService(
        notificationTitle: title,
        notificationText: text,
      );
    } catch (e) {
      debugPrint('[BleScanner] Notification update error: $e');
    }
  }

  Future<void> loadSavedPreferences() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      ignoreCooldown = prefs.getBool('ignore_cooldown') ?? false;
      rssiThreshold = prefs.getInt('rssi_threshold') ?? -75;
      cooldownSeconds = prefs.getInt('cooldown_seconds') ?? 10;
    } catch (e) {
      debugPrint('[BleScanner] SharedPreferences 로드 실패: $e');
    }
  }

  Future<void> setCooldownSeconds(int value) async {
    cooldownSeconds = value;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt('cooldown_seconds', value);
    } catch (_) {}
  }

  Future<void> setIgnoreCooldown(bool value) async {
    ignoreCooldown = value;
    _lastPrearmTime = DateTime.now(); // 리셋
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setBool('ignore_cooldown', value);
    } catch (_) {}
  }

  Future<void> setRssiThreshold(int value) async {
    rssiThreshold = value;
    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setInt('rssi_threshold', value);
    } catch (_) {}
  }

  void _startTimeoutCheckTimer() {
    _timeoutTimer?.cancel();
    _timeoutTimer = Timer.periodic(const Duration(milliseconds: 1000), (timer) {
      if (lastRssiUpdateTime.value != null) {
        final elapsedMs = DateTime.now().difference(lastRssiUpdateTime.value!).inMilliseconds;
        if (elapsedMs > 3000) {
          if (isBeaconConnected.value || liveRssi.value != null) {
            liveRssi.value = null;
            isBeaconConnected.value = false;
            debugPrint('[BleScanner] ⚠️ Target 비콘 신호 미수신 (3초 초과) -> 저전력 감시 모드 유지');
            _updateNotification(
              title: '💤 Target 비콘 구역 수면 감시 중 (저전력 모드)',
              text: 'Target 비콘 구역 접근 시 OS가 자동으로 비콘을 감지합니다.',
            );
          }
        }
      } else {
        if (isBeaconConnected.value) {
          isBeaconConnected.value = false;
          _updateNotification(
            title: '💤 Target 비콘 구역 수면 감시 중 (저전력 모드)',
            text: 'Target 비콘 구역 접근 시 OS가 자동으로 비콘을 감지합니다.',
          );
        }
      }
    });
  }

  Future<void> initialize() async {
    await loadSavedPreferences();
    await fetchRemoteConfig();
    await UpdateChecker().checkForUpdates();
    startScanning();
  }

  Future<void> fetchRemoteConfig() async {
    try {
      final response = await http
          .get(Uri.parse('$backendBaseUrl/config'))
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        if (data['beacon_uuid'] != null) {
          targetBeaconUuid = data['beacon_uuid'].toString().toLowerCase();
        }
        if (data['cooldown_sec'] != null) {
          cooldownSeconds = data['cooldown_sec'];
        }

        final apkVersionUrl = data['apk_version_url']?.toString();
        final apkDownloadUrl = data['apk_download_url']?.toString();
        if (apkVersionUrl != null && apkVersionUrl.isNotEmpty) {
          await UpdateChecker().checkForUpdates(
            customVersionUrl: apkVersionUrl,
            customDownloadUrl: apkDownloadUrl,
          );
        }
      }
    } catch (e) {
      debugPrint('[BleScanner] Remote Config 로드 실패 (기본값 사용): $e');
    }
  }

  Future<void> startScanning({bool forceRestart = false}) async {
    if (_isScanning && !forceRestart) return;

    if (forceRestart) {
      _isScanning = false;
      _timeoutTimer?.cancel();
      liveRssi.value = null;
      isBeaconConnected.value = false;
      await _streamRanging?.cancel();
      await _streamMonitoring?.cancel();
    }

    try {
      await flutterBeacon.initializeScanning;
    } catch (e) {
      debugPrint('[BleScanner] flutterBeacon 초기화 실패: $e');
      _updateNotification(
        title: '⚠️ BLE 비콘 스캔 초기화 실패',
        text: '블루투스/위치 서비스 또는 권한 상태를 확인해주세요 ($e)',
      );
      return;
    }

    _isScanning = true;
    debugPrint('[BleScanner] 🛡️ iBeacon 저전력 OS 구역 감시(Monitoring) 시작... (Target UUID: $targetBeaconUuid)');
    _updateNotification(
      title: '💤 Target 비콘 구역 수면 감시 중 (저전력 모드)',
      text: 'Target 비콘 구역 접근 시 OS가 자동으로 비콘을 감지합니다.',
    );

    final regions = <Region>[
      Region(identifier: 'SmartGatekeeper', proximityUUID: targetBeaconUuid),
    ];

    // 1. OS iBeacon Region Monitoring 구독 (저전력 구역 진입 깨우기)
    _streamMonitoring?.cancel();
    _streamMonitoring = flutterBeacon.monitoring(regions).listen(
      (MonitoringResult result) {
        if (result.monitoringEventType == MonitoringEventType.didEnterRegion) {
          debugPrint('[BleScanner] 🔔 OS didEnterRegion 감지! (Target 비콘 구역 진입) -> Ranging 스캔 개시');
          scheduleMicrotask(() {
            _startRangingStream(regions);
          });
        } else if (result.monitoringEventType == MonitoringEventType.didExitRegion) {
          debugPrint('[BleScanner] 🚪 OS didExitRegion 감지! (Target 비콘 구역 이탈) -> Ranging 정지 및 저전력 감시 모드 복귀');
          _stopRangingStream();
        }
      },
      onError: (dynamic error) {
        debugPrint('[BleScanner] ⚠️ Monitoring stream error: $error');
      },
    );

    // 2. 초기 기동 시 즉시 Ranging 스트림 활성화 (앱 실행 직후 즉시 비콘 패킷 수집)
    _startRangingStream(regions);
  }

  void _startRangingStream(List<Region> regions) {
    if (_streamRanging != null) return; // 이미 Ranging 스트림 구독 중이면 중복 생성 방지 (네이티브 바인딩 충돌 예방)

    _streamRanging = flutterBeacon.ranging(regions).listen(
      (RangingResult result) {
        if (result.beacons.isNotEmpty) {
          for (var beacon in result.beacons) {
            _processBeacon(beacon);
          }
        }
      },
      onError: (dynamic error) {
        debugPrint('[BleScanner] ⚠️ Ranging stream error: $error');
      },
    );

    _startTimeoutCheckTimer();
  }

  void _stopRangingStream() {
    _streamRanging?.cancel();
    _streamRanging = null;
    liveRssi.value = null;
    isBeaconConnected.value = false;
    _updateNotification(
      title: '💤 Target 비콘 구역 수면 감시 중 (저전력 모드)',
      text: 'Target 비콘 구역 접근 시 OS가 자동으로 비콘을 감지합니다.',
    );
  }

  void _processBeacon(Beacon beacon) {
    if (beacon.proximityUUID.toLowerCase() != targetBeaconUuid.toLowerCase()) return;
    final int rssi = beacon.rssi;
    if (rssi == 0 || rssi == -1) return; // Invalid RSSI

    liveRssi.value = rssi;
    lastRssiUpdateTime.value = DateTime.now();
    isBeaconConnected.value = true;
    packetCount.value++;

    if (_isPrearmInProgress) return;

    final isRecentArm = _lastArmSuccessTime != null &&
        DateTime.now().difference(_lastArmSuccessTime!).inSeconds < 4;

    if (rssi < rssiThreshold) {
      if (!isRecentArm) {
        _updateNotification(
          title: '🟡 Target 비콘 신호 약함 ($rssi dBm)',
          text: '센서 근접 필요 (현재: $rssi dBm / 기준: $rssiThreshold dBm)',
        );
      }
      return;
    }

    final now = DateTime.now();
    if (!ignoreCooldown && _lastPrearmTime != null) {
      final difference = now.difference(_lastPrearmTime!).inSeconds;
      if (difference < cooldownSeconds) {
        final remainSec = cooldownSeconds - difference;
        if (!isRecentArm) {
          _updateNotification(
            title: '⏳ 출입 쿨다운 대기 중 ($remainSec초)',
            text: 'Target 비콘 감지됨 ($rssi dBm) — 연속 개방 방지 대기 중',
          );
        }
        return;
      }
    }

    _lastPrearmTime = now;
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
            },
            body: jsonEncode({
              'beacon_uuid': targetBeaconUuid,
              'device_id': deviceId,
              'rssi': rssi,
              'timestamp': DateTime.now().toIso8601String(),
            }),
          )
          .timeout(const Duration(seconds: 4));

      if (response.statusCode == 200) {
        _lastArmSuccessTime = DateTime.now();
        _updateNotification(
          title: '🟢 Smart Key 출입문 승인 완료!',
          text: 'Target 비콘 감지 ($rssi dBm) → ToF 센서로 다가가면 문이 열립니다!',
        );
      } else if (response.statusCode == 403) {
        _updateNotification(
          title: '⛔ 출입 권한 거부/미승인',
          text: '관리자 승인이 필요한 세입자 기기입니다.',
        );
      } else {
        _updateNotification(
          title: '⚠️ 출입 승인 실패 (HTTP ${response.statusCode})',
          text: '서버 통신 오류가 발생했습니다.',
        );
      }
    } catch (e) {
      debugPrint('[BleScanner] Pre-arm API 통신 오류: $e');
    } finally {
      _isPrearmInProgress = false;
    }
  }

  Future<void> stopScanning() async {
    _isScanning = false;
    _timeoutTimer?.cancel();
    liveRssi.value = null;
    isBeaconConnected.value = false;
    await _streamRanging?.cancel();
    await _streamMonitoring?.cancel();
    debugPrint('[BleScanner] 비콘 스캐닝 중지됨.');
    _updateNotification(
      title: '⏹️ Target 비콘 감지 중지됨',
      text: '스캔 서비스가 일시 정지되었습니다.',
    );
  }
}
