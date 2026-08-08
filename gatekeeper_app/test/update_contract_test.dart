import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/update_contract.dart';

void main() {
  const testPublicKey = '11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=';
  const hash =
      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
  final validVector = <String, dynamic>{
    'apk_size': 20971520,
    'apk_url': 'https://updates.example.test/mobile/1.1.0-test.apk',
    'artifact_type': 'android-apk',
    'build_number': 110,
    'commit': '75b946aa173d7315de1903f7685ee3d00b5ceeea',
    'fallback_url': 'https://fallback.example.test/mobile/1.1.0-test.apk',
    'mandatory_after': null,
    'min_android_sdk': 23,
    'protocol_max': 2,
    'protocol_min': 1,
    'published_at': '2026-08-01T00:00:00Z',
    'release_notes_url': 'https://updates.example.test/mobile/1.1.0-test-notes',
    'schema_version': 1,
    'sha256':
        'abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789',
    'signature':
        'RMvdUfcu2C0R0OjcwZ5ABmZZzOBCdmNuRh+xGBQcLPm0eMS9sfY/ATtV2q9cQInuGIjXoSXQ/IhilbZFO9p4AA==',
    'signature_algorithm': 'Ed25519',
    'signing_certificate_digest':
        '1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef',
    'signing_key_id': 'rfc8032-test-key-1',
    'version': '1.1.0-test',
    'version_code': 110,
    'version_name': '1.1.0-test',
  };

  Map<String, dynamic> artifactManifest({
    String artifactHash = hash,
    int protocolMin = 1,
    int protocolMax = 2,
    int minAndroidSdk = 23,
  }) =>
      <String, dynamic>{
        ...validVector,
        'apk_size': 3,
        'build_number': 2,
        'version_code': 2,
        'version': '2.0.0',
        'version_name': '2.0.0',
        'sha256': artifactHash,
        'signing_certificate_digest': hash,
        'protocol_min': protocolMin,
        'protocol_max': protocolMax,
        'min_android_sdk': minAndroidSdk,
      };

  test('repository mobile vector verifies with pinned key id and sgk-json-v1',
      () async {
    final manifest =
        SignedUpdateManifest.fromJsonString(jsonEncode(validVector));
    expect(
      await manifest.verifySignature(
        trustedPublicKeyBase64: testPublicKey,
        trustedSigningKeyId: 'rfc8032-test-key-1',
      ),
      isTrue,
    );
    expect(
      await manifest.verifySignature(
        trustedPublicKeyBase64: testPublicKey,
        trustedSigningKeyId: 'different-key',
      ),
      isFalse,
    );
    final tampered = SignedUpdateManifest.fromJson(
      <String, dynamic>{...validVector, 'sha256': hash},
    );
    expect(
      await tampered.verifySignature(
        trustedPublicKeyBase64: testPublicKey,
        trustedSigningKeyId: 'rfc8032-test-key-1',
      ),
      isFalse,
    );
  });

  test(
      'manifest rejects legacy fields, aliases, nested values, and insecure URLs',
      () {
    expect(
      () => SignedUpdateManifest.fromJson(
        <String, dynamic>{...validVector, 'artifact_sha256': hash},
      ),
      throwsFormatException,
    );
    expect(
      () => SignedUpdateManifest.fromJson(
        <String, dynamic>{...validVector, 'version_code': 109},
      ),
      throwsFormatException,
    );
    expect(
      () => SignedUpdateManifest.fromJsonString(
        jsonEncode(<String, dynamic>{
          ...validVector,
          'release_notes_url': <String, dynamic>{'url': 'https://example.test'},
        }),
      ),
      throwsFormatException,
    );
    expect(
      () => SignedUpdateManifest.fromJson(
        <String, dynamic>{
          ...validVector,
          'apk_url': 'http://example.test/app.apk'
        },
      ),
      throwsFormatException,
    );
  });

  test(
      'raw parser rejects duplicate, escaped-alias duplicate, and trailing content',
      () {
    final encoded = jsonEncode(validVector);
    expect(
      () => SignedUpdateManifest.fromJsonString(
        encoded.replaceFirst('{', '{"apk_size":20971520,'),
      ),
      throwsFormatException,
    );
    expect(
      () => SignedUpdateManifest.fromJsonString(
        encoded.replaceFirst('{', '{"apk_siz\\u0065":20971520,'),
      ),
      throwsFormatException,
    );
    expect(
      () => SignedUpdateManifest.fromJsonString('$encoded true'),
      throwsFormatException,
    );
  });

  test('published and mandatory timestamps are bounded and ordered', () {
    final baseline = SignedUpdateManifest.fromJson(validVector);
    final now = DateTime.parse('2026-08-09T00:00:00Z');
    expect(baseline.validateTimePolicy(now: now), isNull);

    final future = SignedUpdateManifest.fromJson(<String, dynamic>{
      ...validVector,
      'published_at': '2026-08-09T00:05:01Z',
    });
    expect(future.validateTimePolicy(now: now), 'MANIFEST_FROM_FUTURE');

    final stale = SignedUpdateManifest.fromJson(<String, dynamic>{
      ...validVector,
      'published_at': '2026-07-09T23:59:59Z',
    });
    expect(stale.validateTimePolicy(now: now), 'MANIFEST_STALE');

    expect(
      () => SignedUpdateManifest.fromJson(<String, dynamic>{
        ...validVector,
        'published_at': '2026-08-09T00:00:00',
      }),
      throwsFormatException,
    );
    expect(
      () => SignedUpdateManifest.fromJson(<String, dynamic>{
        ...validVector,
        'mandatory_after': '2026-07-31T23:59:59Z',
      }),
      throwsFormatException,
    );

    final mandatory = SignedUpdateManifest.fromJson(<String, dynamic>{
      ...validVector,
      'mandatory_after': '2026-08-02T00:00:00+00:00',
    });
    expect(mandatory.isMandatoryAt(DateTime.parse('2026-08-01T23:59:59Z')),
        isFalse);
    expect(mandatory.isMandatoryAt(DateTime.parse('2026-08-02T00:00:00Z')),
        isTrue);
  });

  test('artifact validation fails closed across platform and N/N-1 bounds', () {
    final bytes = Uint8List.fromList(<int>[1, 2, 3]);
    const validator = UpdateArtifactValidator();
    final validHash = validator.sha256Hex(bytes);
    final manifest = SignedUpdateManifest.fromJson(
      artifactManifest(artifactHash: validHash),
    );
    expect(
      validator.validate(
        manifest: manifest,
        bytes: bytes,
        installedBuild: 1,
        androidSdk: 35,
        certificateSha256: hash,
      ),
      isNull,
    );
    expect(
      validator.validate(
        manifest: manifest,
        bytes: bytes,
        installedBuild: 2,
        androidSdk: 35,
        certificateSha256: hash,
      ),
      'DOWNGRADE_OR_REPLAY',
    );
    final futureSdk = SignedUpdateManifest.fromJson(
      artifactManifest(artifactHash: validHash, minAndroidSdk: 36),
    );
    expect(
      validator.validate(
        manifest: futureSdk,
        bytes: bytes,
        installedBuild: 1,
        androidSdk: 35,
        certificateSha256: hash,
      ),
      'ANDROID_SDK_INCOMPATIBLE',
    );
    final futureProtocol = SignedUpdateManifest.fromJson(
      artifactManifest(artifactHash: validHash, protocolMin: 3, protocolMax: 4),
    );
    expect(
      validator.validate(
        manifest: futureProtocol,
        bytes: bytes,
        installedBuild: 1,
        androidSdk: 35,
        certificateSha256: hash,
      ),
      'PROTOCOL_INCOMPATIBLE',
    );
    expect(
      validator.validate(
        manifest: manifest,
        bytes: Uint8List.fromList(<int>[1]),
        installedBuild: 1,
        androidSdk: 35,
        certificateSha256: hash,
      ),
      'ARTIFACT_SIZE_MISMATCH',
    );
    expect(
      validator.validate(
        manifest: manifest,
        bytes: bytes,
        installedBuild: 1,
        androidSdk: 35,
        certificateSha256:
            'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
      ),
      'CERTIFICATE_MISMATCH',
    );
  });
}
