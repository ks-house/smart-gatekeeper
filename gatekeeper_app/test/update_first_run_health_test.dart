import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/update_checker.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel(
    'com.kshouse.gatekeeper_app/update_security',
  );
  const artifact =
      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
  const certificate =
      'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';

  Map<String, Object> pending() => <String, Object>{
        'update_pending_health_path': '/verified/candidate.apk',
        'update_pending_build_number': 42,
        'update_pending_version_name': '1.2.3',
        'update_pending_artifact_sha256': artifact,
        'update_pending_certificate_sha256': certificate,
        'update_pending_commit': '1234567890abcdef1234567890abcdef12345678',
        'update_pending_requested_at': '2026-08-09T00:00:00Z',
      };

  tearDown(() async {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, null);
  });

  test('matching installed identity confirms health and clears pending state',
      () async {
    SharedPreferences.setMockInitialValues(pending());
    MethodCall? observed;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(channel, (call) async {
      observed = call;
      return <String, Object>{
        'buildNumber': 42,
        'versionName': '1.2.3',
        'sourceSha256': artifact,
        'certificateSha256': certificate,
      };
    });

    final checker = UpdateChecker();
    await checker.reconcilePendingFirstRunHealth();

    expect(observed?.method, 'installedPackageIdentity');
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getBool('update_first_run_healthy'), isTrue);
    expect(prefs.getInt('update_pending_build_number'), isNull);
    expect(checker.state, UpdateState.healthy);
  });

  test('artifact mismatch remains pending and is never reported as latest',
      () async {
    SharedPreferences.setMockInitialValues(pending());
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
            channel,
            (_) async => <String, Object>{
                  'buildNumber': 42,
                  'versionName': '1.2.3',
                  'sourceSha256':
                      'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
                  'certificateSha256': certificate,
                });

    final checker = UpdateChecker();
    await checker.reconcilePendingFirstRunHealth();

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getBool('update_first_run_healthy'), isFalse);
    expect(prefs.getString('update_first_run_reason'),
        'INSTALLED_ARTIFACT_MISMATCH');
    expect(prefs.getInt('update_pending_build_number'), 42);
    expect(checker.state, UpdateState.failed);
    expect(
      updateStatusMessage(
        checker.state,
        failureReason: checker.lastFailureReason,
      ),
      isNot(contains('최신')),
    );
  });

  test('only a confirmed healthy state may claim latest', () {
    for (final state in UpdateState.values) {
      final message = updateStatusMessage(
        state,
        version: '1.2.3',
        failureReason: 'REJECTED',
      );
      if (state == UpdateState.healthy) {
        expect(message, contains('최신'));
      } else {
        expect(message, isNot(contains('최신')), reason: '$state: $message');
      }
    }
  });
}
