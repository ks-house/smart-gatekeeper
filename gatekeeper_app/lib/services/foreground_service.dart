import 'dart:async';
import 'dart:io';
import 'dart:isolate';
import 'package:flutter/widgets.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';

@pragma('vm:entry-point')
void startCallback() {
  FlutterForegroundTask.setTaskHandler(GatekeeperTaskHandler());
}

class GatekeeperTaskHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, SendPort? sendPort) async {
    WidgetsFlutterBinding.ensureInitialized();
    debugPrint('[ForegroundTask] 🛡️ 백그라운드 상주 포그라운드 서비스 구동 시작');
  }

  @override
  Future<void> onRepeatEvent(DateTime timestamp, SendPort? sendPort) async {
    // Keep background service alive and wake lock maintained
  }


  @override
  Future<void> onDestroy(DateTime timestamp, SendPort? sendPort) async {
    debugPrint('[ForegroundTask] 백그라운드 서비스 정지');
  }

  @override
  void onNotificationPressed() {
    FlutterForegroundTask.launchApp();
  }
}

class ForegroundServiceManager {
  static Future<void> initForegroundTask() async {
    FlutterForegroundTask.init(
      androidNotificationOptions: AndroidNotificationOptions(
        channelId: 'smart_key_foreground_channel',
        channelName: 'Smart Key Background Scan Service',
        channelDescription: '화면이 꺼져도 출입문 자동 감지 서비스를 지속 유지합니다.',
        channelImportance: NotificationChannelImportance.LOW,
        priority: NotificationPriority.LOW,
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
        allowWakeLock: true,
        allowWifiLock: true,
      ),
    );
  }

  static Future<void> startService() async {
    if (await FlutterForegroundTask.isRunningService) {
      return;
    }

    // 안드로이드 배터리 최적화 제외 요청 (화면 OFF / Doze 모드 극복)
    if (Platform.isAndroid) {
      try {
        if (!await FlutterForegroundTask.isIgnoringBatteryOptimizations) {
          await FlutterForegroundTask.requestIgnoreBatteryOptimization();
        }
      } catch (e) {
        debugPrint('[ForegroundServiceManager] 배터리 최적화 요청 예외 (무시 후 계속 진행): $e');
      }
    }

    await FlutterForegroundTask.startService(
      notificationTitle: '🔴 Target 비콘 연결 안됨 (탐색 중)',
      notificationText: 'SmartGatekeeper 비콘 신호를 찾는 중입니다...',
      callback: startCallback,
    );

  }
}
