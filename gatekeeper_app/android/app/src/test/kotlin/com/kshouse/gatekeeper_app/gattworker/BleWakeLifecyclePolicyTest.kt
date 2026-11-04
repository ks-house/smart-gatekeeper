package com.kshouse.gatekeeper_app.gattworker

import com.kshouse.gatekeeper_app.blewake.BleWakeLifecycleRecoveryPolicy
import org.junit.Assert.*
import org.junit.Test

class BleWakeLifecyclePolicyTest {
  @Test fun processRecreationRetainsMonotonicCooldownWithoutWallClockInput() {
    assertTrue(BleWakeLifecycleRecoveryPolicy.maySchedule(0, null))
    assertFalse(BleWakeLifecycleRecoveryPolicy.maySchedule(59_999, 0))
    assertTrue(BleWakeLifecycleRecoveryPolicy.maySchedule(60_000, 0))
    assertFalse(BleWakeLifecycleRecoveryPolicy.maySchedule(Long.MAX_VALUE, Long.MAX_VALUE - 59_999))
    assertTrue(BleWakeLifecycleRecoveryPolicy.maySchedule(Long.MAX_VALUE, Long.MAX_VALUE - 60_000))
    // A reboot resets elapsed time and permits a new native registration check.
    assertTrue(BleWakeLifecycleRecoveryPolicy.maySchedule(10, 1_000_000))
    assertFalse(BleWakeLifecycleRecoveryPolicy.maySchedule(-1, 0))
  }

  @Test fun lifecycleEventsCanAddOnlyOnePendingSuccessor() {
    assertTrue(BleWakeLifecycleRecoveryPolicy.needsSuccessor(emptyList()))
    assertTrue(BleWakeLifecycleRecoveryPolicy.needsSuccessor(listOf("SUCCEEDED", "RUNNING")))
    assertTrue(BleWakeLifecycleRecoveryPolicy.needsSuccessor(listOf("CANCELLED")))
    assertFalse(BleWakeLifecycleRecoveryPolicy.needsSuccessor(listOf("ENQUEUED")))
    assertFalse(BleWakeLifecycleRecoveryPolicy.needsSuccessor(listOf("RUNNING", "BLOCKED")))
    assertFalse(BleWakeLifecycleRecoveryPolicy.needsSuccessor(listOf("RUNNING", "RUNNING")))
  }
}
