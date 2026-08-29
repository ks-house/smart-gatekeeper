import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import '../services/native_wake_registration.dart';
import '../services/update_checker.dart';
import 'app_settings_screen.dart';

/// A capability shell deliberately independent from scanner, WebView, and FGS.
/// It remains reachable when permissions, Bluetooth, OEM policy, or the web UI
/// are unavailable, so recovery cannot be hidden by the failing capability.
class RecoveryShellScreen extends StatefulWidget {
  const RecoveryShellScreen(
      {super.key,
      required this.status,
      required this.missing,
      this.onRetrySetup});
  final String status;
  final List<String> missing;
  final Future<void> Function()? onRetrySetup;

  @override
  State<RecoveryShellScreen> createState() => _RecoveryShellScreenState();
}

class _RecoveryShellScreenState extends State<RecoveryShellScreen> {
  final _wake = NativeWakeRegistrationBridge();
  final _updates = UpdateChecker();
  NativeWakeRegistration? _registration;
  String? _updateMessage;

  @override
  void initState() {
    super.initState();
    _refreshWake();
  }

  Future<void> _refreshWake() async {
    try {
      final registration = await _wake.status();
      if (mounted) setState(() => _registration = registration);
    } catch (_) {}
  }

  Future<void> _registerWake() async {
    try {
      final registration = await _wake.register();
      if (mounted) setState(() => _registration = registration);
    } catch (_) {
      if (mounted) {
        setState(() => _updateMessage =
            'Native wake is unavailable; use manual recovery.');
      }
    }
  }

  Future<void> _checkUpdates() async {
    await _updates.checkForUpdates();
    if (mounted) {
      setState(
        () => _updateMessage = updateStatusMessage(
          _updates.state,
          version: _updates.remoteVersion,
          failureReason: _updates.lastFailureReason,
          mandatory: _updates.updateMandatory,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: const Text('Smart Key recovery')),
      body: LayoutBuilder(
        builder: (context, constraints) => SingleChildScrollView(
          padding: EdgeInsets.all(constraints.maxWidth < 600 ? 16 : 32),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Semantics(
                    liveRegion: true,
                    header: true,
                    label: widget.status,
                    child: Card(
                      child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('Setup status',
                                  style: theme.textTheme.titleLarge),
                              const SizedBox(height: 8),
                              Text(widget.status),
                              if (widget.missing.isNotEmpty) ...[
                                const SizedBox(height: 12),
                                ...widget.missing.map((value) => ListTile(
                                      contentPadding: EdgeInsets.zero,
                                      leading: const Icon(
                                          Icons.warning_amber_rounded),
                                      title: Text(value),
                                    )),
                              ],
                            ]),
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  Card(
                      child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text('Native wake',
                                  style: theme.textTheme.titleMedium),
                              const SizedBox(height: 6),
                              Text(_registration?.registered == true
                                  ? 'Registered for fresh-install background wake.'
                                  : 'Not registered. Registration is optional; manual recovery remains available.'),
                              const SizedBox(height: 10),
                              FilledButton.icon(
                                onPressed: _registerWake,
                                icon: const Icon(Icons.wifi_tethering),
                                label: const Text('Register native wake'),
                              ),
                            ],
                          ))),
                  const SizedBox(height: 12),
                  Card(
                      child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text('Recovery capabilities',
                                  style: theme.textTheme.titleMedium),
                              const SizedBox(height: 10),
                              if (widget.onRetrySetup != null)
                                FilledButton.icon(
                                  key: const Key('retry-background-setup'),
                                  onPressed: widget.onRetrySetup,
                                  icon: const Icon(Icons.refresh),
                                  label: const Text('권한 및 배터리 설정 다시 시도'),
                                ),
                              if (widget.onRetrySetup != null)
                                const SizedBox(height: 8),
                              OutlinedButton.icon(
                                onPressed: () => Navigator.push(
                                    context,
                                    MaterialPageRoute(
                                        builder: (_) =>
                                            const AppSettingsScreen())),
                                icon: const Icon(Icons.settings),
                                label: const Text('고급 진단 열기'),
                              ),
                              OutlinedButton.icon(
                                onPressed: _checkUpdates,
                                icon: const Icon(Icons.system_update),
                                label: const Text('Check verified app update'),
                              ),
                              TextButton.icon(
                                  onPressed: openAppSettings,
                                  icon: const Icon(Icons.settings),
                                  label: const Text('Open Android settings')),
                              if (_updateMessage != null) ...[
                                const SizedBox(height: 8),
                                Text(_updateMessage!,
                                    semanticsLabel: _updateMessage)
                              ],
                            ],
                          ))),
                  const SizedBox(height: 12),
                  Text(
                    'OEM limitations (force-stop, Bluetooth off, revoked permission, and restricted battery) cannot be silently repaired. Samsung/One UI acceptance requires physical repeated testing; synthetic ADB is not acceptance evidence.',
                    style: theme.textTheme.bodySmall,
                  ),
                ]),
          ),
        ),
      ),
    );
  }
}
