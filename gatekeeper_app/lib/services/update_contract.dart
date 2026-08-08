import 'dart:collection';
import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:cryptography/cryptography.dart';

/// Exact consumer for ota/schemas/mobile-manifest.schema.json.
///
/// Manifest keys are intentionally not aliased here. Production metadata must
/// pass the repository's machine-readable OTA contract before the app accepts
/// it, and the signing key is supplied by the APK rather than by the manifest.
class SignedUpdateManifest {
  const SignedUpdateManifest._({
    required this.schemaVersion,
    required this.artifactType,
    required this.version,
    required this.versionName,
    required this.buildNumber,
    required this.versionCode,
    required this.minProtocol,
    required this.maxProtocol,
    required this.minAndroidSdk,
    required this.primaryUrl,
    required this.fallbackUrl,
    required this.artifactSize,
    required this.artifactSha256,
    required this.certificateSha256,
    required this.signatureAlgorithm,
    required this.signingKeyId,
    required this.signature,
    required this.mandatoryAfter,
    required this.releaseNotesUrl,
    required this.publishedAt,
    required this.commit,
  });

  static const Set<String> _requiredFields = <String>{
    'schema_version',
    'artifact_type',
    'version',
    'version_name',
    'build_number',
    'version_code',
    'protocol_min',
    'protocol_max',
    'min_android_sdk',
    'apk_url',
    'fallback_url',
    'apk_size',
    'sha256',
    'signing_certificate_digest',
    'signature_algorithm',
    'signing_key_id',
    'signature',
    'mandatory_after',
    'release_notes_url',
    'published_at',
    'commit',
  };

  final int schemaVersion;
  final String artifactType;
  final String version;
  final String versionName;
  final int buildNumber;
  final int versionCode;
  final int minProtocol;
  final int maxProtocol;
  final int minAndroidSdk;
  final String primaryUrl;
  final String fallbackUrl;
  final int artifactSize;
  final String artifactSha256;
  final String certificateSha256;
  final String signatureAlgorithm;
  final String signingKeyId;
  final String signature;
  final String? mandatoryAfter;
  final String releaseNotesUrl;
  final String publishedAt;
  final String commit;

  /// Parses the raw document first so duplicate keys cannot be collapsed by
  /// [jsonDecode] before signature verification.
  factory SignedUpdateManifest.fromJsonString(String source) {
    _rejectDuplicateTopLevelKeys(source);
    final decoded = jsonDecode(source);
    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('mobile manifest must be a JSON object');
    }
    return SignedUpdateManifest.fromJson(decoded);
  }

  factory SignedUpdateManifest.fromJson(Map<String, dynamic> json) {
    if (json.keys.toSet().length != _requiredFields.length ||
        !json.keys.toSet().containsAll(_requiredFields)) {
      throw const FormatException('mobile manifest fields do not match schema v1');
    }

    int exactInt(String key) {
      final value = json[key];
      if (value is! int) throw FormatException('$key must be an integer');
      return value;
    }

    String exactString(String key) {
      final value = json[key];
      if (value is! String || value.isEmpty) {
        throw FormatException('$key must be a non-empty string');
      }
      return value;
    }

    final mandatoryValue = json['mandatory_after'];
    if (mandatoryValue != null && mandatoryValue is! String) {
      throw const FormatException('mandatory_after must be a date-time or null');
    }

    final manifest = SignedUpdateManifest._(
      schemaVersion: exactInt('schema_version'),
      artifactType: exactString('artifact_type'),
      version: exactString('version'),
      versionName: exactString('version_name'),
      buildNumber: exactInt('build_number'),
      versionCode: exactInt('version_code'),
      minProtocol: exactInt('protocol_min'),
      maxProtocol: exactInt('protocol_max'),
      minAndroidSdk: exactInt('min_android_sdk'),
      primaryUrl: exactString('apk_url'),
      fallbackUrl: exactString('fallback_url'),
      artifactSize: exactInt('apk_size'),
      artifactSha256: exactString('sha256'),
      certificateSha256: exactString('signing_certificate_digest'),
      signatureAlgorithm: exactString('signature_algorithm'),
      signingKeyId: exactString('signing_key_id'),
      signature: exactString('signature'),
      mandatoryAfter: mandatoryValue as String?,
      releaseNotesUrl: exactString('release_notes_url'),
      publishedAt: exactString('published_at'),
      commit: exactString('commit'),
    );
    manifest._validateSemantics();
    return manifest;
  }

  void _validateSemantics() {
    final digest = RegExp(r'^[0-9a-f]{64}$');
    final keyId = RegExp(r'^[A-Za-z0-9._-]{1,64}$');
    final signaturePattern = RegExp(r'^[A-Za-z0-9+/]{86}==$');
    final commitPattern = RegExp(r'^[0-9a-f]{40}$');
    if (schemaVersion != 1 || artifactType != 'android-apk') {
      throw const FormatException('unsupported mobile manifest schema');
    }
    if (version != versionName || version.length > 64) {
      throw const FormatException('version aliases must match');
    }
    if (buildNumber != versionCode || buildNumber < 1) {
      throw const FormatException('build aliases must match and be positive');
    }
    if (minProtocol < 1 || maxProtocol < minProtocol) {
      throw const FormatException('invalid protocol compatibility range');
    }
    if (minAndroidSdk < 23 || artifactSize < 1) {
      throw const FormatException('invalid platform or artifact size');
    }
    if (!_isHttps(primaryUrl) ||
        !_isHttps(fallbackUrl) ||
        primaryUrl == fallbackUrl ||
        !_isHttps(releaseNotesUrl)) {
      throw const FormatException('update endpoints must be distinct trusted HTTPS URLs');
    }
    if (!digest.hasMatch(artifactSha256) ||
        !digest.hasMatch(certificateSha256) ||
        signatureAlgorithm != 'Ed25519' ||
        !keyId.hasMatch(signingKeyId) ||
        !signaturePattern.hasMatch(signature) ||
        !commitPattern.hasMatch(commit)) {
      throw const FormatException('invalid mobile artifact trust metadata');
    }
    if (!_isDateTime(publishedAt) ||
        (mandatoryAfter != null && !_isDateTime(mandatoryAfter!))) {
      throw const FormatException('invalid manifest date-time');
    }
    if (mandatoryAfter != null &&
        DateTime.parse(mandatoryAfter!).isBefore(DateTime.parse(publishedAt))) {
      throw const FormatException('mandatory_after cannot precede published_at');
    }
  }

  static bool _isHttps(String value) {
    final uri = Uri.tryParse(value);
    return uri != null &&
        uri.scheme == 'https' &&
        uri.host.isNotEmpty &&
        uri.userInfo.isEmpty;
  }

  static bool _isDateTime(String value) =>
      value.contains('T') &&
      RegExp(r'(?:Z|[+-]\d{2}:\d{2})$').hasMatch(value) &&
      DateTime.tryParse(value) != null;

  String? validateTimePolicy({
    DateTime? now,
    Duration maximumFutureSkew = const Duration(minutes: 5),
    Duration maximumManifestAge = const Duration(days: 30),
  }) {
    final trustedNow = (now ?? DateTime.now()).toUtc();
    final publication = DateTime.parse(publishedAt).toUtc();
    if (publication.isAfter(trustedNow.add(maximumFutureSkew))) {
      return 'MANIFEST_FROM_FUTURE';
    }
    if (publication.isBefore(trustedNow.subtract(maximumManifestAge))) {
      return 'MANIFEST_STALE';
    }
    return null;
  }

  bool isMandatoryAt(DateTime now) => mandatoryAfter != null &&
      !DateTime.parse(mandatoryAfter!).toUtc().isAfter(now.toUtc());

  /// `sgk-json-v1`: remove only signature, sort keys, encode UTF-8 JSON with
  /// no insignificant whitespace and no ASCII-only escaping.
  String canonicalBytes() {
    final payload = SplayTreeMap<String, Object?>.from(<String, Object?>{
      'schema_version': schemaVersion,
      'artifact_type': artifactType,
      'version': version,
      'version_name': versionName,
      'build_number': buildNumber,
      'version_code': versionCode,
      'protocol_min': minProtocol,
      'protocol_max': maxProtocol,
      'min_android_sdk': minAndroidSdk,
      'apk_url': primaryUrl,
      'fallback_url': fallbackUrl,
      'apk_size': artifactSize,
      'sha256': artifactSha256,
      'signing_certificate_digest': certificateSha256,
      'signature_algorithm': signatureAlgorithm,
      'signing_key_id': signingKeyId,
      'mandatory_after': mandatoryAfter,
      'release_notes_url': releaseNotesUrl,
      'published_at': publishedAt,
      'commit': commit,
    });
    return jsonEncode(payload);
  }

  Future<bool> verifySignature({
    required String trustedPublicKeyBase64,
    required String trustedSigningKeyId,
  }) async {
    if (trustedSigningKeyId.isEmpty || signingKeyId != trustedSigningKeyId) {
      return false;
    }
    try {
      final publicKeyBytes = base64.decode(trustedPublicKeyBase64);
      final signatureBytes = base64.decode(signature);
      if (publicKeyBytes.length != 32 || signatureBytes.length != 64) {
        return false;
      }
      return Ed25519().verify(
        utf8.encode(canonicalBytes()),
        signature: Signature(
          signatureBytes,
          publicKey: SimplePublicKey(
            publicKeyBytes,
            type: KeyPairType.ed25519,
          ),
        ),
      );
    } catch (_) {
      return false;
    }
  }

  static void _rejectDuplicateTopLevelKeys(String source) {
    var index = 0;

    void whitespace() {
      while (index < source.length &&
          const <String>{' ', '\t', '\r', '\n'}.contains(source[index])) {
        index++;
      }
    }

    String stringToken() {
      if (index >= source.length || source[index] != '"') {
        throw const FormatException('expected JSON string');
      }
      final start = index++;
      while (index < source.length) {
        final unit = source.codeUnitAt(index);
        if (unit < 0x20) throw const FormatException('invalid JSON string');
        if (source[index] == '"') {
          index++;
          return source.substring(start, index);
        }
        if (source[index] == '\\') {
          index++;
          if (index >= source.length) throw const FormatException('invalid JSON escape');
          if (source[index] == 'u') {
            if (index + 4 >= source.length ||
                !RegExp(r'^[0-9a-fA-F]{4}$')
                    .hasMatch(source.substring(index + 1, index + 5))) {
              throw const FormatException('invalid JSON unicode escape');
            }
            index += 5;
            continue;
          }
          if (!const <String>{'"', '\\', '/', 'b', 'f', 'n', 'r', 't'}
              .contains(source[index])) {
            throw const FormatException('invalid JSON escape');
          }
        }
        index++;
      }
      throw const FormatException('unterminated JSON string');
    }

    void scalarValue() {
      if (index >= source.length) throw const FormatException('missing JSON value');
      if (source[index] == '"') {
        stringToken();
        return;
      }
      if (source[index] == '{' || source[index] == '[') {
        throw const FormatException('sgk-json-v1 permits scalar fields only');
      }
      final start = index;
      while (index < source.length &&
          source[index] != ',' &&
          source[index] != '}' &&
          !const <String>{' ', '\t', '\r', '\n'}.contains(source[index])) {
        index++;
      }
      if (start == index) throw const FormatException('missing JSON value');
    }

    whitespace();
    if (index >= source.length || source[index++] != '{') {
      throw const FormatException('mobile manifest must be a JSON object');
    }
    final keys = <String>{};
    whitespace();
    if (index < source.length && source[index] == '}') {
      index++;
    } else {
      while (true) {
        whitespace();
        final encodedKey = stringToken();
        final key = jsonDecode(encodedKey);
        if (key is! String || !keys.add(key)) {
          throw FormatException('duplicate mobile manifest field: $key');
        }
        whitespace();
        if (index >= source.length || source[index++] != ':') {
          throw const FormatException('expected JSON member separator');
        }
        whitespace();
        scalarValue();
        whitespace();
        if (index >= source.length) throw const FormatException('truncated JSON object');
        if (source[index] == '}') {
          index++;
          break;
        }
        if (source[index++] != ',') {
          throw const FormatException('expected JSON field separator');
        }
      }
    }
    whitespace();
    if (index != source.length) {
      throw const FormatException('trailing mobile manifest content');
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
    required int androidSdk,
    required String certificateSha256,
    int supportedProtocolMin = 1,
    int supportedProtocolMax = 2,
  }) {
    if (manifest.buildNumber <= installedBuild) return 'DOWNGRADE_OR_REPLAY';
    if (manifest.minAndroidSdk > androidSdk) return 'ANDROID_SDK_INCOMPATIBLE';
    if (manifest.minProtocol > supportedProtocolMax ||
        manifest.maxProtocol < supportedProtocolMin) {
      return 'PROTOCOL_INCOMPATIBLE';
    }
    if (bytes.length != manifest.artifactSize) return 'ARTIFACT_SIZE_MISMATCH';
    if (sha256Hex(bytes) != manifest.artifactSha256) {
      return 'ARTIFACT_HASH_MISMATCH';
    }
    if (certificateSha256.toLowerCase() != manifest.certificateSha256) {
      return 'CERTIFICATE_MISMATCH';
    }
    return null;
  }
}
