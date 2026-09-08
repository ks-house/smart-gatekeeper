import 'package:flutter/services.dart';

/// Native-owned capture/transport. MissingPlugin is the only legacy fallback;
/// configuration/storage errors must stay visible instead of claiming success.
class NativeDiagnosticUpload {
  static const channel = MethodChannel(
    'com.kshouse.gatekeeper_app/native_diagnostics',
  );

  Future<Map<Object?, Object?>?> configure(
      Map<String, Object?> arguments) async {
    try {
      return await channel.invokeMapMethod<Object?, Object?>(
          'configure', arguments);
    } on MissingPluginException {
      return null;
    }
  }

  Future<Map<Object?, Object?>?> status() =>
      channel.invokeMapMethod<Object?, Object?>('status');
  Future<void> requestCapture() => channel.invokeMethod<void>('requestCapture');
  Future<void> clear() async {
    try {
      await channel.invokeMethod<Object?>('clear');
    } on MissingPluginException {
      // Older/non-Android implementations have no native diagnostic queue.
    }
  }
}
