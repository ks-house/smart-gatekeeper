import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:permission_handler/permission_handler.dart';
import 'screens/web_view_screen.dart';
import 'services/ble_scanner.dart';
import 'services/foreground_service.dart';

import 'services/error_logger.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  FlutterError.onError = (FlutterErrorDetails details) {
    FlutterError.presentError(details);
    AppErrorLogger().logError('UI Framework Error: ${details.exception}', details.exception, details.stack);
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
  String _permissionStatus = '권한 및 포그라운드 서비스 준비 중...';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initializeApp();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    // BleScanner 워치독 및 생명주기는 이제 백그라운드 isolate 에서 자체 관리됩니다.
  }

  Future<void> _initializeApp() async {
    try {
      // 1. OS 필수 권한 요청 (위치, 블루투스 스캔/연결, 알림)
      Map<Permission, PermissionStatus> statuses = await [
        Permission.locationWhenInUse,
        Permission.bluetoothScan,
        Permission.bluetoothConnect,
        Permission.notification,
      ].request();

      if (await Permission.locationWhenInUse.isGranted) {
        if (!await Permission.locationAlways.isGranted) {
          await Permission.locationAlways.request();
        }
      }

      bool allGranted = true;
      statuses.forEach((permission, status) {
        if (status.isDenied || status.isPermanentlyDenied) {
          allGranted = false;
        }
      });

      // 2. 포그라운드 서비스를 먼저 띄운다 (issue.md P0-4).
      // 백그라운드 서비스 내부에서 BleScanner가 초기화되고 동작을 시작한다.
      await ForegroundServiceManager.startService();

      if (mounted) {
        setState(() {
          _initialized = true;
          _permissionStatus = allGranted ? '모든 권한 승인 완료' : '일부 권한이 거부되었습니다.';
        });
      }
    } catch (e, stack) {
      debugPrint('[SmartKeyApp] 초기화 예외: $e');
      AppErrorLogger().logError('앱 초기화 오류', e, stack);
      if (mounted) {
        setState(() {
          _initialized = true;
          _permissionStatus = '초기화 오류 발생 ($e)';
        });
      }
    }
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
            ? const WebViewScreen()
            : Scaffold(
                body: Center(
                  child: Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const CircularProgressIndicator(),
                      const SizedBox(height: 16),
                      Text(
                        _permissionStatus,
                        style: const TextStyle(fontSize: 16, color: Colors.white70),
                      ),
                    ],
                  ),
                ),
              ),
      ),
    );
  }
}
