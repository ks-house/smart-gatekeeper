import 'package:flutter/services.dart';

enum NativeWakeStatus { registered, notRegistered, blocked, unavailable }

class NativeWakeRegistration {
  const NativeWakeRegistration({
    required this.status,
    required this.registered,
    required this.nextAction,
    this.errorCode,
  });

  final NativeWakeStatus status;
  final bool registered;
  final String nextAction;
  final int? errorCode;

  factory NativeWakeRegistration.fromMap(Map<Object?, Object?> value) {
    final raw = value['status']?.toString() ?? 'unavailable';
    final status = switch (raw) {
      'registered' => NativeWakeStatus.registered,
      'not_registered' => NativeWakeStatus.notRegistered,
      _ when raw.startsWith('missing_permission') ||
          raw.contains('bluetooth') => NativeWakeStatus.blocked,
      _ => NativeWakeStatus.unavailable,
    };
    return NativeWakeRegistration(
      status: status,
      registered: value['registered'] == true,
      nextAction: value['nextAction']?.toString() ?? 'retry',
      errorCode: (value['errorCode'] as num?)?.toInt(),
    );
  }
}

class NativeWakeRegistrationBridge {
  static const MethodChannel _channel = MethodChannel(
    'com.kshouse.gatekeeper_app/ble_wake_registration',
  );

  Future<NativeWakeRegistration> status() async {
    final raw = await _channel.invokeMethod<Map<Object?, Object?>>('getStatus');
    return NativeWakeRegistration.fromMap(raw ?? const <Object?, Object?>{});
  }

  Future<NativeWakeRegistration> register() async {
    final raw = await _channel.invokeMethod<Map<Object?, Object?>>('register');
    return NativeWakeRegistration.fromMap(raw ?? const <Object?, Object?>{});
  }

  Future<NativeWakeRegistration> stop() async {
    final raw = await _channel.invokeMethod<Map<Object?, Object?>>('stop');
    return NativeWakeRegistration.fromMap(raw ?? const <Object?, Object?>{});
  }
}
