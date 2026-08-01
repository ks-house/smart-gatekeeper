package com.kshouse.gatekeeper_app.blewake

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BleWakeContractTest {
  @Test
  fun manufacturerPrefixMatchesCurrentTargetIBeaconContract() {
    assertArrayEquals(
      byteArrayOf(
        0x02, 0x15,
        0xA1.toByte(), 0xB2.toByte(), 0xC3.toByte(), 0xD4.toByte(),
        0xE5.toByte(), 0xF6.toByte(), 0x78, 0x90.toByte(),
        0xAB.toByte(), 0xCD.toByte(), 0xEF.toByte(), 0x12, 0x34, 0x56, 0x78, 0x90.toByte(),
      ),
      BleWakeContract.manufacturerDataPrefix,
    )
  }

  @Test
  fun filterAcceptsVariableMajorMinorAndTxPower() {
    val completeIBeaconData = BleWakeContract.manufacturerDataPrefix +
      byteArrayOf(0x00, 0x01, 0x00, 0x02, 0xC5.toByte())
    assertTrue(BleWakeContract.matchesManufacturerData(completeIBeaconData))
  }

  @Test
  fun filterRejectsWrongUuidOrTruncatedPayload() {
    val wrongUuid = BleWakeContract.manufacturerDataPrefix.copyOf().also { it[2] = 0x00 }
    assertFalse(BleWakeContract.matchesManufacturerData(wrongUuid))
    assertFalse(BleWakeContract.matchesManufacturerData(byteArrayOf(0x02, 0x15)))
  }
}
