import 'dart:io';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:device_info_plus/device_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:dio/dio.dart';
import 'package:path_provider/path_provider.dart';
import 'package:open_filex/open_filex.dart';
import 'update_contract.dart';

enum UpdateState { idle, checking, available, downloading, verifying, installing, healthy, failed }

String updateStatusMessage(
  UpdateState state, {
  String? version,
  String? failureReason,
  bool mandatory = false,
}) {
  switch (state) {
    case UpdateState.idle:
      return '업데이트 확인 전입니다.';
    case UpdateState.checking:
      return '서명된 업데이트 정보를 확인 중입니다.';
    case UpdateState.available:
      return mandatory
          ? '필수 보안 업데이트 v${version ?? ''} 설치가 필요합니다.'
          : '새 버전 v${version ?? ''} 다운로드 가능';
    case UpdateState.downloading:
      return '검증 전 임시 파일을 다운로드 중입니다.';
    case UpdateState.verifying:
      return 'APK 크기, 해시, 패키지와 서명을 검증 중입니다.';
    case UpdateState.installing:
      return '설치 승인 또는 새 앱 첫 실행 확인을 기다리고 있습니다.';
    case UpdateState.healthy:
      return '서명된 metadata 기준 최신 버전입니다.';
    case UpdateState.failed:
      return '업데이트가 확인되지 않았습니다: ${failureReason ?? 'UNKNOWN'}';
  }
}

/// Independent mobile updater. It never depends on the scanner, WebView, or
/// foreground service and never replaces the installed APK before verification.
class UpdateChecker {
  static final UpdateChecker _instance = UpdateChecker._internal();
  factory UpdateChecker() => _instance;
  UpdateChecker._internal();

  static const String versionUrlFromEnv = String.fromEnvironment('APK_VERSION_URL');
  static const String fallbackVersionUrlFromEnv =
      String.fromEnvironment('APK_FALLBACK_VERSION_URL');
  static const String signingPublicKeyFromEnv = String.fromEnvironment('UPDATE_SIGNING_PUBLIC_KEY_B64');
  static const String signingKeyIdFromEnv = String.fromEnvironment('UPDATE_SIGNING_KEY_ID');
  static const MethodChannel _securityChannel = MethodChannel(
    'com.kshouse.gatekeeper_app/update_security',
  );

  String? remoteVersion;
  int? remoteBuildNumber;
  String? downloadUrl;
  SignedUpdateManifest? manifest;
  UpdateState state = UpdateState.idle;
  String? lastFailureReason;
  bool updateMandatory = false;
  final ValueNotifier<bool> isUpdateAvailable = ValueNotifier<bool>(false);
  final ValueNotifier<double?> downloadProgress = ValueNotifier<double?>(null);
  final ValueNotifier<UpdateState> stateNotifier =
      ValueNotifier<UpdateState>(UpdateState.idle);

  Future<bool> checkForUpdates({String? customVersionUrl, String? customDownloadUrl}) async {
    _transition(UpdateState.checking);
    final metadataUrls = <String>{
      if (customVersionUrl?.trim().isNotEmpty == true) customVersionUrl!.trim(),
      if (versionUrlFromEnv.isNotEmpty)
        versionUrlFromEnv
      else
        'https://tworimpa.synology.me:4442/api/v1/download/version.json',
      if (fallbackVersionUrlFromEnv.isNotEmpty) fallbackVersionUrlFromEnv,
    }.where(_isTrustedHttpsUrl).toList();
    var finalFailure = 'METADATA_UNAVAILABLE';
    for (final targetUrl in metadataUrls) {
      try {
        final response =
            await http.get(Uri.parse(targetUrl)).timeout(const Duration(seconds: 5));
        if (response.statusCode != 200) {
          finalFailure = 'METADATA_HTTP_${response.statusCode}';
          continue;
        }
        final candidate = SignedUpdateManifest.fromJsonString(response.body);
        if (!await candidate.verifySignature(
          trustedPublicKeyBase64: signingPublicKeyFromEnv,
          trustedSigningKeyId: signingKeyIdFromEnv,
        )) {
          finalFailure = 'MANIFEST_SIGNATURE_INVALID';
          continue;
        }
        final timeFailure = candidate.validateTimePolicy();
        if (timeFailure != null) {
          finalFailure = timeFailure;
          continue;
        }
        final packageInfo = await PackageInfo.fromPlatform();
        final currentBuild = int.tryParse(packageInfo.buildNumber) ?? 0;
        if (candidate.buildNumber < currentBuild) {
          finalFailure = 'MANIFEST_BUILD_ROLLBACK';
          continue;
        }
        if (candidate.buildNumber == currentBuild) {
          if (candidate.versionName != packageInfo.version) {
            finalFailure = 'INSTALLED_VERSION_IDENTITY_MISMATCH';
            continue;
          }
          manifest = candidate;
          updateMandatory = false;
          lastFailureReason = null;
          _transition(UpdateState.healthy);
          isUpdateAvailable.value = false;
          return false;
        }
        manifest = candidate;
        remoteVersion = candidate.version;
        remoteBuildNumber = candidate.buildNumber;
        // A legacy remote-config download URL is never promoted over the two
        // URLs covered by the signed manifest.
        downloadUrl = candidate.primaryUrl;
        updateMandatory = candidate.isMandatoryAt(DateTime.now());
        if (customDownloadUrl?.trim().isNotEmpty == true &&
            customDownloadUrl != candidate.primaryUrl &&
            customDownloadUrl != candidate.fallbackUrl) {
          debugPrint('[UpdateChecker] Ignored unsigned custom APK URL');
        }
        isUpdateAvailable.value = true;
        _transition(UpdateState.available);
        lastFailureReason = null;
        return true;
      } catch (error) {
        finalFailure = error is FormatException
            ? 'METADATA_MALFORMED'
            : 'METADATA_UNAVAILABLE';
      }
    }
    return _fail(finalFailure);
  }

  Future<bool> downloadUpdate({String? overrideUrl}) async {
    if (state == UpdateState.downloading || state == UpdateState.verifying) return false;
    if (state != UpdateState.available) return _fail('NO_ACTIVE_VERIFIED_UPDATE');
    final currentManifest = manifest;
    if (currentManifest == null) return _fail('NO_VERIFIED_MANIFEST');
    if (overrideUrl?.trim().isNotEmpty == true &&
        overrideUrl != currentManifest.primaryUrl &&
        overrideUrl != currentManifest.fallbackUrl) {
      return _fail('UNSIGNED_DOWNLOAD_URL');
    }
    final urls = <String>[
      if (overrideUrl?.trim().isNotEmpty == true) overrideUrl!,
      currentManifest.primaryUrl,
      currentManifest.fallbackUrl,
    ].toSet().toList();
    if (urls.isEmpty) return _fail('NO_UPDATE_URL');
    _transition(UpdateState.downloading);
    downloadProgress.value = 0;
    final tempDir = await getTemporaryDirectory();
    final candidatePath = '${tempDir.path}/smart-gatekeeper-update.apk.part';
    final verifiedPath = '${tempDir.path}/smart-gatekeeper-update.apk';
    for (final url in urls) {
      try {
        final response = await Dio().get<List<int>>(
          url,
          options: Options(responseType: ResponseType.bytes, followRedirects: false),
          onReceiveProgress: (received, total) {
            if (total > 0) downloadProgress.value = received / total;
          },
        );
        final bytes = Uint8List.fromList(response.data ?? const <int>[]);
        await File(candidatePath).writeAsBytes(bytes, flush: true);
        _transition(UpdateState.verifying);
        final cert = await _certificateSha256(candidatePath);
        final installed = await PackageInfo.fromPlatform();
        final androidInfo = await DeviceInfoPlugin().androidInfo;
        final reason = const UpdateArtifactValidator().validate(
          manifest: currentManifest,
          bytes: bytes,
          installedBuild: int.tryParse(installed.buildNumber) ?? 0,
          androidSdk: androidInfo.version.sdkInt,
          certificateSha256: cert,
        );
        if (reason != null) {
          lastFailureReason = reason;
          continue;
        }
        final verifiedFile = File(verifiedPath);
        if (await verifiedFile.exists()) await verifiedFile.delete();
        await File(candidatePath).rename(verifiedPath);
        _transition(UpdateState.installing);
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('update_pending_health_path', verifiedPath);
        await prefs.setInt('update_pending_build_number', currentManifest.buildNumber);
        await prefs.setString('update_pending_version_name', currentManifest.versionName);
        await prefs.setString('update_pending_artifact_sha256', currentManifest.artifactSha256);
        await prefs.setString('update_pending_certificate_sha256', currentManifest.certificateSha256);
        await prefs.setString('update_pending_commit', currentManifest.commit);
        await prefs.setString(
          'update_pending_requested_at',
          DateTime.now().toUtc().toIso8601String(),
        );
        final result = await OpenFilex.open(verifiedPath);
        if (result.type != ResultType.done) {
          lastFailureReason = 'INSTALLER_${result.type}';
          await recordFirstRunHealth(
            healthy: false,
            reason: lastFailureReason,
          );
          continue;
        }
        downloadProgress.value = 1;
        _transition(UpdateState.installing);
        return true;
      } catch (_) {
        lastFailureReason = 'DOWNLOAD_OR_INSTALL_FAILED';
      }
    }
    downloadProgress.value = null;
    _transition(UpdateState.failed);
    try {
      final partial = File(candidatePath);
      if (await partial.exists()) await partial.delete();
    } catch (_) {}
    return false;
  }

  Future<void> recordFirstRunHealth({required bool healthy, String? reason}) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('update_first_run_healthy', healthy);
    if (reason != null) await prefs.setString('update_first_run_reason', reason);
    if (healthy) {
      for (final key in <String>[
        'update_pending_health_path',
        'update_pending_build_number',
        'update_pending_version_name',
        'update_pending_artifact_sha256',
        'update_pending_certificate_sha256',
        'update_pending_commit',
        'update_pending_requested_at',
      ]) {
        await prefs.remove(key);
      }
      lastFailureReason = null;
      _transition(UpdateState.healthy);
    } else {
      lastFailureReason = reason ?? 'FIRST_RUN_HEALTH_FAILED';
      _transition(UpdateState.failed);
    }
  }

  /// Runs before permission, scanner, WebView, or foreground-service startup.
  /// A pending install is healthy only when the installed APK identity matches
  /// every field persisted from the previously verified signed manifest.
  Future<void> reconcilePendingFirstRunHealth() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final expectedBuild = prefs.getInt('update_pending_build_number');
      if (expectedBuild == null) return;
      final identity = await _securityChannel
          .invokeMapMethod<String, Object?>('installedPackageIdentity');
      final expectedVersion = prefs.getString('update_pending_version_name');
      final expectedArtifact =
          prefs.getString('update_pending_artifact_sha256');
      final expectedCertificate =
          prefs.getString('update_pending_certificate_sha256');
      String? failure;
      if (identity == null) {
        failure = 'INSTALLED_IDENTITY_UNAVAILABLE';
      } else if (identity['buildNumber'] != expectedBuild ||
          identity['versionName'] != expectedVersion) {
        failure = 'INSTALLED_VERSION_IDENTITY_MISMATCH';
      } else if (identity['sourceSha256'] != expectedArtifact) {
        failure = 'INSTALLED_ARTIFACT_MISMATCH';
      } else if (identity['certificateSha256'] != expectedCertificate) {
        failure = 'INSTALLED_CERTIFICATE_MISMATCH';
      }
      await recordFirstRunHealth(
        healthy: failure == null,
        reason: failure ?? 'FIRST_RUN_IDENTITY_CONFIRMED',
      );
    } catch (_) {
      try {
        await recordFirstRunHealth(
          healthy: false,
          reason: 'INSTALLED_IDENTITY_UNAVAILABLE',
        );
      } catch (_) {
        // Preference storage failure must not make the recovery UI unreachable.
        lastFailureReason = 'FIRST_RUN_HEALTH_STORAGE_UNAVAILABLE';
        _transition(UpdateState.failed);
      }
    }
  }

  Future<String> _certificateSha256(String path) async {
    try {
      final value = await _securityChannel.invokeMethod<String>('apkCertificateSha256', {'path': path});
      if (value != null && value.isNotEmpty) return value.toLowerCase();
    } catch (_) {}
    // A missing platform certificate is not proof of a valid APK.
    return 'certificate-unavailable';
  }

  bool _fail(String reason) {
    lastFailureReason = reason;
    updateMandatory = false;
    _transition(UpdateState.failed);
    isUpdateAvailable.value = false;
    return false;
  }

  void _transition(UpdateState next) {
    state = next;
    stateNotifier.value = next;
  }

  static bool _isTrustedHttpsUrl(String value) {
    final uri = Uri.tryParse(value);
    return uri != null &&
        uri.scheme == 'https' &&
        uri.host.isNotEmpty &&
        uri.userInfo.isEmpty;
  }
}
