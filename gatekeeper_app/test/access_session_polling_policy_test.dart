import 'package:flutter_test/flutter_test.dart';
import 'package:gatekeeper_app/services/access_session_polling_policy.dart';
import 'package:gatekeeper_app/services/mobile_identity_service.dart';
import 'package:gatekeeper_app/services/native_gatt_worker_health.dart';

void main() {
  test('only a recent succeeded exact Target session starts bounded polling',
      () {
    final health = NativeGattWorkerHealth.fromMap(<Object?, Object?>{
      'lastSession': <Object?, Object?>{
        'state': 'SUCCEEDED',
        'updatedEpochMs': 1000,
        'targetSessionId': '10213243-5465-4687-98a9-bacbdcedfe0f',
      },
    });

    final candidate = AccessSessionPollingPolicy.candidate(
      health,
      now: DateTime.fromMillisecondsSinceEpoch(31 * 1000),
    );

    expect(candidate?.targetSessionId, '10213243-5465-4687-98a9-bacbdcedfe0f');
    expect(candidate?.remaining, const Duration(seconds: 90));
    expect(AccessSessionPollingPolicy.interval, const Duration(seconds: 4));
    expect(
      AccessSessionPollingPolicy.maximumWindow,
      const Duration(seconds: 120),
    );
    expect(health.lastSessionState, 'SUCCEEDED');
    final combinedRequestsPerMinute = 2 *
        ((60 ~/ AccessSessionPollingPolicy.interval.inSeconds) +
            4); // access polls + status/activity refreshes, for two phones
    expect(combinedRequestsPerMinute, lessThan(40));
  });

  test('HTTP outcomes allow only bounded transient retries', () {
    expect(
      AccessSessionPollingPolicy.nextDelay(
        outcome: MobilePersonalActivityOutcome.success,
        consecutiveTransientFailures: 0,
      ),
      const Duration(seconds: 4),
    );
    expect(
      AccessSessionPollingPolicy.nextDelay(
        outcome: MobilePersonalActivityOutcome.retryableFailure,
        consecutiveTransientFailures: 1,
      ),
      const Duration(seconds: 4),
    );
    expect(
      AccessSessionPollingPolicy.nextDelay(
        outcome: MobilePersonalActivityOutcome.retryableFailure,
        consecutiveTransientFailures: 2,
      ),
      const Duration(seconds: 8),
    );
    expect(
      AccessSessionPollingPolicy.nextDelay(
        outcome: MobilePersonalActivityOutcome.retryableFailure,
        consecutiveTransientFailures: 3,
      ),
      const Duration(seconds: 16),
    );
    expect(
      AccessSessionPollingPolicy.nextDelay(
        outcome: MobilePersonalActivityOutcome.retryableFailure,
        consecutiveTransientFailures: 4,
      ),
      isNull,
    );
    for (final outcome in <MobilePersonalActivityOutcome>[
      MobilePersonalActivityOutcome.accessDenied,
      MobilePersonalActivityOutcome.terminalFailure,
    ]) {
      expect(
        AccessSessionPollingPolicy.nextDelay(
          outcome: outcome,
          consecutiveTransientFailures: 0,
        ),
        isNull,
      );
    }
  });

  test('rate limiting respects Retry-After without polling below four seconds',
      () {
    expect(
      AccessSessionPollingPolicy.nextDelay(
        outcome: MobilePersonalActivityOutcome.rateLimited,
        consecutiveTransientFailures: 0,
        retryAfter: const Duration(seconds: 17),
      ),
      const Duration(seconds: 17),
    );
    expect(
      AccessSessionPollingPolicy.nextDelay(
        outcome: MobilePersonalActivityOutcome.rateLimited,
        consecutiveTransientFailures: 0,
        retryAfter: const Duration(seconds: 1),
      ),
      const Duration(seconds: 4),
    );
    expect(
      AccessSessionPollingPolicy.nextDelay(
        outcome: MobilePersonalActivityOutcome.rateLimited,
        consecutiveTransientFailures: 0,
      ),
      const Duration(seconds: 30),
    );
  });

  test('failed, stale, or non-canonical sessions never poll', () {
    NativeGattWorkerHealth health(
      String state,
      int updatedEpochMs,
      String targetSessionId,
    ) =>
        NativeGattWorkerHealth.fromMap(<Object?, Object?>{
          'lastSession': <Object?, Object?>{
            'state': state,
            'updatedEpochMs': updatedEpochMs,
            'targetSessionId': targetSessionId,
          },
        });
    final now = DateTime.fromMillisecondsSinceEpoch(121001);

    expect(
      AccessSessionPollingPolicy.candidate(
        health(
          'FAILED',
          120000,
          '10213243-5465-4687-98a9-bacbdcedfe0f',
        ),
        now: now,
      ),
      isNull,
    );
    expect(
      AccessSessionPollingPolicy.candidate(
        health(
          'SUCCEEDED',
          1000,
          '10213243-5465-4687-98a9-bacbdcedfe0f',
        ),
        now: now,
      ),
      isNull,
    );
    expect(
      AccessSessionPollingPolicy.candidate(
        health(
          'SUCCEEDED',
          120000,
          '10213243-5465-1687-98a9-bacbdcedfe0f',
        ),
        now: now,
      ),
      isNull,
    );
  });
}
