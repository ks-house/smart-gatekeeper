import 'dart:async';
import 'dart:io';
import 'dart:isolate';
import 'package:flutter/widgets.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:flutter/services.dart';
import 'ble_scanner.dart';
import 'error_logger.dart';

@pragma('vm:entry-point')
void startCallback() {
  FlutterForegroundTask.setTaskHandler(GatekeeperTaskHandler());
}

SendPort? backgroundSendPort;

/// UI isolate에서 보는 서비스/알림 채널 상태다. 서비스 isolate의 진단 값과 분리해
/// Android가 실제로 유지 중인 foreground service와 알림 채널을 표시한다.
class ForegroundServiceHealth {
  const ForegroundServiceHealth({
    required this.running,
    required this.detail,
    required this.updatedAt,
  });

  final bool? running;
  final String detail;
  final DateTime? updatedAt;
}

/// 포그라운드 서비스 isolate 의 태스크 핸들러.
///
/// 실제 BLE 스캔의 유일한 소유자다. UI isolate는 이 서비스가 보내는 상태만
/// 표시하며 flutter_beacon 네이티브 채널을 직접 시작하지 않는다.
class GatekeeperTaskHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, SendPort? sendPort) async {
    backgroundSendPort = sendPort;
    WidgetsFlutterBinding.ensureInitialized();
    debugPrint('[ForegroundTask] 🛡️ 백그라운드 상주 포그라운드 서비스 구동 시작');

    AppErrorLogger().log('🛡️ foreground service 시작');
    sendPort?.send(<String, dynamic>{
      'type': 'ForegroundService',
      'event': 'started',
      'timestamp': timestamp.toIso8601String(),
    });

    try {
      // UI 스레드가 아닌 이 백그라운드 스레드에서 실제 스캐너를 가동한다.
      await BleScanner().initialize();
    } catch (e, stack) {
      AppErrorLogger().logError('foreground service 초기화 실패', e, stack);
      await BleScanner.updateForegroundNotification(
        title: '⚠️ Smart Key 서비스 시작 실패',
        text: '앱 Debug 화면의 오류 로그를 확인해주세요.',
        force: true,
      );
    }
  }

  @override
  Future<void> onRepeatEvent(DateTime timestamp, SendPort? sendPort) async {
    backgroundSendPort = sendPort;
    sendPort?.send(<String, dynamic>{
      'type': 'ForegroundService',
      'event': 'heartbeat',
      'timestamp': timestamp.toIso8601String(),
    });
    try {
      await BleScanner().reloadSavedPreferences();
      await BleScanner().publishServiceState();
    } catch (e, stack) {
      AppErrorLogger().logError('foreground service heartbeat 실패', e, stack);
    }
  }

  @override
  Future<void> onDestroy(DateTime timestamp, SendPort? sendPort) async {
    sendPort?.send(<String, dynamic>{
      'type': 'ForegroundService',
      'event': 'stopped',
      'timestamp': timestamp.toIso8601String(),
    });
    await BleScanner().stopScanning();
    AppErrorLogger().log('foreground service 종료');
    backgroundSendPort = null;
    debugPrint('[ForegroundTask] 백그라운드 서비스 정지');
  }

  @override
  void onNotificationPressed() {
    FlutterForegroundTask.launchApp();
  }
}

class ForegroundServiceManager {
  static const String _notificationChannelId =
      'smart_key_foreground_channel_v2';
  static const MethodChannel _notificationChannel =
      MethodChannel('com.kshouse.gatekeeper_app/notification_channel');

  static ReceivePort? _receivePort;
  static StreamSubscription<dynamic>? _receiveSubscription;
  static final ValueNotifier<ForegroundServiceHealth> health =
      ValueNotifier<ForegroundServiceHealth>(
    const ForegroundServiceHealth(
      running: null,
      detail: '서비스 상태 확인 전',
      updatedAt: null,
    ),
  );

  static Future<void> initForegroundTask() async {
    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        // Android는 이미 생성된 채널의 importance를 바꾸지 않는다. 기존 LOW 채널의
        // 상태바 아이콘 숨김 설정을 피하기 위해 v2 채널을 새로 만든다.
        channelId: _notificationChannelId,
        channelName: 'Smart Key Background Scan Service',
        channelDescription: '화면이 꺼져도 출입문 자동 감지 서비스를 지속 유지합니다.',
        channelImportance: NotificationChannelImportance.DEFAULT,
        priority: NotificationPriority.DEFAULT,
        playSound: false,
        isSticky: true,
        iconData: const NotificationIconData(
          resType: ResourceType.mipmap,
          resPrefix: ResourcePrefix.ic,
          name: 'launcher',
        ),
      ),
      iosNotificationOptions: const IOSNotificationOptions(
        showNotification: true,
        playSound: false,
      ),
      foregroundTaskOptions: const ForegroundTaskOptions(
        interval: 5000,
        isOnceEvent: false,
        autoRunOnBoot: true,
        autoRunOnMyPackageReplaced: true,
        allowWakeLock: true,
        allowWifiLock: true,
      ),
    );
  }

  static Future<void> startService() async {
    // flutter_foreground_task 6.x 계약: 서비스가 SendPort를 받기 전에 UI receive
    // port를 먼저 등록해야 한다. 이 순서가 뒤집히면 UI 로그/진단 IPC가 전부 유실된다.
    if (!await _registerReceivePort()) {
      _setHealth(false, '서비스 IPC 포트 등록 실패');
      throw StateError('foreground service IPC 포트 등록에 실패했습니다.');
    }

    if (await FlutterForegroundTask.isRunningService) {
      // 앱 업데이트/재부팅 자동 실행 서비스는 receive port가 등록되기 전에 시작돼
      // onStart의 SendPort가 null일 수 있다. 포트 등록 후 재시작해야 새 service
      // isolate가 UI 포트를 받아 이벤트·에러 로그를 전달한다.
      AppErrorLogger().log('기존 foreground service 재시작 요청 (IPC 포트 연결)');
      final restarted = await FlutterForegroundTask.restartService();
      if (!restarted) {
        _setHealth(false, '기존 foreground service 재시작 API가 false를 반환했습니다');
        throw StateError('기존 foreground service 재시작에 실패했습니다.');
      }
      await refreshHealth();
      return;
    }

    AppErrorLogger().log('foreground service 시작 요청');
    final started = await FlutterForegroundTask.startService(
      notificationTitle: '💤 저전력 감시 준비 중',
      notificationText: 'SmartGatekeeper 비콘 감지를 시작하고 있습니다...',
      callback: startCallback,
    );
    if (!started) {
      _setHealth(false, 'foreground service 시작 API가 false를 반환했습니다');
      throw StateError('foreground service 시작에 실패했습니다.');
    }

    await refreshHealth();
  }

  static Future<bool> _registerReceivePort() async {
    final newReceivePort = FlutterForegroundTask.receivePort;
    if (newReceivePort == null || identical(_receivePort, newReceivePort)) {
      return newReceivePort != null;
    }

    await _receiveSubscription?.cancel();
    _receivePort?.close();
    _receivePort = newReceivePort;
    _receiveSubscription = newReceivePort.listen((data) {
      if (data is! Map) return;
      final message = Map<String, dynamic>.from(data);
      if (message['type'] == 'BleScanner') {
        BleScanner().syncFromService(message);
      } else if (message['type'] == 'AppErrorLogger') {
        AppErrorLogger().syncFromService(message);
      } else if (message['type'] == 'ForegroundService') {
        final event = message['event'];
        final timestamp = DateTime.tryParse(message['timestamp'] ?? '');
        _setHealth(event != 'stopped', '서비스 $event', timestamp);
      }
    });
    // 이 메서드는 UI isolate에서만 호출한다. backgroundSendPort가 null이어도
    // 콘솔의 ValueNotifier에는 즉시 남으므로 로그 UI 자체와 서비스 IPC를 구분한다.
    AppErrorLogger().log('foreground service IPC 포트 등록 완료');
    return true;
  }

  static Future<void> refreshHealth() async {
    bool running = false;
    try {
      running = await FlutterForegroundTask.isRunningService;
    } catch (e) {
      _setHealth(false, '서비스 상태 조회 실패: $e');
      return;
    }

    try {
      final state = await _notificationChannel.invokeMapMethod<String, dynamic>(
        'getNotificationChannelState',
      );
      final appEnabled = state?['appNotificationsEnabled'] == true;
      final exists = state?['channelExists'] == true;
      final blocked = state?['channelBlocked'] == true;
      final importance = state?['importance'];
      final channelDetail = !appEnabled
          ? '앱 알림이 Android 설정에서 꺼져 있습니다'
          : !exists
              ? 'foreground 알림 채널 생성 대기 중'
              : blocked
                  ? 'foreground 알림 채널이 차단되어 있습니다'
                  : 'foreground 알림 채널 정상 (importance: $importance)';
      _setHealth(running, '$channelDetail · 서비스 ${running ? '실행 중' : '중지됨'}');
    } catch (e) {
      _setHealth(running, '서비스 ${running ? '실행 중' : '중지됨'} · 채널 상태 조회 실패: $e');
    }
  }

  static void _setHealth(bool? running, String detail, [DateTime? updatedAt]) {
    health.value = ForegroundServiceHealth(
      running: running,
      detail: detail,
      updatedAt: updatedAt ?? DateTime.now(),
    );
  }

  static Future<bool> ensureBatteryOptimizationExemption({
    bool requestIfMissing = true,
  }) async {
    if (!Platform.isAndroid) return true;
    try {
      if (await FlutterForegroundTask.isIgnoringBatteryOptimizations) {
        return true;
      }
      if (requestIfMissing) {
        await FlutterForegroundTask.requestIgnoreBatteryOptimization();
      }
      return await FlutterForegroundTask.isIgnoringBatteryOptimizations;
    } catch (e) {
      debugPrint('[ForegroundServiceManager] 배터리 최적화 예외 확인 실패: $e');
      return false;
    }
  }

  static Future<void> stopService() async {
    if (await FlutterForegroundTask.isRunningService) {
      await FlutterForegroundTask.stopService();
    }
    await _receiveSubscription?.cancel();
    _receiveSubscription = null;
    _receivePort?.close();
    _receivePort = null;
    _setHealth(false, '서비스 중지됨');
  }
}
