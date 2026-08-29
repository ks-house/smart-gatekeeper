import 'package:flutter/material.dart';

import 'debug_screen.dart';
import 'smart_key_control_screen.dart';

/// The single settings destination for user controls and advanced diagnostics.
///
/// Keeping both areas as tabs preserves the complete recovery and engineering
/// toolset without presenting two competing settings pages in navigation.
class AppSettingsScreen extends StatelessWidget {
  const AppSettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        backgroundColor: const Color(0xFF121212),
        appBar: AppBar(
          title: const Text('Smart Key 설정'),
          backgroundColor: const Color(0xFF1E1E1E),
          bottom: const TabBar(
            tabs: [
              Tab(icon: Icon(Icons.key), text: 'Smart Key'),
              Tab(icon: Icon(Icons.monitor_heart), text: '진단·튜닝'),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            SmartKeyControlScreen(embedded: true),
            DebugScreen(embedded: true),
          ],
        ),
      ),
    );
  }
}
