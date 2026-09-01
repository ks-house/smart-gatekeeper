import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'commercial_models.dart';
import 'mobile_identity_service.dart';
import 'native_gatt_worker_health.dart';
import 'remote_manual_open_service.dart';

class MobileActivityItem {
  const MobileActivityItem({
    required this.id,
    required this.type,
    required this.occurredAt,
    required this.title,
    required this.detail,
    required this.isFailure,
  });

  final String id;
  final String type;
  final DateTime occurredAt;
  final String title;
  final String detail;
  final bool isFailure;

  Map<String, Object?> toJson() => <String, Object?>{
        'id': id,
        'type': type,
        'occurred_at': occurredAt.toUtc().toIso8601String(),
        'title': title,
        'detail': detail,
        'is_failure': isFailure,
      };

  factory MobileActivityItem.fromJson(Map<String, dynamic> value) {
    return MobileActivityItem(
      id: value['id']?.toString() ?? '',
      type: value['type']?.toString() ?? 'unknown',
      occurredAt: DateTime.tryParse(value['occurred_at']?.toString() ?? '') ??
          DateTime.fromMillisecondsSinceEpoch(0),
      title: value['title']?.toString() ?? '상태 변경',
      detail: value['detail']?.toString() ?? '',
      isFailure: value['is_failure'] == true,
    );
  }
}

class MobileActivityStore {
  static const _key = 'mobile_activity_v1';
  static const _limit = 30;

  Future<List<MobileActivityItem>> read() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_key);
    if (raw == null) return const [];
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! List) return const [];
      return decoded
          .whereType<Map>()
          .map((item) =>
              MobileActivityItem.fromJson(item.cast<String, dynamic>()))
          .where((item) => item.id.isNotEmpty)
          .take(_limit)
          .toList(growable: false);
    } catch (_) {
      return const [];
    }
  }

  Future<List<MobileActivityItem>> ingest(NativeGattWorkerHealth health) async {
    final current = await read();
    final next = _project(health);
    if (next == null) return current;
    return _append(current, next);
  }

  Future<List<MobileActivityItem>> recordManualOpenResult(
    Map<Object?, Object?> result, {
    DateTime? occurredAt,
  }) async {
    final current = await read();
    final outcome = ManualOpenOutcome.fromNative(result);
    final timestamp = occurredAt ?? DateTime.now();
    final latency = outcome.latencyMs == null
        ? ''
        : ' (${outcome.latencyMs!.toString()}ms)';
    final safeReason = _boundedReason(outcome.reason);
    final item = switch (outcome.state) {
      ManualOpenState.commandExecuted => MobileActivityItem(
          id: _manualId(outcome, timestamp),
          type: 'manual_command_executed',
          occurredAt: timestamp,
          title: '개방 명령 실행 완료',
          detail: 'Target이 개방 명령을 실행했습니다$latency. 실제 문 열림은 별도 확인이 필요합니다.',
          isFailure: false,
        ),
      ManualOpenState.outcomeUnknown => MobileActivityItem(
          id: _manualId(outcome, timestamp),
          type: 'manual_command_unknown',
          occurredAt: timestamp,
          title: '개방 결과 확인 필요',
          detail: 'Target 실행 결과를 확인할 수 없습니다 ($safeReason). 자동 재시도하지 마세요.',
          isFailure: true,
        ),
      ManualOpenState.failed => MobileActivityItem(
          id: _manualId(outcome, timestamp),
          type: 'manual_command_failed',
          occurredAt: timestamp,
          title: '개방 명령 실패',
          detail: 'Target이 개방 명령을 완료하지 못했습니다 ($safeReason).',
          isFailure: true,
        ),
    };
    return _append(current, item);
  }

  Future<List<MobileActivityItem>> recordRemoteOpenResult(
    RemoteManualOpenOutcome outcome, {
    DateTime? occurredAt,
  }) async {
    final current = await read();
    final timestamp = occurredAt ?? DateTime.now();
    final safeReason = _boundedReason(outcome.reason);
    final id = outcome.requestId ??
        timestamp.toUtc().millisecondsSinceEpoch.toString();
    final item = switch (outcome.state) {
      RemoteManualOpenState.requested => MobileActivityItem(
          id: 'remote-$id-requested',
          type: 'manual_remote_requested',
          occurredAt: timestamp,
          title: '원격 개방 명령 전달',
          detail: '백엔드가 MQTT broker 전달을 확인했습니다. 실제 문 열림은 별도 확인이 필요합니다.',
          isFailure: false,
        ),
      RemoteManualOpenState.outcomeUnknown => MobileActivityItem(
          id: 'remote-$id-unknown',
          type: 'manual_remote_unknown',
          occurredAt: timestamp,
          title: '원격 개방 결과 확인 필요',
          detail: '전달 결과를 확인할 수 없습니다 ($safeReason). 자동 재시도하지 마세요.',
          isFailure: true,
        ),
      RemoteManualOpenState.failed => MobileActivityItem(
          id: 'remote-$id-failed',
          type: 'manual_remote_failed',
          occurredAt: timestamp,
          title: '원격 개방 요청 실패',
          detail: '백엔드가 요청을 완료하지 못했습니다 ($safeReason).',
          isFailure: true,
        ),
    };
    return _append(current, item);
  }

  Future<List<MobileActivityItem>> recordAccessSession(
    MobileAccessSession session, {
    DateTime? observedAt,
  }) async {
    final current = await read();
    final timestamp = session.occurredAt ?? observedAt ?? DateTime.now();
    final effectiveStatus = session.isReadyComplete
        ? MobileAccessSessionStatus.complete
        : session.status == MobileAccessSessionStatus.complete
            ? MobileAccessSessionStatus.cooldown
            : session.status;
    final item = switch (effectiveStatus) {
      MobileAccessSessionStatus.pending ||
      MobileAccessSessionStatus.armed =>
        MobileActivityItem(
          id: _accessId(session, effectiveStatus),
          type: 'access_armed',
          occurredAt: timestamp,
          title: '출입 준비 완료 · 센서 대기',
          detail: 'Target 인증이 완료되어 센서 접근을 기다리고 있습니다.',
          isFailure: false,
        ),
      MobileAccessSessionStatus.sensorDetected ||
      MobileAccessSessionStatus.relayActive =>
        MobileActivityItem(
          id: _accessId(session, effectiveStatus),
          type: 'access_relay_active',
          occurredAt: timestamp,
          title: '센서 감지 · 개방 동작 중',
          detail: 'Target이 센서를 감지하여 릴레이 개방 동작을 수행하고 있습니다.',
          isFailure: false,
        ),
      MobileAccessSessionStatus.cooldown => MobileActivityItem(
          id: _accessId(session, effectiveStatus),
          type: 'access_cooldown',
          occurredAt: timestamp,
          title: '개방 동작 완료 · 다음 출입 준비 중',
          detail: '릴레이 동작이 종료되어 Target이 다음 인증을 준비하고 있습니다.',
          isFailure: false,
        ),
      MobileAccessSessionStatus.complete => MobileActivityItem(
          id: _accessId(session, effectiveStatus),
          type: 'access_complete',
          occurredAt: timestamp,
          title: '출입 동작 완료 · 다음 인증 가능',
          detail: 'Target 출입 흐름이 완료되었습니다. 이 상태는 문 개폐 자체를 확정하지 않습니다.',
          isFailure: false,
        ),
      MobileAccessSessionStatus.terminated => MobileActivityItem(
          id: _accessId(session, effectiveStatus),
          type: 'access_terminated',
          occurredAt: timestamp,
          title: '출입 동작 종료',
          detail: 'Target 출입 흐름이 완료되지 않고 종료되었습니다.',
          isFailure: true,
        ),
    };
    return _append(current, item);
  }

  String _accessId(
    MobileAccessSession session,
    MobileAccessSessionStatus effectiveStatus,
  ) {
    final eventRef = session.eventRef;
    if (eventRef != null && eventRef.isNotEmpty) {
      return 'access-$eventRef-${effectiveStatus.name}';
    }
    return 'access-${session.targetSessionId}-${effectiveStatus.name}';
  }

  String _manualId(ManualOpenOutcome outcome, DateTime timestamp) {
    return 'manual-${outcome.sessionId ?? timestamp.toUtc().millisecondsSinceEpoch}-${outcome.state.name}';
  }

  String _boundedReason(String reason) {
    final bounded = reason
        .toUpperCase()
        .replaceAll(RegExp('[^A-Z0-9_-]'), '_')
        .replaceAll(RegExp('_+'), '_');
    if (bounded.isEmpty) return 'UNKNOWN';
    return bounded.length <= 64 ? bounded : bounded.substring(0, 64);
  }

  Future<List<MobileActivityItem>> _append(
    List<MobileActivityItem> current,
    MobileActivityItem next,
  ) async {
    if (current.any((item) => item.id == next.id)) return current;
    final updated =
        <MobileActivityItem>[next, ...current].take(_limit).toList();
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(
      _key,
      jsonEncode(updated.map((item) => item.toJson()).toList()),
    );
    return updated;
  }

  MobileActivityItem? _project(NativeGattWorkerHealth health) {
    final session = health.lastSession;
    final updated = (session?['updatedEpochMs'] as num?)?.toInt();
    final state = session?['state']?.toString();
    if (updated != null && state != null) {
      final failure = state == 'FAILED' || state == 'PROOF_UNCERTAIN';
      final title = switch (state) {
        'SUCCEEDED' => '출입 준비 완료',
        'PROOF_UNCERTAIN' => '결과를 확인할 수 없음',
        'FAILED' => 'Target 인증 실패',
        'DISABLED' => '자동 출입 비활성',
        'RUNNING' || 'QUEUED' || 'RETRY_PENDING' => 'Target 인증 중',
        _ => 'Target 상태 변경',
      };
      return MobileActivityItem(
        id: 'session-$updated-$state',
        type: state.toLowerCase(),
        occurredAt: DateTime.fromMillisecondsSinceEpoch(updated),
        title: title,
        detail: state == 'SUCCEEDED'
            ? '센서 접근을 기다리고 있습니다. 문 열림 확인은 아닙니다.'
            : (health.lastReasonCode ?? health.lastTransportReason ?? state),
        isFailure: failure,
      );
    }
    final detection = health.latestDetection;
    if (detection == null) return null;
    return MobileActivityItem(
      id: 'detection-${detection.receivedEpochMs}-${detection.success}',
      type: 'detected',
      occurredAt: detection.receivedAt,
      title: detection.success ? 'Target 감지' : 'Target 감지 실패',
      detail: detection.success ? '스마트키 인증을 준비합니다.' : '다시 시도해주세요.',
      isFailure: !detection.success,
    );
  }
}
