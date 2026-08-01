package com.kshouse.gatekeeper_app.blewake

import kotlin.math.ceil

data class BleWakeObservation(
  val success: Boolean,
  val latencyMs: Double?,
)

data class BleWakeSummary(
  val attempts: Int,
  val successes: Int,
  val successRate: Double,
  val p50LatencyMs: Double?,
  val p95LatencyMs: Double?,
  val maxLatencyMs: Double?,
)

object BleWakeMetrics {
  fun summarize(observations: List<BleWakeObservation>): BleWakeSummary {
    val successfulLatencies = observations
      .asSequence()
      .filter { it.success }
      .mapNotNull { it.latencyMs }
      .sorted()
      .toList()
    val successes = observations.count { it.success }
    return BleWakeSummary(
      attempts = observations.size,
      successes = successes,
      successRate = if (observations.isEmpty()) 0.0 else successes.toDouble() / observations.size,
      p50LatencyMs = percentile(successfulLatencies, 0.50),
      p95LatencyMs = percentile(successfulLatencies, 0.95),
      maxLatencyMs = successfulLatencies.lastOrNull(),
    )
  }

  private fun percentile(sorted: List<Double>, quantile: Double): Double? {
    if (sorted.isEmpty()) return null
    val nearestRank = ceil(quantile * sorted.size).toInt().coerceIn(1, sorted.size)
    return sorted[nearestRank - 1]
  }
}
