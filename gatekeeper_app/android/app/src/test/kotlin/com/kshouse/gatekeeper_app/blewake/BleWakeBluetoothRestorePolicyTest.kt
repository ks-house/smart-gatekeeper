package com.kshouse.gatekeeper_app.blewake

import android.bluetooth.BluetoothAdapter
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BleWakeBluetoothRestorePolicyTest {
  @Test
  fun restoresOnlyOnFirstObservedStateOnWhenRegistrationWasRequested() {
    assertTrue(
      BleWakeBluetoothRestorePolicy.shouldRestore(
        BluetoothAdapter.ACTION_STATE_CHANGED,
        BluetoothAdapter.STATE_ON,
        BluetoothAdapter.STATE_TURNING_ON,
        registrationRequested = true,
      ),
    )
    assertFalse(
      BleWakeBluetoothRestorePolicy.shouldRestore(
        BluetoothAdapter.ACTION_STATE_CHANGED,
        BluetoothAdapter.STATE_ON,
        BluetoothAdapter.STATE_ON,
        registrationRequested = true,
      ),
    )
    assertFalse(
      BleWakeBluetoothRestorePolicy.shouldRestore(
        BluetoothAdapter.ACTION_STATE_CHANGED,
        BluetoothAdapter.STATE_ON,
        BluetoothAdapter.STATE_OFF,
        registrationRequested = false,
      ),
    )
  }

  @Test
  fun ignoresOffTurningAndUnrelatedBroadcasts() {
    for (
      state in listOf(
        BluetoothAdapter.STATE_OFF,
        BluetoothAdapter.STATE_TURNING_OFF,
        BluetoothAdapter.STATE_TURNING_ON,
      )
    ) {
      assertFalse(
        BleWakeBluetoothRestorePolicy.shouldRestore(
          BluetoothAdapter.ACTION_STATE_CHANGED,
          state,
          BluetoothAdapter.STATE_ON,
          registrationRequested = true,
        ),
      )
    }
    assertFalse(
      BleWakeBluetoothRestorePolicy.shouldRestore(
        IntentActionForTest,
        BluetoothAdapter.STATE_ON,
        BluetoothAdapter.STATE_OFF,
        registrationRequested = true,
      ),
    )
  }

  private companion object {
    const val IntentActionForTest = "com.kshouse.gatekeeper_app.UNRELATED"
  }
}
