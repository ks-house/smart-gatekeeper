import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/l10n/generated/app_localizations_en.dart';
import 'package:gatekeeper_app/l10n/generated/app_localizations_ko.dart';
import 'package:gatekeeper_app/services/home_message_projection.dart';

void main() {
  final english = AppLocalizationsEn();
  final korean = AppLocalizationsKo();

  test('command execution stays semantic and resolves in the active locale',
      () {
    const message = HomeMessage(
      HomeMessageKind.manualOpenCommandExecuted,
      latencyMs: 2007,
    );

    expect(
      message.resolve(korean),
      'Target이 개방 명령을 실행했습니다. 실제 문 열림은 별도 확인이 필요합니다. (2007ms)',
    );
    expect(
      message.resolve(english),
      'Target executed the open command. Physical door opening is not confirmed. (2007ms)',
    );
  });

  test('generic failure resolves in the active locale without a door claim',
      () {
    const message = HomeMessage(
      HomeMessageKind.failure,
      reason: 'FAILED',
    );

    expect(message.resolve(korean), contains('요청을 완료하지 못했습니다'));
    expect(message.resolve(english), contains('request did not complete'));
    expect(
        message.resolve(english).toLowerCase(), isNot(contains('door open')));
  });

  test('proof uncertainty remains terminal and forbids automatic retry', () {
    const message = HomeMessage(
      HomeMessageKind.failure,
      reason: 'PROOF_UNCERTAIN',
    );

    expect(message.resolve(korean), contains('자동 재시도하지 마세요'));
    expect(message.resolve(english), contains('Do not retry automatically'));
  });
}
