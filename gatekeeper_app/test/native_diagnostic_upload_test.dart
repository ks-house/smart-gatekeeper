import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:gatekeeper_app/services/native_diagnostic_upload.dart';
import 'package:gatekeeper_app/services/mobile_identity_service.dart';
import 'package:gatekeeper_app/services/field_diagnostics_service.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(() =>
      messenger.setMockMethodCallHandler(NativeDiagnosticUpload.channel, null));

  test(
      'native configuration receives transport but only redacted identity snapshot',
      () async {
    final calls = <MethodCall>[];
    messenger.setMockMethodCallHandler(NativeDiagnosticUpload.channel,
        (call) async {
      calls.add(call);
      return {'supported': true, 'enabled': true, 'pendingUploads': 1};
    });
    final service = MobileIdentityService(
        backendBaseUrl: 'https://example.test/api/v1',
        apiKey: 'test-app-auth',
        deviceIdProvider: () async => 'TEST-INSTALL');
    final response = await service.configureNativeDiagnostics(
        enabled: true,
        identity: MobileIdentityStatus.unavailable,
        sinceEpochMs: 123);
    expect(response?['supported'], true);
    expect(calls.single.method, 'configure');
    final arguments = calls.single.arguments as Map;
    expect(arguments['sinceEpochMs'], 123);
    expect((arguments['identity'] as Map).keys.toSet(), {
      'enrollment_state',
      'access_ready',
      'door_count',
      'target_synced',
      'acl_version',
    });
    expect(arguments['apiKey'], 'test-app-auth');
  });

  test(
      'disable does not require fetching device identity or sending transport credentials',
      () async {
    Map? arguments;
    messenger.setMockMethodCallHandler(NativeDiagnosticUpload.channel,
        (call) async {
      arguments = call.arguments as Map;
      return {'supported': true, 'enabled': false};
    });
    await MobileIdentityService(
        deviceIdProvider: () async =>
            throw StateError('must not be called')).configureNativeDiagnostics(
        enabled: false,
        identity: MobileIdentityStatus.unavailable,
        sinceEpochMs: 0);
    expect(arguments?['enabled'], false);
    expect(arguments?.containsKey('apiKey'), false);
    expect(arguments?.containsKey('deviceId'), false);
  });

  test(
      'clear retires native report queue but preserves authorization preferences and consent',
      () async {
    SharedPreferences.setMockInitialValues(
        {'credential': 'keep', 'field_diagnostics_upload_enabled_v1': true});
    final methods = <String>[];
    messenger.setMockMethodCallHandler(NativeDiagnosticUpload.channel,
        (call) async {
      methods.add(call.method);
      return {'supported': true};
    });
    await FieldDiagnosticsStore()
        .clearReportHistory(now: DateTime.fromMillisecondsSinceEpoch(321));
    final prefs = await SharedPreferences.getInstance();
    expect(methods, ['clear']);
    expect(prefs.getString('credential'), 'keep');
    expect(prefs.getBool('field_diagnostics_upload_enabled_v1'), true);
    expect(await FieldDiagnosticsStore().reportSinceEpochMs(), 321);
  });

  test(
      'missing native plugin falls back but configuration failures are not hidden',
      () async {
    messenger.setMockMethodCallHandler(NativeDiagnosticUpload.channel,
        (_) async => throw MissingPluginException());
    expect(await NativeDiagnosticUpload().configure({'enabled': true}), isNull);
    messenger.setMockMethodCallHandler(NativeDiagnosticUpload.channel,
        (_) async => throw PlatformException(code: 'STORE_FAILED'));
    await expectLater(NativeDiagnosticUpload().configure({'enabled': true}),
        throwsA(isA<PlatformException>()));
  });
}
