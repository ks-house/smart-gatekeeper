import 'dart:convert';
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

class AccountLogoutOutcome {
  const AccountLogoutOutcome(
    this.accepted,
    this.reason, {
    this.serverRevoked = false,
  });
  final bool accepted;
  final String reason;
  final bool serverRevoked;
}

/// Server-first logout: revoke and publish the exact credential before local
/// AndroidKeyStore deletion. A network ambiguity never clears the local key.
class AccountLogoutService {
  AccountLogoutService({http.Client? client, String? backendBaseUrl})
      : _client = client ?? http.Client(),
        _backendBaseUrl = backendBaseUrl ?? _configuredBackendBaseUrl;

  static const _channel = MethodChannel(
    'com.kshouse.gatekeeper_app/ble_gatt_worker_health',
  );
  static const _configuredBackendBaseUrl = String.fromEnvironment(
    'BACKEND_URL',
    defaultValue: 'https://tworimpa.synology.me:4442/api/v1',
  );

  final http.Client _client;
  final String _backendBaseUrl;

  Future<AccountLogoutOutcome> logout() async {
    final base = _backendBaseUrl.trim().replaceFirst(RegExp(r'/+$'), '');
    final uri = Uri.tryParse('$base/mobile/account/logout');
    if (uri == null || uri.scheme != 'https' || uri.host.isEmpty) {
      return const AccountLogoutOutcome(false, 'BACKEND_URL_INVALID');
    }
    final nonce = _hex(_random(32));
    final idempotency = _hex(_random(24));
    final expiresAt =
        DateTime.now().toUtc().millisecondsSinceEpoch ~/ 1000 + 60;
    try {
      final proof = await _channel.invokeMethod<Map<Object?, Object?>>(
            'signAccountLogout',
            <String, Object?>{
              'nonce': nonce,
              'expiresAt': expiresAt,
              'idempotencyKey': idempotency,
            },
          ) ??
          const <Object?, Object?>{};
      if (proof['accepted'] != true) {
        return AccountLogoutOutcome(
          false,
          proof['reason']?.toString() ?? 'LOGOUT_PROOF_UNAVAILABLE',
        );
      }
      final response = await _client
          .post(
            uri,
            headers: <String, String>{
              'Content-Type': 'application/json',
              'Idempotency-Key': idempotency,
            },
            body: jsonEncode(<String, Object?>{
              'credential_id': proof['credentialId'],
              'nonce': nonce,
              'expires_at': expiresAt,
              'signature_raw64': proof['signatureRaw64'],
            }),
          )
          .timeout(const Duration(seconds: 15));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        return AccountLogoutOutcome(
            false, 'SERVER_REJECTED_${response.statusCode}');
      }
      final cleared = await _channel.invokeMethod<Map<Object?, Object?>>(
            'clearLocalIdentityAfterLogout',
          ) ??
          const <Object?, Object?>{};
      return AccountLogoutOutcome(
        cleared['accepted'] == true,
        cleared['reason']?.toString() ?? 'LOCAL_CLEAR_INCOMPLETE',
        serverRevoked: true,
      );
    } catch (_) {
      return const AccountLogoutOutcome(false, 'LOGOUT_OUTCOME_UNKNOWN');
    }
  }

  static List<int> _random(int length) {
    final random = Random.secure();
    return List<int>.generate(length, (_) => random.nextInt(256));
  }

  static String _hex(List<int> bytes) =>
      bytes.map((value) => value.toRadixString(16).padLeft(2, '0')).join();
}
