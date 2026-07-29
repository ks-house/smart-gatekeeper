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

/// 포그라운드 서비스 isolate 의 태스크 핸들러.
///
/// ⚠️ **현재 실제 BLE 스캔은 이 isolate 가 아니라 UI isolate 의
/// [BleScanner] 싱글톤에서 수행된다** (issue.md P0-4).
///
/// 이 서비스의 역할은 프로세스를 포그라운드 우선순위로 유지해
/// UI isolate 의 FlutterEngine 이 살아 있게 하고, 알림을 통해 상태를
/// 표시하는 것이다. 그 결과 다음 한계가 남는다:
///
/// * Activity 가 **파괴**되면 UI isolate 의 엔진도 사라져 스캔이 멈춘다.
///   ("활동 유지 안 함" 개발자 옵션, 강한 메모리 압박, 스와이프 종료)
/// * 화면 OFF 나 일반적인 백그라운드 전환은 Activity 를 파괴하지 않으므로
///   영향받지 않는다.
///
/// 완전한 해결책은 스캐너를 이 isolate 로 옮기고 `sendDataToMain` /
/// `sendDataToTask` 로 UI 와 통신하는 것이다(issue.md P0-4 안 A).
/// 그때까지는 [BleScanner] 내부의 30초 워치독과 앱 복귀 훅이 안전망 역할을 한다.
class GatekeeperTaskHandler extends TaskHandler {
  @override
  Future<void> onStart(DateTime timestamp, SendPort? sendPort) async {
    WidgetsFlutterBinding.ensureInitialized();
    debugPrint('[ForegroundTask] 🛡️ 백그라운드 상주 포그라운드 서비스 구동 시작');
    
    // UI 스레드가 아닌 이 백그라운드 스레드에서 실제 스캐너를 가동한다.
    await BleScanner().initialize();
  }

  @override
  Future<void> onRepeatEvent(DateTime timestamp, SendPort? sendPort) async {
    // BleScanner 내부 워치독이 스스로 돌아가므로 여기서 따로 호출하지 않아도 된다.
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
      notificationTitle: '💤 저전력 감시 준비 중',
      notificationText: 'SmartGatekeeper 비콘 감지를 시작하고 있습니다...',
      callback: startCallback,
    );

    // 백그라운드 스레드에서 올라오는 이벤트를 수신하여 UI 스레드의 상태를 동기화한다.
    FlutterForegroundTask.receivePort?.listen((data) {
      if (data is Map<String, dynamic>) {
        if (data['type'] == 'BleScanner') {
          BleScanner().syncFromMain(data);
        } else if (data['type'] == 'AppErrorLogger') {
          AppErrorLogger().syncFromMain(data);
        }
      }
    });
  }
}
