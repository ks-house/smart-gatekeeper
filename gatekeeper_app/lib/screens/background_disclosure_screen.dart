import 'package:flutter/material.dart';

class BackgroundDisclosureScreen extends StatelessWidget {
  const BackgroundDisclosureScreen({
    super.key,
    required this.onConsent,
    required this.onDefer,
    this.busy = false,
  });

  final Future<void> Function() onConsent;
  final VoidCallback onDefer;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('백그라운드 출입 감지 안내')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 680),
              child: Semantics(
                scopesRoute: true,
                namesRoute: true,
                explicitChildNodes: true,
                label: '백그라운드 출입 감지 권한 및 배터리 사용 안내',
                child: Card(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Icon(Icons.shield_outlined,
                            size: 48, color: theme.colorScheme.primary),
                        const SizedBox(height: 16),
                        Text(
                          '동의 후에만 시스템 요청을 시작합니다',
                          style: theme.textTheme.headlineSmall,
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 16),
                        const Text(
                          '화면이 꺼진 동안에도 등록된 출입문을 감지하려면 다음 항목이 필요합니다. '
                          '동의하기 전에는 위치·Bluetooth 권한이나 배터리 최적화 예외를 요청하지 않습니다.',
                        ),
                        const SizedBox(height: 16),
                        const _DisclosureItem(
                          icon: Icons.location_on_outlined,
                          title: '위치 및 근처 기기 권한',
                          detail:
                              'BLE 출입문 신호 탐색에 사용합니다. 위치 이력이나 이동 경로를 서버에 판매하지 않습니다.',
                        ),
                        const _DisclosureItem(
                          icon: Icons.location_searching,
                          title: '백그라운드 위치 허용',
                          detail:
                              '앱 화면이 닫혀 있을 때 BLE 감지를 계속하기 위해 Android의 “항상 허용” 권한을 요청합니다.',
                        ),
                        const _DisclosureItem(
                          icon: Icons.battery_saver_outlined,
                          title: '배터리 최적화 예외',
                          detail:
                              'Android 전용 배터리 최적화 예외 화면을 엽니다. 거부해도 수동 복구와 업데이트 기능은 유지됩니다.',
                        ),
                        const SizedBox(height: 20),
                        FilledButton.icon(
                          key: const Key('background-consent-accept'),
                          onPressed: busy ? null : onConsent,
                          icon: busy
                              ? const SizedBox.square(
                                  dimension: 18,
                                  child:
                                      CircularProgressIndicator(strokeWidth: 2),
                                )
                              : const Icon(Icons.check_circle_outline),
                          label: const Text('동의하고 계속'),
                        ),
                        const SizedBox(height: 8),
                        TextButton(
                          key: const Key('background-consent-defer'),
                          onPressed: busy ? null : onDefer,
                          child: const Text('나중에 설정 — 복구 화면 사용'),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _DisclosureItem extends StatelessWidget {
  const _DisclosureItem({
    required this.icon,
    required this.title,
    required this.detail,
  });

  final IconData icon;
  final String title;
  final String detail;

  @override
  Widget build(BuildContext context) => ListTile(
        contentPadding: EdgeInsets.zero,
        leading: Icon(icon),
        title: Text(title),
        subtitle: Text(detail),
      );
}
