import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/update_contract.dart';

void main() {
  const hash = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';
  final base = <String, dynamic>{
    'version': '2.0.0',
    'build_number': 2,
    'artifact_sha256': hash,
    'artifact_size': 3,
    'certificate_sha256': hash,
    'apk_url': 'https://updates.example.test/primary.apk',
    'fallback_apk_url': 'https://updates.example.test/fallback.apk',
    'signature': 'signed-envelope',
    'signing_public_key': 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=',
  };

  test('manifest rejects unsigned, insecure, and incomplete metadata', () {
    expect(() => SignedUpdateManifest.fromJson({...base, 'signature': ''}), throwsFormatException);
    expect(() => SignedUpdateManifest.fromJson({...base, 'apk_url': 'http://updates.example.test/a'}), throwsFormatException);
    expect(() => SignedUpdateManifest.fromJson({...base}..remove('artifact_sha256')), throwsFormatException);
  });

  test('artifact validation is fail-closed for downgrade, size, hash, and certificate', () {
    final manifest = SignedUpdateManifest.fromJson(base);
    final bytes = Uint8List.fromList(<int>[1, 2, 3]);
    const validator = UpdateArtifactValidator();
    expect(validator.validate(manifest: manifest, bytes: bytes, installedBuild: 2, certificateSha256: hash), 'DOWNGRADE_OR_REPLAY');
    expect(validator.validate(manifest: manifest, bytes: Uint8List.fromList(<int>[1]), installedBuild: 1, certificateSha256: hash), 'ARTIFACT_SIZE_MISMATCH');
    expect(validator.validate(manifest: manifest, bytes: bytes, installedBuild: 1, certificateSha256: hash), 'ARTIFACT_HASH_MISMATCH');
    final validHash = validator.sha256Hex(bytes);
    final corrected = SignedUpdateManifest.fromJson({...base, 'artifact_sha256': validHash});
    expect(validator.validate(manifest: corrected, bytes: bytes, installedBuild: 1, certificateSha256: 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'), 'CERTIFICATE_MISMATCH');
  });
}
