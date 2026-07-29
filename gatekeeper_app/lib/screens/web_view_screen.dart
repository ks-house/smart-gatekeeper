import 'dart:async';
import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';
import '../services/device_id_service.dart';
import '../services/update_checker.dart';
import '../services/error_logger.dart';
import 'debug_screen.dart';

class WebViewScreen extends StatefulWidget {

  final String? initialUrl;

  const WebViewScreen({
    super.key,
    this.initialUrl,
  });

  // 환경변수(--dart-define=WEBVIEW_URL=...)로부터 웹뷰 URL 동적 로드 (하드코딩 방지)
  static const String webviewUrlFromEnv = String.fromEnvironment('WEBVIEW_URL');

  @override
  State<WebViewScreen> createState() => _WebViewScreenState();
}

class _WebViewScreenState extends State<WebViewScreen> with WidgetsBindingObserver {
  late final WebViewController _controller;
  bool _isLoading = true;
  Timer? _updateCheckTimer;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _setupController();
    _loadUrlWithDeviceId();

    // 앱이 포그라운드에 계속 켜져 있을 때를 대비해 15분마다 정기적으로 업데이트 확인 (Push 대체)
    _updateCheckTimer = Timer.periodic(const Duration(minutes: 15), (_) {
      UpdateChecker().checkForUpdates();
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _updateCheckTimer?.cancel();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      // 앱이 백그라운드에서 다시 돌아올 때마다 업데이트 즉시 확인
      UpdateChecker().checkForUpdates();
    }
  }

  void _setupController() {
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF121212))
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (String url) {
            if (mounted) {
              setState(() {
                _isLoading = true;
              });
            }
          },
          onPageFinished: (String url) {
            if (mounted) {
              setState(() {
                _isLoading = false;
              });
            }
          },
          onNavigationRequest: (NavigationRequest request) async {
            final url = request.url;
            if (url.endsWith('.apk') ||
                url.contains('/gatekeeper_apk/') ||
                url.contains('/download/apk') ||
                url.contains('/download/')) {
              try {
                debugPrint('[WebView] 🚀 APK 다운로드 앱 내부 처리 시도: $url');
                UpdateChecker().downloadUpdate(overrideUrl: url);
              } catch (e) {
                debugPrint('[WebView] APK 다운로드 처리 중 오류: $e');
              }
              return NavigationDecision.prevent;
            }
            return NavigationDecision.navigate;
          },

          onWebResourceError: (WebResourceError error) {
            debugPrint('[WebView] Page error: ${error.description}');
          },
        ),
      );
  }

  Future<void> _loadUrlWithDeviceId() async {
    final devId = await DeviceIdService.getDeviceId();
    String targetUrl = widget.initialUrl ??
        (WebViewScreen.webviewUrlFromEnv.isNotEmpty
            ? WebViewScreen.webviewUrlFromEnv
            : 'https://tworimpa.synology.me:4442/app');

    if (!targetUrl.contains('device_id=')) {
      final separator = targetUrl.contains('?') ? '&' : '?';
      targetUrl = '$targetUrl${separator}device_id=$devId';
    }

    debugPrint('[WebView] 🚀 영구 Device ID 반영 웹뷰 로드: $targetUrl');
    await _controller.loadRequest(Uri.parse(targetUrl));
  }

  @override
  Widget build(BuildContext context) {
    final updateChecker = UpdateChecker();

    return Scaffold(
      backgroundColor: const Color(0xFF121212),
      appBar: AppBar(
        title: const Text('Smart Key'),
        centerTitle: true,
        backgroundColor: const Color(0xFF1E1E1E),
        elevation: 0,
        actions: [
          IconButton(
            icon: const Icon(Icons.tune, color: Colors.cyanAccent),
            tooltip: '엔지니어 디버그 모드',
            onPressed: () {
              Navigator.push(
                context,
                MaterialPageRoute(builder: (context) => const DebugScreen()),
              );
            },
          ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () => _controller.reload(),
          ),
        ],

      ),
      body: SafeArea(
        bottom: true,
        child: Column(
          children: [
            // 앱 실행 중 에러 발생 시 상단 빨간색 유리질감 패널로 실시간 에러 메시지 알림
            ValueListenableBuilder<String?>(
              valueListenable: AppErrorLogger().latestError,
              builder: (context, errorMessage, _) {
                if (errorMessage == null || errorMessage.isEmpty) return const SizedBox.shrink();
                return Container(
                  color: Colors.red.shade900,
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                  child: Row(
                    children: [
                      const Icon(Icons.warning_amber_rounded, color: Colors.white),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          errorMessage,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      IconButton(
                        icon: const Icon(Icons.close, color: Colors.white70, size: 20),
                        onPressed: () => AppErrorLogger().clearError(),
                      ),
                    ],
                  ),
                );
              },
            ),

            // 업데이트 감지 시 상단 안내 배너 반응형 표시
            ValueListenableBuilder<bool>(
              valueListenable: updateChecker.isUpdateAvailable,
              builder: (context, available, _) {
                if (!available) return const SizedBox.shrink();
                
                return ValueListenableBuilder<double?>(
                  valueListenable: updateChecker.downloadProgress,
                  builder: (context, progress, _) {
                    final isDownloading = progress != null;
                    
                    return Container(
                      color: Colors.amber.shade900,
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Row(
                            children: [
                              const Icon(Icons.system_update, color: Colors.white),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Text(
                                  isDownloading 
                                    ? (progress >= 1.0 ? '다운로드 완료! 설치를 진행합니다.' : '업데이트 다운로드 중... ${(progress * 100).toStringAsFixed(0)}%')
                                    : '새로운 Smart Key v${updateChecker.remoteVersion ?? ''} 업데이트 가능!',
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                              if (!isDownloading)
                                ElevatedButton(
                                  onPressed: () => updateChecker.downloadUpdate(),
                                  style: ElevatedButton.styleFrom(
                                    backgroundColor: Colors.white,
                                    foregroundColor: Colors.black,
                                    padding: const EdgeInsets.symmetric(horizontal: 12),
                                  ),
                                  child: const Text('다운로드'),
                                ),
                            ],
                          ),
                          if (isDownloading && progress < 1.0) ...[
                            const SizedBox(height: 10),
                            LinearProgressIndicator(
                              value: progress,
                              backgroundColor: Colors.white30,
                              valueColor: const AlwaysStoppedAnimation<Color>(Colors.white),
                            ),
                          ],
                        ],
                      ),
                    );
                  },
                );
              },
            ),

            Expanded(
              child: Stack(
                children: [
                  WebViewWidget(controller: _controller),
                  if (_isLoading)
                    const Center(
                      child: CircularProgressIndicator(),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );

  }
}
