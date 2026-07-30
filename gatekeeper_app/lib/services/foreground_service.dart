import 'dart:async';
import 'dart:io';
import 'dart:isolate';
import 'package:flutter/widgets.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'ble_scanner.dart';
import 'error_logger.dart';

@pragma('vm:entry-point')
void startCallback() {
  FlutterForegroundTask.setTaskHandler(GatekeeperTaskHandler());
}

SendPort? backgroundSendPort;

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

    // UI 스레드가 아닌 이 백그라운드 스레드에서 실제 스캐너를 가동한다.
    await BleScanner().initialize();
  }

  @override
  Future<void> onRepeatEvent(DateTime timestamp, SendPort? sendPort) async {
    backgroundSendPort = sendPort;
    await BleScanner().reloadSavedPreferences();
    await BleScanner().publishServiceState();
  }

  @override
  Future<void> onDestroy(DateTime timestamp, SendPort? sendPort) async {
    await BleScanner().stopScanning();
    backgroundSendPort = null;
    debugPrint('[ForegroundTask] 백그라운드 서비스 정지');
  }

  @override
  void onNotificationPressed() {
    FlutterForegroundTask.launchApp();
  }
}

class ForegroundServiceManager {
  static ReceivePort? _receivePort;
  static StreamSubscription<dynamic>? _receiveSubscription;

  static Future<void> initForegroundTask() async {
    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'smart_key_foreground_channel',
        channelName: 'Smart Key Background Scan Service',
        channelDescription: '화면이 꺼져도 출입문 자동 감지 서비스를 지속 유지합니다.',
        channelImportance: NotificationChannelImportance.LOW,
        priority: NotificationPriority.LOW,
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
    if (await FlutterForegroundTask.isRunningService) {
      await _registerReceivePort();
      return;
    }

    final started = await FlutterForegroundTask.startService(
      notificationTitle: '💤 저전력 감시 준비 중',
      notificationText: 'SmartGatekeeper 비콘 감지를 시작하고 있습니다...',
      callback: startCallback,
    );
    if (!started) {
      throw StateError('foreground service 시작에 실패했습니다.');
    }

    await _registerReceivePort();
  }

  static Future<void> _registerReceivePort() async {
    final newReceivePort = FlutterForegroundTask.receivePort;
    if (newReceivePort == null || identical(_receivePort, newReceivePort)) {
      return;
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
      }
    });
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
  }
}
