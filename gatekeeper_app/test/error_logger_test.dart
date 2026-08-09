import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/error_logger.dart';

void main() {
  setUp(() {
    AppErrorLogger().clearLogs();
  });

  test('normal and error sinks redact PII, credentials, MACs, and URL queries',
      () {
    final logger = AppErrorLogger();
    logger.log(
      'tenant_name=Hong unit_no=101 device_id=GK-12345678-1234 '
      'mac=AA:BB:CC:DD:EE:FF token=top-secret '
      'https://updates.example.test/app?token=query-secret',
    );
    logger.logError(
      'credential=summary-secret tenant_id=legacy:7',
      'Bearer detail-token room_number=202 DEV-ABCDEFGH1234',
      StackTrace.fromString(
        'api_key=stack-secret https://example.test/path?password=leak',
      ),
    );

    final emitted =
        '${logger.logs.value.join('\n')}\n${logger.latestError.value}';
    for (final secret in <String>[
      'Hong',
      '101',
      'GK-12345678-1234',
      'AA:BB:CC:DD:EE:FF',
      'top-secret',
      'query-secret',
      'summary-secret',
      'legacy:7',
      'detail-token',
      '202',
      'DEV-ABCDEFGH1234',
    ]) {
      expect(emitted, isNot(contains(secret)));
    }
    expect(emitted, contains('[SENSITIVE_REDACTED]'));
    expect(emitted, contains('[DEVICE_REDACTED]'));
    expect(emitted, contains('[URL_REDACTED]'));
  });

  test('service IPC is redacted again before UI and support storage', () {
    final logger = AppErrorLogger();
    logger.syncFromService(<String, dynamic>{
      'action': 'logError',
      'message': 'unit_number=303 password=ipc-secret',
      'latestError': 'device_id=DEV-IPCDEVICE99 token=ipc-token',
    });

    final emitted =
        '${logger.logs.value.join('\n')}\n${logger.latestError.value}';
    expect(emitted, isNot(contains('303')));
    expect(emitted, isNot(contains('ipc-secret')));
    expect(emitted, isNot(contains('DEV-IPCDEVICE99')));
    expect(emitted, isNot(contains('ipc-token')));
  });
}
