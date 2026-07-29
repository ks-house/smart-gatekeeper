import 'package:flutter/foundation.dart';
import 'package:flutter_foreground_task/flutter_foreground_task.dart';

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
      if (FlutterForegroundTask.isTaskHandlerRunning) {
        FlutterForegroundTask.sendDataToMain({
          'type': 'AppErrorLogger',
          'action': 'log',
          'message': formatted,
        });
      }
    } catch (_) {}
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

    try {
      if (FlutterForegroundTask.isTaskHandlerRunning) {
        FlutterForegroundTask.sendDataToMain({
          'type': 'AppErrorLogger',
          'action': 'logError',
          'message': formatted,
          'latestError': latestError.value,
        });
      }
    } catch (_) {}
  }

  void clearError() {
    latestError.value = null;
  }

  void clearLogs() {
    logs.value = [];
    latestError.value = null;
  }

  void syncFromMain(Map<String, dynamic> data) {
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
