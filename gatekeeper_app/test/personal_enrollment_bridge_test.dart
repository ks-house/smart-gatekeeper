import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('WebView enrollment is delegated to authenticated native code', () {
    final source = File('lib/screens/web_view_screen.dart').readAsStringSync();
    expect(source, contains("addJavaScriptChannel("));
    expect(source, contains("'GatekeeperNative'"));
    expect(source, contains("'X-API-KEY': _apiKey"));
    expect(source, contains("/user/request"));
    expect(source, contains('DeviceIdService.getDeviceId()'));
  });

  test('web content never embeds the application API key', () {
    final source = File('../backend/app/static/index.html').readAsStringSync();
    expect(source, contains('GatekeeperNative.postMessage'));
    expect(source, isNot(contains('X-API-KEY')));
    expect(source, isNot(contains('GATEKEEPER_API_KEY')));
  });
}
