package com.kshouse.gatekeeper_app.gattworker

import android.bluetooth.le.ScanSettings
import com.kshouse.gatekeeper_app.blewake.BleWakeDispatchAction
import com.kshouse.gatekeeper_app.blewake.BleWakeDispatchPolicy
import com.kshouse.gatekeeper_app.blewake.BleWakeEvent
import org.junit.Assert.assertEquals
import org.junit.Test

class BleWakeDispatchPolicyTest {
  @Test
  fun `first match dispatches presence`() {
    assertEquals(
      BleWakeDispatchAction.PRESENCE,
      BleWakeDispatchPolicy.classify(event(ScanSettings.CALLBACK_TYPE_FIRST_MATCH)),
    )
  }

  @Test
  fun `match lost dispatches exit instead of another access`() {
    assertEquals(
      BleWakeDispatchAction.EXIT,
      BleWakeDispatchPolicy.classify(event(ScanSettings.CALLBACK_TYPE_MATCH_LOST)),
    )
  }

  @Test
  fun `scan error never infers an exit`() {
    assertEquals(
      BleWakeDispatchAction.IGNORE,
      BleWakeDispatchPolicy.classify(
        event(ScanSettings.CALLBACK_TYPE_MATCH_LOST, errorCode = 2),
      ),
    )
  }

  private fun event(callbackType: Int, errorCode: Int = 0) = BleWakeEvent(
    source = "ble_scan",
    scenario = "field",
    iteration = null,
    success = true,
    receivedEpochMs = 1,
    receivedElapsedMs = 1,
    scanTimestampNanos = 1,
    latencyMs = 1.0,
    callbackType = callbackType,
    errorCode = errorCode,
    resultCount = 1,
    strongestRssi = -50,
    processId = "test",
    screenInteractive = false,
    deviceAddress = "00:11:22:33:44:55",
  )
}
