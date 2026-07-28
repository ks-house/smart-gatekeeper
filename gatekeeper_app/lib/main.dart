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

class _SmartKeyAppState extends State<SmartKeyApp> {
  bool _initialized = false;
  String _permissionStatus = '권한 및 포그라운드 서비스 준비 중...';

  @override
  void initState() {
    super.initState();
    _initializeApp();
  }

  Future<void> _initializeApp() async {
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

    // 2. 백그라운드 BLE 스캐너 초기화 및 포그라운드 서비스 시작
    await BleScanner().initialize();
    await ForegroundServiceManager.startService();

    if (mounted) {
      setState(() {
        _initialized = true;
        _permissionStatus = allGranted ? '모든 권한 승인 완료' : '일부 권한이 거부되었습니다.';
      });
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
