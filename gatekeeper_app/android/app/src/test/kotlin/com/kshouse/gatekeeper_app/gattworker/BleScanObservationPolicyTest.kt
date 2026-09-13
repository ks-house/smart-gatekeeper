package com.kshouse.gatekeeper_app.gattworker

import com.kshouse.gatekeeper_app.blewake.*
import org.junit.Assert.*
import org.junit.Test

class BleScanObservationPolicyTest {
  // Source-derived firmware 494 iBeacon contract (not an over-the-air capture).
  // Major/minor 1, Tx-power example -59; ready-v1 is separate service data.
  private val installed494 = byteArrayOf(0x02, 0x15, 0xa1.toByte(), 0xb2.toByte(), 0xc3.toByte(),
    0xd4.toByte(), 0xe5.toByte(), 0xf6.toByte(), 0x78, 0x90.toByte(), 0xab.toByte(), 0xcd.toByte(),
    0xef.toByte(), 0x12, 0x34, 0x56, 0x78, 0x90.toByte(), 0, 1, 0, 1, 0xc5.toByte())

  @Test fun installedManufacturerStillMatchesWhenScanResponseIsMissing() {
    assertTrue(BleWakeContract.matchesManufacturerData(installed494))
    assertEquals(BleScanObservationPolicy.Hint.MISSING, BleScanObservationPolicy.hint(null))
    assertEquals(BleScanObservationPolicy.Hint.READY,
      BleScanObservationPolicy.hint(byteArrayOf(1, 1, -1, -1, -1, -1)))
    assertEquals(BleScanObservationPolicy.Hint.NOT_READY,
      BleScanObservationPolicy.hint(byteArrayOf(1, 0, 42, 0, 0, 0)))
    assertEquals(BleScanObservationPolicy.Hint.MALFORMED,
      BleScanObservationPolicy.hint(byteArrayOf(1, 1, 42)))
    assertFalse(BleWakeContract.matchesManufacturerData(installed494.copyOf(18)))
    assertFalse(BleWakeContract.matchesManufacturerData(installed494.copyOf().also { it[17] = 0 }))
  }

  @Test fun invalidFutureAndOldBatchTimestampsCannotRefreshRfEvidence() {
    assertNull(BleScanObservationPolicy.ageMs(0, 10_000_000_000))
    assertNull(BleScanObservationPolicy.ageMs(10_000_000_001, 10_000_000_000))
    for (age in listOf(null, Double.NaN, Double.POSITIVE_INFINITY, -1.0, 5_000.001)) {
      assertFalse(BleScanObservationPolicy.fresh(age))
      assertNull(BleScanObservationPolicy.packetEpochMs(100_000, age))
    }
    assertEquals(95_000L, BleScanObservationPolicy.packetEpochMs(100_000, 5_000.0))
  }

  @Test fun strongStalePacketDoesNotMaskFreshWeakerTargetInOneBatch() {
    data class Packet(val age: Double, val rssi: Int, val timestamp: Long)
    val stale = Packet(60_000.0, -20, 1)
    val fresh = Packet(100.0, -85, 2)
    assertEquals(fresh, BleScanObservationPolicy.selectMatching(listOf(stale, fresh),
      { it.age }, { it.rssi }, { it.timestamp }))
  }

  @Test fun callbackFilterHintAndStaleCountersAreDistinctAndDoNotManufactureReception() {
    val counters = BleScanCounters()
    val missing = BleScanObservationPolicy.Hint.MISSING
    assertNull(counters.callback(0, 1, 3, listOf(60_000.0 to missing)))
    assertNull(counters.callback(0, 4, 1, listOf(1.0 to missing)))
    assertNull(counters.callback(3, 1, 1, listOf(1.0 to missing)))
    assertNull(counters.callback(0, 1, 0, emptyList()))
    assertEquals(0L, counters.snapshot()["freshMatchCount"])
    assertEquals(3L, counters.snapshot()["filterMatchCount"])
    assertEquals(1L, counters.snapshot()["staleMatchCount"])
    assertEquals(1L, counters.snapshot()["emptyCallbackCount"])
    assertEquals(1L, counters.snapshot()["callbackErrorCount"])
    assertEquals(10.0, counters.callback(0, 2, 3, listOf(10.0 to missing,
      20.0 to BleScanObservationPolicy.Hint.MALFORMED, 30.0 to BleScanObservationPolicy.Hint.NOT_READY)))
    assertEquals(3L, counters.snapshot()["freshMatchCount"])
    assertEquals(1L, counters.snapshot()["missingReadyHintCount"])
    assertEquals(1L, counters.snapshot()["malformedReadyHintCount"])
    assertEquals(1L, counters.snapshot()["targetNotReadyCount"])
  }

  @Test fun countersAreSaturatedClosedAndRestoreWithoutAcceptingRawFields() {
    val counts = BleScanCounters(mapOf("callbackCount" to Long.MAX_VALUE, "rawAddress" to 1))
    counts.add("callbackCount", Long.MAX_VALUE)
    counts.add("rawAddress")
    counts.add("resultCount", -1)
    assertEquals(BleScanCounters.MAX, counts.snapshot()["callbackCount"])
    assertEquals(0L, counts.snapshot()["resultCount"])
    assertEquals(BleScanCounters.KEYS, counts.snapshot().keys)
    assertEquals(counts.snapshot(), BleScanCounters(counts.snapshot()).snapshot())
  }
}
