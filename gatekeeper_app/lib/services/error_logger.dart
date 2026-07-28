import 'package:flutter/foundation.dart';

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
  }

  void logError(String summary, [dynamic error, StackTrace? stackTrace]) {
    final timestamp = DateTime.now().toIso8601String().substring(11, 19);
    final errorStr = error != null ? ' | Details: $error' : '';
    final formatted = '[$timestamp] ⚠️ $summary$errorStr';

    debugPrint(formatted);
    if (stackTrace != null) {
      debugPrint(stackTrace.toString());
    }

    latestError.value = '$summary$errorStr';

    final current = List<String>.from(logs.value);
    if (current.length >= 100) {
      current.removeAt(0);
    }
    current.add(formatted);
    logs.value = current;
  }

  void clearError() {
    latestError.value = null;
  }

  void clearLogs() {
    logs.value = [];
    latestError.value = null;
  }
}
