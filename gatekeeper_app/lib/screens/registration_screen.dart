import 'package:flutter/material.dart';

import '../services/commercial_models.dart';
import '../services/mobile_identity_service.dart';

/// Native, registration-only onboarding. It intentionally contains no door
/// control, installer tuning, credential identifier, or backend configuration.
class RegistrationScreen extends StatefulWidget {
  const RegistrationScreen({super.key, this.identity});

  final MobileIdentityService? identity;

  @override
  State<RegistrationScreen> createState() => _RegistrationScreenState();
}

class _RegistrationScreenState extends State<RegistrationScreen> {
  late final MobileIdentityService _identity;
  final _name = TextEditingController();
  final _unit = TextEditingController();
  MobileIdentityStatus _status = MobileIdentityStatus.unavailable;
  bool _busy = true;
  String? _message;

  @override
  void initState() {
    super.initState();
    _identity = widget.identity ?? MobileIdentityService();
    _refresh();
  }

  @override
  void dispose() {
    _name.dispose();
    _unit.dispose();
    super.dispose();
  }

  Future<void> _refresh() async {
    setState(() => _busy = true);
    final status = await _identity.status();
    if (!mounted) return;
    setState(() {
      _status = status;
      _busy = false;
      if (status.accountName != null) _name.text = status.accountName!;
      if (status.unitNumber != null) _unit.text = status.unitNumber!;
    });
  }

  Future<void> _submit() async {
    final name = _name.text.trim();
    final unit = _unit.text.trim();
    if (name.isEmpty || unit.isEmpty) {
      setState(() => _message = '이름과 동·호수를 모두 입력해 주세요.');
      return;
    }
    setState(() {
      _busy = true;
      _message = null;
    });
    final result = await _identity.requestRegistration(
      name: name,
      unitNumber: unit,
    );
    if (!mounted) return;
    if (result == 'REQUEST_ACCEPTED') {
      await _refresh();
      if (mounted) setState(() => _message = '신청이 접수되었습니다. 관리자 승인을 기다려 주세요.');
    } else {
      setState(() {
        _busy = false;
        _message = '신청을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final pending = _status.enrollmentState == EnrollmentState.pending;
    final approved = _status.enrollmentState == EnrollmentState.readyToEnroll ||
        _status.enrollmentState == EnrollmentState.approved;
    return Scaffold(
      appBar: AppBar(title: const Text('스마트키 등록')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Icon(Icons.person_add_alt_1,
              size: 56, color: Colors.cyanAccent),
          const SizedBox(height: 16),
          Text(
            approved
                ? '관리자 승인이 완료되었습니다.'
                : pending
                    ? '관리자 승인 대기 중입니다.'
                    : '사용자 정보를 신청해 주세요.',
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 8),
          const Text(
            '승인 후 이 휴대폰의 보안 키가 등록됩니다. 이 화면에서는 문 열기나 시스템 설정을 제공하지 않습니다.',
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 24),
          if (!approved) ...[
            TextField(
              controller: _name,
              enabled: !_busy && !pending,
              maxLength: 50,
              decoration: const InputDecoration(
                labelText: '이름',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _unit,
              enabled: !_busy && !pending,
              maxLength: 20,
              decoration: const InputDecoration(
                labelText: '동·호수',
                hintText: '예: 401호',
                border: OutlineInputBorder(),
              ),
            ),
          ],
          if (_message != null) ...[
            const SizedBox(height: 12),
            Text(_message!, textAlign: TextAlign.center),
          ],
          const SizedBox(height: 20),
          if (!pending && !approved)
            FilledButton.icon(
              onPressed: _busy ? null : _submit,
              icon: const Icon(Icons.send),
              label: const Text('등록 신청'),
            )
          else
            FilledButton.icon(
              onPressed: _busy ? null : _refresh,
              icon: const Icon(Icons.refresh),
              label: Text(approved ? '홈에서 계속' : '승인 상태 확인'),
            ),
          if (approved)
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('홈으로 돌아가기'),
            ),
        ],
      ),
    );
  }
}
