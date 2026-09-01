import 'mobile_identity_service.dart';
import 'native_gatt_worker_health.dart';

class AccessSessionPollCandidate {
  const AccessSessionPollCandidate({
    required this.targetSessionId,
    required this.remaining,
  });

  final String targetSessionId;
  final Duration remaining;
}

class AccessSessionPollingPolicy {
  // Each phone also refreshes personal status and lifecycle activity twice per
  // minute. A four-second access interval keeps two resident phones below the
  // shared Backend limit of 40 requests per minute.
  static const interval = Duration(seconds: 4);
  static const maximumWindow = Duration(seconds: 120);
  static const maximumTransientRetries = 3;
  static const rateLimitFallback = Duration(seconds: 30);

  static Duration? nextDelay({
    required MobilePersonalActivityOutcome outcome,
    required int consecutiveTransientFailures,
    Duration? retryAfter,
  }) {
    switch (outcome) {
      case MobilePersonalActivityOutcome.success:
        return interval;
      case MobilePersonalActivityOutcome.rateLimited:
        final serverDelay = retryAfter ?? rateLimitFallback;
        return serverDelay < interval ? interval : serverDelay;
      case MobilePersonalActivityOutcome.retryableFailure:
        if (consecutiveTransientFailures < 1 ||
            consecutiveTransientFailures > maximumTransientRetries) {
          return null;
        }
        return Duration(
          milliseconds: interval.inMilliseconds *
              (1 << (consecutiveTransientFailures - 1)),
        );
      case MobilePersonalActivityOutcome.accessDenied:
      case MobilePersonalActivityOutcome.terminalFailure:
        return null;
    }
  }

  static AccessSessionPollCandidate? candidate(
    NativeGattWorkerHealth health, {
    required DateTime now,
  }) {
    if (health.lastSessionState != 'SUCCEEDED') return null;
    final targetSessionId = health.lastTargetSessionId;
    final armedEpochMs = health.lastSessionUpdatedEpochMs;
    if (targetSessionId == null || armedEpochMs == null) return null;
    final ageMs = now.millisecondsSinceEpoch - armedEpochMs;
    if (ageMs >= maximumWindow.inMilliseconds) return null;
    final boundedAgeMs = ageMs < 0 ? 0 : ageMs;
    return AccessSessionPollCandidate(
      targetSessionId: targetSessionId,
      remaining: Duration(
        milliseconds: maximumWindow.inMilliseconds - boundedAgeMs,
      ),
    );
  }
}
