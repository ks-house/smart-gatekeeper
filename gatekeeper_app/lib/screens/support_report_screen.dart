import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../l10n/generated/app_localizations.dart';
import '../services/mobile_identity_service.dart';
import '../services/native_gatt_worker_health.dart';
import '../services/support_report_service.dart';

class SupportReportScreen extends StatefulWidget {
  const SupportReportScreen({
    super.key,
    required this.identity,
    required this.health,
  });

  final MobileIdentityStatus identity;
  final NativeGattWorkerHealth? health;

  @override
  State<SupportReportScreen> createState() => _SupportReportScreenState();
}

class _SupportReportScreenState extends State<SupportReportScreen> {
  String? _report;
  bool _consented = false;

  @override
  void initState() {
    super.initState();
    SupportReportService()
        .build(identity: widget.identity, health: widget.health)
        .then((value) {
      if (mounted) setState(() => _report = value);
    });
  }

  Future<void> _copy() async {
    if (!_consented || _report == null) return;
    await Clipboard.setData(ClipboardData(text: _report!));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(AppLocalizations.of(context).reportCopied)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final strings = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(strings.supportReport)),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(strings.supportReportDescription),
          const SizedBox(height: 12),
          Semantics(
            label: strings.supportReport,
            readOnly: true,
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: SelectableText(_report ?? '...'),
              ),
            ),
          ),
          CheckboxListTile(
            value: _consented,
            onChanged: (value) => setState(() => _consented = value == true),
            title: Text(strings.copyConsent),
            controlAffinity: ListTileControlAffinity.leading,
          ),
          FilledButton.icon(
            key: const Key('copy-redacted-support-report'),
            onPressed: _consented && _report != null ? _copy : null,
            icon: const Icon(Icons.copy),
            label: Text(strings.copyReport),
          ),
        ],
      ),
    );
  }
}
