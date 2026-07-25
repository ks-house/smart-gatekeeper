import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'screens/web_view_screen.dart';
import 'services/ble_scanner.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const SmartKeyApp());
}

class SmartKeyApp extends StatefulWidget {
  const SmartKeyApp({super.key});

  @override
  State<SmartKeyApp> createState() => _SmartKeyAppState();
}

class _SmartKeyAppState extends State<SmartKeyApp> {
  bool _initialized = false;
  String _permissionStatus = '권한 확인 중...';

  @override
  void initState() {
    super.initState();
    _initializeApp();
  }

  Future<void> _initializeApp() async {
    // 1. OS 권한 요청 (위치, 블루투스 스캔/연결, 알림)
    Map<Permission, PermissionStatus> statuses = await [
      Permission.locationWhenInUse,
      Permission.locationAlways,
      Permission.bluetoothScan,
      Permission.bluetoothConnect,
      Permission.notification,
    ].request();

    bool allGranted = true;
    statuses.forEach((permission, status) {
      if (status.isDenied || status.isPermanentlyDenied) {
        allGranted = false;
      }
    });

    // 2. 백그라운드 BLE 스캐너 싱글톤 초기화
    await BleScanner().initialize();

    setState(() {
      _initialized = true;
      _permissionStatus = allGranted ? '모든 권한 승인 완료' : '일부 권한이 거부되었습니다.';
    });
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
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
    );
  }
}
