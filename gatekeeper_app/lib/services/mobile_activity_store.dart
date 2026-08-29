import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import 'native_gatt_worker_health.dart';

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
          .map((item) => MobileActivityItem.fromJson(
              item.cast<String, dynamic>()))
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
    if (next == null || current.any((item) => item.id == next.id)) return current;
    final updated = <MobileActivityItem>[next, ...current].take(_limit).toList();
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
