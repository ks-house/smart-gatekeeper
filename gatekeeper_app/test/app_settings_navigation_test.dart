import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('normal user and recovery routes hide installer controls', () {
    final settings =
        File('lib/screens/app_settings_screen.dart').readAsStringSync();
    final home =
        File('lib/screens/smart_key_home_screen.dart').readAsStringSync();
    final webView = File('lib/screens/web_view_screen.dart').readAsStringSync();
    final recovery =
        File('lib/screens/recovery_shell_screen.dart').readAsStringSync();

    expect(settings, contains("title: const Text('고급 진단')"));
    expect(settings, contains("text: '고급 제어'"));
    expect(settings, contains("text: '진단·튜닝'"));
    expect(settings, contains('SmartKeyControlScreen(embedded: true)'));
    expect(settings, contains('DebugScreen(embedded: true)'));

    expect(
        home,
        contains(
            'final titles = [strings.home, strings.activity, strings.settings]'));
    expect(home, isNot(contains('const AppSettingsScreen()')));
    expect(home, contains('const MobileAdminSettingsScreen()'));
    expect(home, contains('if (_identityStatus.isMobileAdmin)'));
    expect(home, contains('const RegistrationScreen()'));

    expect(webView, isNot(contains('const AppSettingsScreen()')));
    expect(webView, isNot(contains('const SmartKeyControlScreen()')));
    expect(webView, isNot(contains('const DebugScreen()')));
    expect(recovery, isNot(contains('const AppSettingsScreen()')));
    expect(recovery, isNot(contains('const SmartKeyControlScreen()')));
    expect(recovery, isNot(contains('const DebugScreen()')));
  });

  test('registration screen is registration-only', () {
    final source =
        File('lib/screens/registration_screen.dart').readAsStringSync();
    expect(source, contains('등록 신청'));
    expect(source, isNot(contains('requestOpenCommand')));
    expect(source, isNot(contains('RemoteManualOpenService')));
    expect(source, isNot(contains('AppSettingsScreen')));
  });
}
