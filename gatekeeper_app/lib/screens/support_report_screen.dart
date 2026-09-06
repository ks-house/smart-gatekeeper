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
    this.service,
  });

  final MobileIdentityStatus identity;
  final NativeGattWorkerHealth? health;
  final SupportReportService? service;

  @override
  State<SupportReportScreen> createState() => _SupportReportScreenState();
}

class _SupportReportScreenState extends State<SupportReportScreen> {
  String? _report;
  bool _consented = false;
  bool _busy = false;
  bool _fullHistory = false;
  late final SupportReportService _service;

  @override
  void initState() {
    super.initState();
    _service = widget.service ?? SupportReportService();
    _reload();
  }

  Future<void> _reload() async {
    setState(() {
      _busy = true;
      _consented = false;
      _report = null;
    });
    try {
      final value = await _service.build(
        identity: widget.identity,
        health: widget.health,
        fullHistory: _fullHistory,
      );
      if (mounted) setState(() => _report = value);
    } catch (_) {
      _showError();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _showError() {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(AppLocalizations.of(context).reportActionFailed)),
    );
  }

  Future<void> _clear() async {
    final strings = AppLocalizations.of(context);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        scrollable: true,
        title: Text(strings.reportClear),
        content: Text(strings.reportClearConfirm),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: Text(strings.reportCancel),
          ),
          TextButton(
            key: const Key('confirm-clear-support-report'),
            onPressed: () => Navigator.pop(context, true),
            child: Text(strings.reportClear),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _busy = true;
      _consented = false;
      _report = null;
    });
    try {
      await _service.clearHistory();
      if (!mounted) return;
      await _reload();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(strings.reportClearDone)),
      );
    } catch (_) {
      _showError();
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _copy() async {
    if (!_consented || _report == null) return;
    try {
      await Clipboard.setData(ClipboardData(text: _report!));
    } catch (_) {
      _showError();
      return;
    }
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(AppLocalizations.of(context).reportCopied)),
    );
  }

  @override
  Widget build(BuildContext context) {
    final strings = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(strings.supportReport),
        actions: [
          IconButton(
            tooltip: strings.reportRefresh,
            onPressed: _busy ? null : _reload,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Text(strings.supportReportDescription),
            Text(strings.reportRecentHistory),
            SwitchListTile(
              value: _fullHistory,
              title: Text(strings.reportFullHistory),
              onChanged: _busy
                  ? null
                  : (value) {
                      setState(() => _fullHistory = value);
                      _reload();
                    },
            ),
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
          ],
        ),
      ),
      bottomNavigationBar: SafeArea(
        top: false,
        minimum: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CheckboxListTile(
                value: _consented,
                onChanged: _busy || _report == null
                    ? null
                    : (value) => setState(() => _consented = value == true),
                title: Text(strings.copyConsent),
                controlAffinity: ListTileControlAffinity.leading,
              ),
              FilledButton.icon(
                key: const Key('copy-redacted-support-report'),
                onPressed:
                    !_busy && _consented && _report != null ? _copy : null,
                icon: const Icon(Icons.copy),
                label: Text(strings.copyReport),
              ),
              TextButton.icon(
                key: const Key('clear-support-report'),
                onPressed: _busy ? null : _clear,
                icon: const Icon(Icons.delete_outline),
                label: Text(strings.reportClear),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
