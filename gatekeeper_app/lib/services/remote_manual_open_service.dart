import 'dart:convert';
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

enum RemoteManualOpenState { requested, outcomeUnknown, failed }

class RemoteManualOpenOutcome {
  const RemoteManualOpenOutcome({
    required this.state,
    required this.reason,
    this.requestId,
  });

  final RemoteManualOpenState state;
  final String reason;
  final String? requestId;
}

/// Explicit user-button control via Backend authorization and signed MQTTS.
///
/// HTTP success proves only that the Backend accepted the possession proof and
/// received broker acknowledgement. It does not claim Target receipt, relay
/// activation, or physical door movement.
class RemoteManualOpenService {
  RemoteManualOpenService({
    http.Client? client,
    String? backendBaseUrl,
    DateTime Function()? clock,
    List<int> Function(int)? randomBytes,
  })  : _client = client ?? http.Client(),
        _backendBaseUrl = backendBaseUrl ?? _configuredBackendBaseUrl,
        _clock = clock ?? DateTime.now,
        _randomBytes = randomBytes ?? _secureRandomBytes;

  static const _channel = MethodChannel(
    'com.kshouse.gatekeeper_app/ble_gatt_worker_health',
  );
  static const _configuredBackendBaseUrl = String.fromEnvironment(
    'BACKEND_URL',
    defaultValue: 'https://tworimpa.synology.me:4442/api/v1',
  );
  static const _reason = 'mobile_manual_button';

  final http.Client _client;
  final String _backendBaseUrl;
  final DateTime Function() _clock;
  final List<int> Function(int) _randomBytes;

  Future<RemoteManualOpenOutcome> request() async {
    final uri = _endpoint();
    if (uri == null) {
      return const RemoteManualOpenOutcome(
        state: RemoteManualOpenState.failed,
        reason: 'BACKEND_URL_INVALID',
      );
    }
    final nonce = _hex(_randomBytes(32));
    final idempotencyKey = _hex(_randomBytes(24));
    final expiresAt = _clock().toUtc().millisecondsSinceEpoch ~/ 1000 + 60;
    Map<Object?, Object?> proof;
    try {
      proof = await _channel.invokeMethod<Map<Object?, Object?>>(
            'signRemoteManualOpen',
            <String, Object?>{
              'nonce': nonce,
              'expiresAt': expiresAt,
              'reason': _reason,
              'idempotencyKey': idempotencyKey,
            },
          ) ??
          const <Object?, Object?>{};
    } catch (_) {
      return const RemoteManualOpenOutcome(
        state: RemoteManualOpenState.failed,
        reason: 'REMOTE_PROOF_UNAVAILABLE',
      );
    }
    final credentialId = proof['credentialId']?.toString() ?? '';
    final signature = proof['signatureRaw64']?.toString() ?? '';
    if (proof['accepted'] != true ||
        !RegExp(r'^[0-9a-f]{32}$').hasMatch(credentialId) ||
        !RegExp(r'^[0-9a-f]{128}$').hasMatch(signature)) {
      return RemoteManualOpenOutcome(
        state: RemoteManualOpenState.failed,
        reason: proof['reason']?.toString() ?? 'REMOTE_PROOF_UNAVAILABLE',
      );
    }

    try {
      final response = await _client
          .post(
            uri,
            headers: <String, String>{
              'Content-Type': 'application/json',
              'Idempotency-Key': idempotencyKey,
            },
            body: jsonEncode(<String, Object?>{
              'credential_id': credentialId,
              'reason': _reason,
              'nonce': nonce,
              'expires_at': expiresAt,
              'signature_raw64': signature,
            }),
          )
          .timeout(const Duration(seconds: 12));
      if (response.statusCode >= 200 && response.statusCode < 300) {
        String? requestId;
        try {
          final body = jsonDecode(response.body);
          if (body is Map) requestId = body['request_id']?.toString();
        } catch (_) {}
        return RemoteManualOpenOutcome(
          state: RemoteManualOpenState.requested,
          reason: 'BROKER_ACKNOWLEDGED',
          requestId: requestId,
        );
      }
      return RemoteManualOpenOutcome(
        state: RemoteManualOpenState.failed,
        reason: switch (response.statusCode) {
          401 || 403 => 'REMOTE_CONTROL_DENIED',
          409 => 'REMOTE_DOOR_SELECTION_REQUIRED',
          426 => 'APP_UPDATE_REQUIRED',
          _ => 'REMOTE_CONTROL_UNAVAILABLE',
        },
      );
    } catch (_) {
      // A timeout can occur after the Backend has published. Never retry a
      // physical-effect request automatically with a fresh nonce.
      return const RemoteManualOpenOutcome(
        state: RemoteManualOpenState.outcomeUnknown,
        reason: 'REMOTE_DELIVERY_OUTCOME_UNKNOWN',
      );
    }
  }

  Uri? _endpoint() {
    final base = _backendBaseUrl.trim().replaceFirst(RegExp(r'/+$'), '');
    final uri = Uri.tryParse('$base/door/open');
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty) {
      return null;
    }
    return uri;
  }

  static List<int> _secureRandomBytes(int length) {
    final random = Random.secure();
    return List<int>.generate(length, (_) => random.nextInt(256));
  }

  static String _hex(List<int> value) =>
      value.map((byte) => byte.toRadixString(16).padLeft(2, '0')).join();
}
