import 'package:flutter/services.dart';

enum NativeWakeStatus {
  registered,
  reconciling,
  notRegistered,
  blocked,
  unavailable,
}

class NativeWakeRegistration {
  const NativeWakeRegistration({
    required this.status,
    required this.rawStatus,
    required this.requested,
    required this.reconciled,
    required this.registered,
    required this.nextAction,
    this.errorCode,
    this.attemptedAtEpochMs,
    this.reconciledAtEpochMs,
    this.lastCallbackAtEpochMs,
  });

  final NativeWakeStatus status;
  final String rawStatus;
  final bool requested;
  final bool reconciled;
  final bool registered;
  final String nextAction;
  final int? errorCode;
  final int? attemptedAtEpochMs;
  final int? reconciledAtEpochMs;
  final int? lastCallbackAtEpochMs;

  factory NativeWakeRegistration.fromMap(Map<Object?, Object?> value) {
    final raw = value['status']?.toString() ?? 'unavailable';
    final requested = value['requested'] == true;
    final reconciled = value['reconciled'] == true;
    final status = switch (raw) {
      'registered' when reconciled => NativeWakeStatus.registered,
      'not_registered' => NativeWakeStatus.notRegistered,
      _
          when raw.startsWith('missing_permission') ||
              raw.contains('bluetooth') =>
        NativeWakeStatus.blocked,
      _ when requested => NativeWakeStatus.reconciling,
      _ => NativeWakeStatus.unavailable,
    };
    return NativeWakeRegistration(
      status: status,
      rawStatus: raw,
      requested: requested,
      reconciled: reconciled,
      // Do not trust a legacy `registered` alias without the registrar's
      // explicit reconciliation evidence.
      registered: reconciled,
      nextAction: value['nextAction']?.toString() ?? 'retry',
      errorCode: (value['errorCode'] as num?)?.toInt(),
      attemptedAtEpochMs: (value['attemptedAtEpochMs'] as num?)?.toInt(),
      reconciledAtEpochMs: (value['reconciledAtEpochMs'] as num?)?.toInt(),
      lastCallbackAtEpochMs: (value['lastCallbackAtEpochMs'] as num?)?.toInt(),
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
