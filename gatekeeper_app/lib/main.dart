import 'dart:io';
import 'dart:ui';
import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/material.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:permission_handler/permission_handler.dart';
import 'screens/web_view_screen.dart';
import 'services/foreground_service.dart';

import 'services/error_logger.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  FlutterError.onError = (FlutterErrorDetails details) {
    FlutterError.presentError(details);
    AppErrorLogger().logError('UI Framework Error: ${details.exception}',
        details.exception, details.stack);
  };

  PlatformDispatcher.instance.onError = (Object error, StackTrace stack) {
    AppErrorLogger().logError('Uncaught App Exception: $error', error, stack);
    return true;
  };

  await ForegroundServiceManager.initForegroundTask();
  runApp(const SmartKeyApp());
}

class SmartKeyApp extends StatefulWidget {
  const SmartKeyApp({super.key});

  @override
  State<SmartKeyApp> createState() => _SmartKeyAppState();
}

class _SmartKeyAppState extends State<SmartKeyApp> with WidgetsBindingObserver {
  bool _initialized = false;
  bool _serviceReady = false;
  bool _initializing = false;
  bool _backgroundRequirementsExplained = false;
  String _permissionStatus = '권한 및 포그라운드 서비스 준비 중...';
  List<String> _missingRequirements = const [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initializeApp(requestPermissions: true);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    if (state == AppLifecycleState.resumed && _initialized) {
      // 설정 화면에서 "항상 허용"/배터리 예외를 켠 뒤 돌아온 경우 자동 재검사.
      _initializeApp(requestPermissions: false);
    }
  }

  Future<void> _initializeApp({required bool requestPermissions}) async {
    if (_initializing) return;
    _initializing = true;
    try {
      var androidSdkInt = 0;
      if (Platform.isAndroid) {
        androidSdkInt = (await DeviceInfoPlugin().androidInfo).version.sdkInt;
      }

      if (requestPermissions) {
        final permissions = <Permission>[Permission.locationWhenInUse];
        if (!Platform.isAndroid || androidSdkInt >= 31) {
          permissions.addAll([
            Permission.bluetoothScan,
            Permission.bluetoothConnect,
          ]);
        }
        if (!Platform.isAndroid || androidSdkInt >= 33) {
          permissions.add(Permission.notification);
        }
        await permissions.request();
      }

      final locationWhenInUseGranted =
          await Permission.locationWhenInUse.isGranted;
      if (requestPermissions &&
          locationWhenInUseGranted &&
          _backgroundRequirementsExplained &&
          (!Platform.isAndroid || androidSdkInt >= 29)) {
        if (!await Permission.locationAlways.isGranted) {
          await Permission.locationAlways.request();
        }
      }

      final missing = <String>[];
      if (!locationWhenInUseGranted) {
        missing.add('위치 권한');
      }
      if (Platform.isAndroid &&
          androidSdkInt >= 29 &&
          !await Permission.locationAlways.isGranted) {
        missing.add('백그라운드 위치 권한: 설정에서 “항상 허용” 선택');
      }
      if (!Platform.isAndroid && !await Permission.locationAlways.isGranted) {
        missing.add('백그라운드 위치 권한: “항상 허용” 선택');
      }
      if (Platform.isAndroid && androidSdkInt >= 31) {
        if (!await Permission.bluetoothScan.isGranted) {
          missing.add('근처 기기/Bluetooth 스캔 권한');
        }
        if (!await Permission.bluetoothConnect.isGranted) {
          missing.add('Bluetooth 연결 권한');
        }
      }
      if (Platform.isAndroid &&
          androidSdkInt >= 33 &&
          !await Permission.notification.isGranted) {
        missing.add('알림 권한');
      }

      try {
        if (!await Permission.location.serviceStatus.isEnabled) {
          missing.add('휴대폰 위치 서비스(GPS) 켜기');
        }
      } catch (_) {}

      final batteryExempt =
          await ForegroundServiceManager.ensureBatteryOptimizationExemption(
        requestIfMissing:
            requestPermissions && _backgroundRequirementsExplained,
      );
      if (!batteryExempt) {
        missing.add('배터리 최적화 사용 안 함');
      }

      final ready = missing.isEmpty;
      if (ready) {
        await ForegroundServiceManager.startService();
      } else {
        // 권한이 부족한데도 "감시 중" 알림만 남는 오해를 방지한다.
        await ForegroundServiceManager.stopService();
      }

      if (mounted) {
        setState(() {
          _initialized = true;
          _serviceReady = ready;
          _missingRequirements = missing;
          _permissionStatus =
              ready ? '백그라운드 출입 감지 준비 완료' : '필수 설정 ${missing.length}개를 완료해주세요.';
        });
      }
    } catch (e, stack) {
      debugPrint('[SmartKeyApp] 초기화 예외: $e');
      AppErrorLogger().logError('앱 초기화 오류', e, stack);
      if (mounted) {
        setState(() {
          _initialized = true;
          _serviceReady = false;
          _missingRequirements = <String>['초기화 오류: $e'];
          _permissionStatus = '초기화 오류 발생 ($e)';
        });
      }
    } finally {
      _initializing = false;
    }
  }

  Widget _buildSetupScreen() {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Center(
            child: SingleChildScrollView(
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Icon(Icons.phonelink_lock,
                      size: 72, color: Colors.amber),
                  const SizedBox(height: 20),
                  const Text(
                    '백그라운드 스마트키 설정 필요',
                    textAlign: TextAlign.center,
                    style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    _permissionStatus,
                    textAlign: TextAlign.center,
                    style: const TextStyle(color: Colors.white70),
                  ),
                  const SizedBox(height: 20),
                  ..._missingRequirements.map(
                    (item) => ListTile(
                      dense: true,
                      leading:
                          const Icon(Icons.error_outline, color: Colors.amber),
                      title: Text(item),
                    ),
                  ),
                  const SizedBox(height: 12),
                  FilledButton.icon(
                    onPressed: _initializing
                        ? null
                        : () {
                            _backgroundRequirementsExplained = true;
                            _initializeApp(requestPermissions: true);
                          },
                    icon: const Icon(Icons.security),
                    label: const Text('필수 권한·배터리 예외 다시 요청'),
                  ),
                  const SizedBox(height: 8),
                  OutlinedButton.icon(
                    onPressed: openAppSettings,
                    icon: const Icon(Icons.settings),
                    label: const Text('앱 권한 설정 열기'),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    '삼성: 설정 > 배터리 > 백그라운드 사용 제한에서 이 앱을 '
                    '절전 앱에서 제외하세요.\n'
                    '샤오미: 자동 시작 허용 및 배터리 절약을 “제한 없음”으로 설정하세요.',
                    style: TextStyle(fontSize: 12, color: Colors.white54),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return WithForegroundTask(
      child: MaterialApp(
        title: 'Smart Key',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF1E88E5),
            brightness: Brightness.dark,
          ),
          useMaterial3: true,
        ),
        home: _initialized
            ? (_serviceReady ? const WebViewScreen() : _buildSetupScreen())
            : Scaffold(
                body: Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const CircularProgressIndicator(),
                      const SizedBox(height: 16),
                      Text(
                        _permissionStatus,
                        style: const TextStyle(
                            fontSize: 16, color: Colors.white70),
                      ),
                    ],
                  ),
                ),
              ),
      ),
    );
  }
}
