package com.kshouse.gatekeeper_app.blewake

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class BleWakeMetricsTest {
  @Test
  fun summarizesTwentyTrialGateWithNearestRankPercentiles() {
    val observations = (1..20).map { BleWakeObservation(success = true, latencyMs = it.toDouble()) }
    val summary = BleWakeMetrics.summarize(observations)

    assertEquals(20, summary.attempts)
    assertEquals(20, summary.successes)
    assertEquals(1.0, summary.successRate, 0.0)
    assertEquals(10.0, summary.p50LatencyMs!!, 0.0)
    assertEquals(19.0, summary.p95LatencyMs!!, 0.0)
    assertEquals(20.0, summary.maxLatencyMs!!, 0.0)
  }

  @Test
  fun reportsFailuresWithoutInventingLatency() {
    val summary = BleWakeMetrics.summarize(
      listOf(
        BleWakeObservation(success = false, latencyMs = null),
        BleWakeObservation(success = true, latencyMs = 12.5),
      ),
    )
    assertEquals(0.5, summary.successRate, 0.0)
    assertEquals(12.5, summary.p95LatencyMs!!, 0.0)
  }

  @Test
  fun emptyInputKeepsLatencyPending() {
    val summary = BleWakeMetrics.summarize(emptyList())
    assertEquals(0, summary.attempts)
    assertNull(summary.p50LatencyMs)
    assertNull(summary.p95LatencyMs)
    assertNull(summary.maxLatencyMs)
  }
}
