package com.kshouse.gatekeeper_app.gattworker

import com.kshouse.gatekeeper_app.blewake.BleScanRecoveryPolicy
import org.junit.Assert.*
import org.junit.Test

class BleScanRecoveryPolicyTest {
  @Test fun freshRegistrationDoesNotRestartBecauseYesterdayHadNoPackets() {
    assertFalse(BleScanRecoveryPolicy.shouldRefresh(1_000_000, 999_000, 1))
    assertFalse(BleScanRecoveryPolicy.shouldRefresh(1_000_000, 999_000, null))
  }
  @Test fun recentReceptionPreservesAnOldRegistration() {
    assertFalse(BleScanRecoveryPolicy.shouldRefresh(2_000_000, 1, 1_999_000))
  }
  @Test fun prolongedSilenceRefreshesOncePerQuietWindow() {
    val now = BleScanRecoveryPolicy.QUIET_REFRESH_MS + 100
    assertTrue(BleScanRecoveryPolicy.shouldRefresh(now, 100, null))
    assertFalse(BleScanRecoveryPolicy.shouldRefresh(now + 1, now, null))
  }
  @Test fun absentEvidenceAndClockRollbackRequireReconciliation() {
    assertTrue(BleScanRecoveryPolicy.shouldRefresh(100, null, null))
    assertTrue(BleScanRecoveryPolicy.shouldRefresh(100, 200, null))
    assertFalse(BleScanRecoveryPolicy.shouldRefresh(101, 100, 999_999))
  }
}
