import 'package:flutter/foundation.dart';
import 'foreground_service.dart';

class AppErrorLogger {
  static final AppErrorLogger _instance = AppErrorLogger._internal();
  factory AppErrorLogger() => _instance;
  AppErrorLogger._internal();

  final ValueNotifier<List<String>> logs = ValueNotifier<List<String>>([]);
  final ValueNotifier<String?> latestError = ValueNotifier<String?>(null);

  void log(String message) {
    final timestamp = DateTime.now().toIso8601String().substring(11, 19);
    final formatted = '[$timestamp] $message';
    debugPrint(formatted);

    final current = List<String>.from(logs.value);
    if (current.length >= 100) {
      current.removeAt(0);
    }
    current.add(formatted);
    logs.value = current;

    try {
      backgroundSendPort?.send({
        'type': 'AppErrorLogger',
        'action': 'log',
        'message': formatted,
      });
    } catch (_) {}
  }

  void logError(String summary, [dynamic error, StackTrace? stackTrace]) {
    final timestamp = DateTime.now().toIso8601String().substring(11, 19);
    final errorStr = error != null ? ' | Details: ${_redact(error.toString())}' : '';
    final formatted = '[$timestamp] ⚠️ $summary$errorStr';

    debugPrint(formatted);
    if (stackTrace != null) {
      debugPrint(_redact(stackTrace.toString()));
    }

    latestError.value = '$summary$errorStr';

    final current = List<String>.from(logs.value);
    if (current.length >= 100) {
      current.removeAt(0);
    }
    current.add(formatted);
    logs.value = current;

    try {
      backgroundSendPort?.send({
        'type': 'AppErrorLogger',
        'action': 'logError',
        'message': formatted,
        'latestError': latestError.value,
      });
    } catch (_) {}
  }

  /// Support bundles and UI diagnostics must never carry credentials, MACs, URLs,
  /// tokens, or raw exception payloads. Keep the reason useful while redacting at
  /// the boundary rather than relying on every caller to remember the contract.
  String _redact(String value) {
    var result = value.replaceAll(
      RegExp(r'(authorization|token|api[_-]?key|password)=?[^\s,;]+', caseSensitive: false),
      '[SECRET_REDACTED]',
    );
    result = result.replaceAll(
      RegExp(r'\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b', caseSensitive: false),
      '[DEVICE_REDACTED]',
    );
    result = result.replaceAll(
      RegExp(r'https?://[^\s]+', caseSensitive: false),
      '[URL_REDACTED]',
    );
    return result.length > 300 ? result.substring(0, 300) : result;
  }

  void clearError() {
    latestError.value = null;
  }

  void clearLogs() {
    logs.value = [];
    latestError.value = null;
  }

  void syncFromService(Map<String, dynamic> data) {
    if (data['action'] == 'log' || data['action'] == 'logError') {
      final String? message = data['message'];
      if (message != null) {
        final current = List<String>.from(logs.value);
        if (current.length >= 100) current.removeAt(0);
        current.add(message);
        logs.value = current;
      }
    }
    if (data['action'] == 'logError') {
      latestError.value = data['latestError'];
    }
  }
}
