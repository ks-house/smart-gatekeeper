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
  final ValueNotifier<bool> isUpdateAvailable = ValueNotifier<bool>(false);
  final ValueNotifier<double?> downloadProgress = ValueNotifier<double?>(null);

  Future<bool> checkForUpdates({String? customVersionUrl, String? customDownloadUrl}) async {
    state = UpdateState.checking;
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
        final packageInfo = await PackageInfo.fromPlatform();
        final currentBuild = int.tryParse(packageInfo.buildNumber) ?? 0;
        if (candidate.buildNumber <= currentBuild) {
          manifest = candidate;
          state = UpdateState.healthy;
          isUpdateAvailable.value = false;
          return false;
        }
        manifest = candidate;
        remoteVersion = candidate.version;
        remoteBuildNumber = candidate.buildNumber;
        // A legacy remote-config download URL is never promoted over the two
        // URLs covered by the signed manifest.
        downloadUrl = candidate.primaryUrl;
        if (customDownloadUrl?.trim().isNotEmpty == true &&
            customDownloadUrl != candidate.primaryUrl &&
            customDownloadUrl != candidate.fallbackUrl) {
          debugPrint('[UpdateChecker] Ignored unsigned custom APK URL');
        }
        isUpdateAvailable.value = true;
        state = UpdateState.available;
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
    state = UpdateState.downloading;
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
        state = UpdateState.verifying;
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
        state = UpdateState.installing;
        final result = await OpenFilex.open(verifiedPath);
        if (result.type != ResultType.done) {
          lastFailureReason = 'INSTALLER_${result.type}';
          continue;
        }
        final prefs = await SharedPreferences.getInstance();
        await prefs.setString('update_pending_health_path', verifiedPath);
        downloadProgress.value = 1;
        state = UpdateState.installing;
        return true;
      } catch (_) {
        lastFailureReason = 'DOWNLOAD_OR_INSTALL_FAILED';
      }
    }
    downloadProgress.value = null;
    state = UpdateState.failed;
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
      await prefs.remove('update_pending_health_path');
      state = UpdateState.healthy;
    } else {
      state = UpdateState.failed;
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
    state = UpdateState.failed;
    isUpdateAvailable.value = false;
    return false;
  }

  static bool _isTrustedHttpsUrl(String value) {
    final uri = Uri.tryParse(value);
    return uri != null &&
        uri.scheme == 'https' &&
        uri.host.isNotEmpty &&
        uri.userInfo.isEmpty;
  }
}
