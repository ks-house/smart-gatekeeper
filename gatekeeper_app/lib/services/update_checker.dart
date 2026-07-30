import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:package_info_plus/package_info_plus.dart';
import 'package:dio/dio.dart';
import 'package:path_provider/path_provider.dart';
import 'package:open_filex/open_filex.dart';

/// APK Version Checker & Auto Download Service
class UpdateChecker {
  static final UpdateChecker _instance = UpdateChecker._internal();
  factory UpdateChecker() => _instance;
  UpdateChecker._internal();

  // 환경변수(--dart-define=APK_VERSION_URL=...)로부터 동적 로드 (하드코딩 금지)
  static const String versionUrlFromEnv =
      String.fromEnvironment('APK_VERSION_URL');
  static const String downloadUrlFromEnv =
      String.fromEnvironment('APK_DOWNLOAD_URL');

  String? remoteVersion;
  int? remoteBuildNumber;
  String? downloadUrl;

  final ValueNotifier<bool> isUpdateAvailable = ValueNotifier<bool>(false);
  final ValueNotifier<double?> downloadProgress = ValueNotifier<double?>(null);

  /// 백엔드 또는 환경변수 URL로 앱 업데이트 여부 확인
  Future<bool> checkForUpdates(
      {String? customVersionUrl, String? customDownloadUrl}) async {
    final targetUrl = (customVersionUrl != null && customVersionUrl.isNotEmpty)
        ? customVersionUrl
        : (versionUrlFromEnv.isNotEmpty
            ? versionUrlFromEnv
            : 'https://tworimpa.synology.me:4442/api/v1/download/version.json');

    try {
      debugPrint('[UpdateChecker] 앱 버전 검사 시작: $targetUrl');
      final response = await http
          .get(Uri.parse(targetUrl))
          .timeout(const Duration(seconds: 5));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body);
        remoteVersion = data['version']?.toString();
        remoteBuildNumber =
            int.tryParse(data['build_number']?.toString() ?? '');
        downloadUrl = (data['apk_url']?.toString() != null &&
                data['apk_url'].toString().isNotEmpty)
            ? data['apk_url'].toString()
            : ((customDownloadUrl != null && customDownloadUrl.isNotEmpty)
                ? customDownloadUrl
                : (downloadUrlFromEnv.isNotEmpty
                    ? downloadUrlFromEnv
                    : 'https://tworimpa.synology.me:4442/api/v1/download/apk'));

        final packageInfo = await PackageInfo.fromPlatform();
        final currentBuildNumber = int.tryParse(packageInfo.buildNumber) ?? 0;

        debugPrint(
            '[UpdateChecker] 현재 버전: ${packageInfo.version} (Build $currentBuildNumber) / 최신 버전: v$remoteVersion (Build $remoteBuildNumber)');

        bool hasNewBuild = remoteBuildNumber != null &&
            remoteBuildNumber! > currentBuildNumber;
        bool hasNewVersionName = remoteVersion != null &&
            remoteVersion!.isNotEmpty &&
            remoteVersion != packageInfo.version;

        if (hasNewBuild || hasNewVersionName) {
          isUpdateAvailable.value = true;
          debugPrint(
              '[UpdateChecker] 🚀 새로운 앱 업데이트 감지됨! (Build: $currentBuildNumber -> $remoteBuildNumber)');
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

  /// 최신 APK 다운로드 (앱 내 파일 다운로드 방식)
  Future<bool> downloadUpdate({String? overrideUrl}) async {
    if (downloadProgress.value != null && downloadProgress.value! < 1.0) {
      debugPrint('[UpdateChecker] 이미 다운로드가 진행 중입니다.');
      return false;
    }

    final targetUrl = (overrideUrl != null && overrideUrl.isNotEmpty)
        ? overrideUrl
        : ((downloadUrl != null && downloadUrl!.isNotEmpty)
            ? downloadUrl!
            : (downloadUrlFromEnv.isNotEmpty
                ? downloadUrlFromEnv
                : 'https://tworimpa.synology.me:4442/api/v1/download/apk'));

    if (targetUrl.isEmpty) {
      debugPrint('[UpdateChecker] APK 다운로드 URL이 설정되지 않았습니다.');
      return false;
    }

    try {
      debugPrint('[UpdateChecker] 앱 내 APK 다운로드 시작: $targetUrl');
      downloadProgress.value = 0.0;

      final tempDir = await getTemporaryDirectory();
      final filePath = '${tempDir.path}/ks-house-gatekeeper.apk';

      final dio = Dio();

      await dio.download(
        targetUrl,
        filePath,
        onReceiveProgress: (received, total) {
          if (total != -1) {
            downloadProgress.value = received / total;
          }
        },
      );

      downloadProgress.value = 1.0;
      debugPrint('[UpdateChecker] 다운로드 완료. 패키지 설치 팝업 호출: $filePath');

      final result = await OpenFilex.open(filePath);
      debugPrint('[UpdateChecker] 설치 실행 결과: ${result.message}');

      // 다운로드 완료 3초 후 프로그레스 바 초기화 (설치 화면이 뜬 후)
      Future.delayed(const Duration(seconds: 3), () {
        downloadProgress.value = null;
      });

      return true;
    } catch (e) {
      debugPrint('[UpdateChecker] APK 다운로드 실패: $e');
      downloadProgress.value = null;
    }

    return false;
  }
}
