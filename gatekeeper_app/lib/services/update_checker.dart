import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';

/// APK Version Checker & Auto Download Service
class UpdateChecker {
  static final UpdateChecker _instance = UpdateChecker._internal();
  factory UpdateChecker() => _instance;
  UpdateChecker._internal();

  // 환경변수(--dart-define=APK_VERSION_URL=...)로부터 동적 로드 (하드코딩 금지)
  static const String versionUrlFromEnv = String.fromEnvironment('APK_VERSION_URL');
  static const String downloadUrlFromEnv = String.fromEnvironment('APK_DOWNLOAD_URL');

  String? remoteVersion;
  int? remoteBuildNumber;
  String? downloadUrl;
  bool isUpdateAvailable = false;

  /// 백엔드 또는 환경변수 URL로 앱 업데이트 여부 확인
  Future<bool> checkForUpdates({String? customVersionUrl, String? customDownloadUrl}) async {
    final targetUrl = (customVersionUrl != null && customVersionUrl.isNotEmpty)
        ? customVersionUrl
        : versionUrlFromEnv;

    if (targetUrl.isEmpty) {
      debugPrint('[UpdateChecker] APK_VERSION_URL이 설정되지 않아 버전 검사를 건너땁니다.');
      return false;
    }

    try {
      debugPrint('[UpdateChecker] 앱 버전 검사 시작: $targetUrl');
      final response = await http
          .get(Uri.parse(targetUrl))
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        remoteVersion = data['version']?.toString();
        remoteBuildNumber = int.tryParse(data['build_number']?.toString() ?? '');
        downloadUrl = (data['apk_url']?.toString() != null && data['apk_url'].toString().isNotEmpty)
            ? data['apk_url'].toString()
            : ((customDownloadUrl != null && customDownloadUrl.isNotEmpty) ? customDownloadUrl : downloadUrlFromEnv);

        final packageInfo = await PackageInfo.fromPlatform();
        final currentBuildNumber = int.tryParse(packageInfo.buildNumber) ?? 0;

        debugPrint('[UpdateChecker] 현재 버전: ${packageInfo.version} (Build $currentBuildNumber) / 최신 버전: v$remoteVersion (Build $remoteBuildNumber)');

        if (remoteBuildNumber != null && remoteBuildNumber! > currentBuildNumber) {
          isUpdateAvailable = true;
          debugPrint('[UpdateChecker] 🚀 새로운 앱 업데이트 감지됨!');
          return true;
        }
      } else {
        debugPrint('[UpdateChecker] 버전 정보 조회 실패: HTTP ${response.statusCode}');
      }
    } catch (e) {
      debugPrint('[UpdateChecker] 버전 검사 오류: $e');
    }
    return false;
  }

  /// 최신 APK 다운로드 링크 외부 브라우저로 열기
  Future<bool> downloadUpdate({String? overrideUrl}) async {
    final targetUrl = overrideUrl ?? downloadUrl ?? downloadUrlFromEnv;
    if (targetUrl.isEmpty) {
      debugPrint('[UpdateChecker] APK 다운로드 URL이 설정되지 않았습니다.');
      return false;
    }

    try {
      final uri = Uri.parse(targetUrl);
      debugPrint('[UpdateChecker] APK 다운로드 시도: $targetUrl');
      bool launched = false;
      
      try {
        launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
      } catch (e) {
        debugPrint('[UpdateChecker] externalApplication 실행 실패: $e');
      }

      if (!launched) {
        try {
          launched = await launchUrl(uri, mode: LaunchMode.inAppBrowserView);
        } catch (e) {
          debugPrint('[UpdateChecker] inAppBrowserView 실행 실패: $e');
        }
      }

      if (!launched) {
        await launchUrl(uri, mode: LaunchMode.platformDefault);
      }
      return true;
    } catch (e) {
      debugPrint('[UpdateChecker] APK 다운로드 실행 최종 오류: $e');
    }


    return false;
  }
}
