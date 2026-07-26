import 'dart:async';
import 'dart:io';
import 'dart:isolate';
import 'package:flutter/widgets.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';


import 'ble_scanner.dart';

@pragma('vm:entry-point')
void startCallback() {
  FlutterForegroundTask.setTaskHandler(GatekeeperTaskHandler());
}

class GatekeeperTaskHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, SendPort? sendPort) async {
    WidgetsFlutterBinding.ensureInitialized();
    debugPrint('[ForegroundTask] 🛡️ 백그라운드 상주 포그라운드 서비스 구동 시작');
    await BleScanner().initialize();
    await BleScanner().startScanning(forceRestart: true);
  }

  @override
  Future<void> onRepeatEvent(DateTime timestamp, SendPort? sendPort) async {
    if (!BleScanner().isScanning) {
      debugPrint('[ForegroundTask] 🔄 백그라운드 스캔 상태 재점검 -> 스캐닝 강제 재시작');
      await BleScanner().startScanning(forceRestart: true);
    }
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
      if (!await FlutterForegroundTask.isIgnoringBatteryOptimizations) {
        await FlutterForegroundTask.requestIgnoreBatteryOptimization();
      }
    }

    await FlutterForegroundTask.startService(
      notificationTitle: '🔴 Target 비콘 연결 안됨 (탐색 중)',
      notificationText: 'SmartGatekeeper 비콘 신호를 찾는 중입니다...',
      callback: startCallback,
    );

  }
}
