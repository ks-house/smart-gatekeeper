import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('mobile exposes one settings destination with two preserved areas', () {
    final settings =
        File('lib/screens/app_settings_screen.dart').readAsStringSync();
    final webView = File('lib/screens/web_view_screen.dart').readAsStringSync();
    final recovery =
        File('lib/screens/recovery_shell_screen.dart').readAsStringSync();

    expect(settings, contains("title: const Text('Smart Key 설정')"));
    expect(settings, contains("text: 'Smart Key'"));
    expect(settings, contains("text: '진단·튜닝'"));
    expect(settings, contains('SmartKeyControlScreen(embedded: true)'));
    expect(settings, contains('DebugScreen(embedded: true)'));

    expect(webView, contains('const AppSettingsScreen()'));
    expect(webView, isNot(contains('const SmartKeyControlScreen()')));
    expect(webView, isNot(contains('const DebugScreen()')));
    expect(recovery, contains('const AppSettingsScreen()'));
    expect(recovery, isNot(contains('const SmartKeyControlScreen()')));
    expect(recovery, isNot(contains('const DebugScreen()')));
  });
}
