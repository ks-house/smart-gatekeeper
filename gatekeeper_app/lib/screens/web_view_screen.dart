import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';
import '../services/update_checker.dart';

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

class _WebViewScreenState extends State<WebViewScreen> {
  late final WebViewController _controller;
  bool _isLoading = true;

  @override
  void initState() {
    super.initState();

    final targetUrl = widget.initialUrl ??
        (WebViewScreen.webviewUrlFromEnv.isNotEmpty
            ? WebViewScreen.webviewUrlFromEnv
            : 'https://tworimpa.synology.me:4442/app');

    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFF121212))
      ..setNavigationDelegate(
        NavigationDelegate(
          onPageStarted: (String url) {
            setState(() {
              _isLoading = true;
            });
          },
          onPageFinished: (String url) {
            setState(() {
              _isLoading = false;
            });
          },
          onNavigationRequest: (NavigationRequest request) async {
            if (request.url.endsWith('.apk') || request.url.contains('/gatekeeper_apk/')) {
              try {
                final uri = Uri.parse(request.url);
                debugPrint('[WebView] APK 다운로드 브라우저 전환 시도: $uri');
                await launchUrl(uri, mode: LaunchMode.externalApplication);
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
      )
      ..loadRequest(Uri.parse(targetUrl));
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
            icon: const Icon(Icons.refresh),
            onPressed: () => _controller.reload(),
          ),
        ],
      ),
      body: Column(
        children: [
          // 업데이트 감지 시 상단 안내 배너 표시
          if (updateChecker.isUpdateAvailable)
            Container(
              color: Colors.amber.shade900,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
              child: Row(
                children: [
                  const Icon(Icons.system_update, color: Colors.white),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      '새로운 Smart Key v${updateChecker.remoteVersion ?? ''} 업데이트 가능!',
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
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
    );
  }
}
