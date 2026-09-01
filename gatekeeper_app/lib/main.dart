import 'dart:io';
import 'dart:ui';
import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/material.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';
import 'package:permission_handler/permission_handler.dart';
import 'l10n/generated/app_localizations.dart';
import 'screens/background_disclosure_screen.dart';
import 'screens/smart_key_home_screen.dart';
import 'screens/recovery_shell_screen.dart';
import 'services/background_setup.dart';
import 'services/foreground_service.dart';

import 'services/error_logger.dart';
import 'services/native_wake_registration.dart';
import 'services/update_checker.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // OTA first-run health is independent of permissions, BLE, WebView, scanner,
  // and foreground-service initialization. Never hide it behind those gates.
  await UpdateChecker().reconcilePendingFirstRunHealth();

  FlutterError.onError = (FlutterErrorDetails details) {
    FlutterError.presentError(details);
    AppErrorLogger()
        .logError('UI Framework Error', details.exception, details.stack);
  };

  PlatformDispatcher.instance.onError = (Object error, StackTrace stack) {
    AppErrorLogger().logError('Uncaught App Exception', error, stack);
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
  bool _consentLoaded = false;
  bool _consentBusy = false;
  bool _backgroundRequirementsExplained = false;
  bool _disclosureDeferred = false;
  int _androidSdkInt = 0;
  final BackgroundConsentStore _consentStore = BackgroundConsentStore();
  BackgroundSetupController? _backgroundSetup;
  String _permissionStatus = '권한 및 포그라운드 서비스 준비 중...';
  List<String> _missingRequirements = const [];

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadConsentAndInitialize();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  Future<void> _loadConsentAndInitialize() async {
    try {
      if (Platform.isAndroid) {
        _androidSdkInt = (await DeviceInfoPlugin().androidInfo).version.sdkInt;
      }
      _backgroundSetup = BackgroundSetupController(
        PermissionBackgroundRequirementGateway(androidSdkInt: _androidSdkInt),
      );
      final consentGranted = await _consentStore.isGranted();
      if (consentGranted) {
        _backgroundSetup!.grantConsent();
      }
      if (!mounted) return;
      setState(() {
        _consentLoaded = true;
        _backgroundRequirementsExplained = consentGranted;
      });
      if (consentGranted) {
        await _initializeApp(requestPermissions: false);
      }
    } catch (error, stack) {
      AppErrorLogger().logError('동의 상태 초기화 오류', error, stack);
      if (!mounted) return;
      setState(() {
        _consentLoaded = true;
        _initialized = true;
        _serviceReady = false;
        _disclosureDeferred = true;
        _missingRequirements = const ['백그라운드 설정 동의 상태를 확인할 수 없음'];
        _permissionStatus = '동의 상태 오류 (BACKGROUND_CONSENT_UNAVAILABLE)';
      });
    }
  }

  Future<void> _acceptBackgroundRequirements() async {
    if (_consentBusy || _backgroundSetup == null) return;
    setState(() => _consentBusy = true);
    try {
      await _consentStore.grant();
      _backgroundSetup!.grantConsent();
      if (!mounted) return;
      setState(() {
        _backgroundRequirementsExplained = true;
        _disclosureDeferred = false;
        _initialized = false;
      });
      await _initializeApp(requestPermissions: true);
    } catch (error, stack) {
      AppErrorLogger().logError('백그라운드 설정 동의 처리 오류', error, stack);
      if (!mounted) return;
      setState(() {
        _initialized = true;
        _serviceReady = false;
        _disclosureDeferred = true;
        _missingRequirements = const ['동의 저장 또는 권한 요청 재시도 필요'];
        _permissionStatus = '설정을 완료하지 못했습니다. 다시 시도해주세요.';
      });
    } finally {
      if (mounted) setState(() => _consentBusy = false);
    }
  }

  void _deferBackgroundRequirements() {
    setState(() {
      _disclosureDeferred = true;
      _initialized = true;
      _serviceReady = false;
      _missingRequirements = const ['백그라운드 감지 안내 동의 필요'];
      _permissionStatus = '권한을 요청하지 않았습니다. 수동 복구 기능은 사용할 수 있습니다.';
    });
  }

  Future<void> _retryBackgroundSetup() async {
    if (!_backgroundRequirementsExplained) {
      setState(() => _disclosureDeferred = false);
      return;
    }
    await _initializeApp(requestPermissions: true);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    if (state == AppLifecycleState.resumed &&
        _initialized &&
        _backgroundRequirementsExplained) {
      // 설정 화면에서 "항상 허용"/배터리 예외를 켠 뒤 돌아온 경우 자동 재검사.
      _initializeApp(requestPermissions: false);
    }
  }

  Future<void> _initializeApp({required bool requestPermissions}) async {
    if (_initializing) return;
    _initializing = true;
    try {
      final setup = await _backgroundSetup!.evaluate(
        requestMissing: requestPermissions,
      );
      final locationWhenInUseGranted = setup.locationWhenInUseGranted;

      final missing = <String>[];
      if (!locationWhenInUseGranted) {
        missing.add('위치 권한');
      }
      if (Platform.isAndroid &&
          _androidSdkInt >= 29 &&
          !setup.locationAlwaysGranted) {
        missing.add('백그라운드 위치 권한: 설정에서 “항상 허용” 선택');
      }
      if (!Platform.isAndroid && !setup.locationAlwaysGranted) {
        missing.add('백그라운드 위치 권한: “항상 허용” 선택');
      }
      if (Platform.isAndroid && _androidSdkInt >= 31) {
        if (!await Permission.bluetoothScan.isGranted) {
          missing.add('근처 기기/Bluetooth 스캔 권한');
        }
        if (!await Permission.bluetoothConnect.isGranted) {
          missing.add('Bluetooth 연결 권한');
        }
      }
      if (Platform.isAndroid &&
          _androidSdkInt >= 33 &&
          !await Permission.notification.isGranted) {
        missing.add('알림 권한');
      }

      try {
        if (!await Permission.location.serviceStatus.isEnabled) {
          missing.add('휴대폰 위치 서비스(GPS) 켜기');
        }
      } catch (_) {}

      if (!setup.batteryOptimizationExempt) {
        missing.add('배터리 최적화 사용 안 함');
      }

      final ready = missing.isEmpty;
      if (ready) {
        // Registration is reached from the fresh-install path only after the
        // user-visible permission gate has completed. Publish native ownership
        // and reconcile its OS scan before the foreground service can acquire
        // a legacy lease; the native lease gate remains the cross-process
        // authority if an existing service is already alive.
        if (Platform.isAndroid) {
          try {
            await NativeWakeRegistrationBridge().register();
          } catch (_) {}
        }
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
      AppErrorLogger().logError('앱 초기화 오류', e, stack);
      if (mounted) {
        setState(() {
          _initialized = true;
          _serviceReady = false;
          _missingRequirements = <String>['초기화 오류: APP_INITIALIZATION_FAILED'];
          _permissionStatus = '초기화 오류 발생 (APP_INITIALIZATION_FAILED)';
        });
      }
    } finally {
      _initializing = false;
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
        supportedLocales: AppLocalizations.supportedLocales,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        localeResolutionCallback: (locale, supported) => supported.firstWhere(
          (candidate) => candidate.languageCode == locale?.languageCode,
          orElse: () => supported.last,
        ),
        home: !_consentLoaded
            ? Scaffold(
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
              )
            : !_backgroundRequirementsExplained && !_disclosureDeferred
                ? BackgroundDisclosureScreen(
                    onConsent: _acceptBackgroundRequirements,
                    onDefer: _deferBackgroundRequirements,
                    busy: _consentBusy,
                  )
                : _initialized
                    ? (_serviceReady
                        ? const SmartKeyHomeScreen()
                        : RecoveryShellScreen(
                            status: _permissionStatus,
                            missing: _missingRequirements,
                            onRetrySetup: _retryBackgroundSetup,
                          ))
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
