import 'dart:convert';
import 'dart:typed_data';
import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:cryptography/cryptography.dart';

class SignedUpdateManifest {
  const SignedUpdateManifest({
    required this.version,
    required this.buildNumber,
    required this.artifactSha256,
    required this.artifactSize,
    required this.certificateSha256,
    required this.primaryUrl,
    required this.fallbackUrl,
    required this.signature,
    required this.signingPublicKey,
    this.minProtocol = 1,
    this.maxProtocol = 1,
  });

  final String version;
  final int buildNumber;
  final String artifactSha256;
  final int artifactSize;
  final String certificateSha256;
  final String primaryUrl;
  final String fallbackUrl;
  final String signature;
  final String signingPublicKey;
  final int minProtocol;
  final int maxProtocol;

  factory SignedUpdateManifest.fromJson(Map<String, dynamic> json) {
    String requiredString(String key) {
      final value = json[key]?.toString() ?? '';
      if (value.isEmpty) throw FormatException('missing $key');
      return value;
    }

    final manifest = SignedUpdateManifest(
      version: requiredString('version'),
      buildNumber: int.parse(requiredString('build_number')),
      artifactSha256: requiredString('artifact_sha256').toLowerCase(),
      artifactSize: int.parse(requiredString('artifact_size')),
      certificateSha256: requiredString('certificate_sha256').toLowerCase(),
      primaryUrl: requiredString('apk_url'),
      fallbackUrl: requiredString('fallback_apk_url'),
      signature: requiredString('signature'),
      signingPublicKey: requiredString('signing_public_key'),
      minProtocol: int.tryParse(json['min_protocol']?.toString() ?? '') ?? 1,
      maxProtocol: int.tryParse(json['max_protocol']?.toString() ?? '') ?? 1,
    );
    final primary = Uri.tryParse(manifest.primaryUrl);
    final fallback = Uri.tryParse(manifest.fallbackUrl);
    if (!RegExp(r'^[0-9a-f]{64}$').hasMatch(manifest.artifactSha256) ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(manifest.certificateSha256) ||
        manifest.artifactSize <= 0 ||
        manifest.signingPublicKey.isEmpty ||
        manifest.buildNumber < 0 ||
        manifest.minProtocol > manifest.maxProtocol ||
        primary == null ||
        !primary.hasAbsolutePath ||
        primary.scheme != 'https' ||
        fallback == null ||
        !fallback.hasAbsolutePath ||
        fallback.scheme != 'https') {
      throw const FormatException('invalid signed update manifest');
    }
    return manifest;
  }

  String canonicalBytes() => jsonEncode({
        'version': version,
        'build_number': buildNumber,
        'artifact_sha256': artifactSha256,
        'artifact_size': artifactSize,
        'certificate_sha256': certificateSha256,
        'apk_url': primaryUrl,
        'fallback_apk_url': fallbackUrl,
        'min_protocol': minProtocol,
        'max_protocol': maxProtocol,
      });

  Future<bool> verifySignature({required String trustedPublicKeyBase64}) async {
    if (trustedPublicKeyBase64.isEmpty || signingPublicKey != trustedPublicKeyBase64) return false;
    try {
      final algorithm = Ed25519();
      final key = SimplePublicKey(
        base64.decode(trustedPublicKeyBase64),
        type: KeyPairType.ed25519,
      );
      return algorithm.verify(
        utf8.encode(canonicalBytes()),
        signature: Signature(base64.decode(signature), publicKey: key),
      );
    } catch (_) {
      return false;
    }
  }
}

class UpdateArtifactValidator {
  const UpdateArtifactValidator();

  String sha256Hex(Uint8List bytes) => sha256.convert(bytes).toString();

  String? validate({
    required SignedUpdateManifest manifest,
    required Uint8List bytes,
    required int installedBuild,
    required String certificateSha256,
    int supportedProtocol = 1,
  }) {
    if (manifest.buildNumber <= installedBuild) return 'DOWNGRADE_OR_REPLAY';
    if (manifest.minProtocol > supportedProtocol ||
        manifest.maxProtocol < supportedProtocol) {
      return 'PROTOCOL_INCOMPATIBLE';
    }
    if (bytes.length != manifest.artifactSize) return 'ARTIFACT_SIZE_MISMATCH';
    if (sha256Hex(bytes) != manifest.artifactSha256) return 'ARTIFACT_HASH_MISMATCH';
    if (certificateSha256.toLowerCase() != manifest.certificateSha256) {
      return 'CERTIFICATE_MISMATCH';
    }
    return null;
  }
}
