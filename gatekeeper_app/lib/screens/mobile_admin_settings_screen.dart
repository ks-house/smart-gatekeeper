import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

class MobileAdminSettingsScreen extends StatelessWidget {
  const MobileAdminSettingsScreen({super.key});

  static final Uri _adminUrl =
      Uri.parse('https://tworimpa.synology.me:4442/admin');

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('관리자 설정')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Card(
            child: ListTile(
              leading: Icon(Icons.admin_panel_settings),
              title: Text('모바일 관리자 계정'),
              subtitle: Text(
                '이 역할은 서버 콘솔에서만 지정됩니다. 사용자 승인, 권한 회수, 계정 삭제 같은 작업은 별도의 관리자 재인증을 계속 요구합니다.',
              ),
            ),
          ),
          Card(
            child: ListTile(
              leading: const Icon(Icons.open_in_browser),
              title: const Text('보안 관리자 콘솔 열기'),
              subtitle: const Text('사용자·출입 이력·권한 관리'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () =>
                  launchUrl(_adminUrl, mode: LaunchMode.externalApplication),
            ),
          ),
        ],
      ),
    );
  }
}
