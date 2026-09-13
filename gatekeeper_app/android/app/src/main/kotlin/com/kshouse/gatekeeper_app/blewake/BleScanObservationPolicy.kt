package com.kshouse.gatekeeper_app.blewake

/** Pure replay seam for installed iBeacon/scan-response packets. No locator is evidence here. */
internal object BleScanObservationPolicy {
  enum class Hint { MISSING, MALFORMED, READY, NOT_READY }

  fun hint(bytes: ByteArray?): Hint = when {
    bytes == null -> Hint.MISSING
    PresenceReadyHint.parse(bytes) == null -> Hint.MALFORMED
    PresenceReadyHint.parse(bytes)?.ready == true -> Hint.READY
    else -> Hint.NOT_READY
  }

  fun ageMs(timestampNanos: Long, receivedNanos: Long): Double? =
    if (timestampNanos <= 0 || receivedNanos < timestampNanos) null
    else (receivedNanos - timestampNanos) / 1_000_000.0

  fun fresh(ageMs: Double?): Boolean = ageMs != null && ageMs.isFinite() &&
    ageMs >= 0 && ageMs <= ContinuousPresencePolicy.FRESH_MS

  fun positiveCallback(error: Int, type: Int): Boolean = error == 0 && type in listOf(1, 2)

  fun <T> selectMatching(results: List<T>, age: (T) -> Double?, rssi: (T) -> Int,
                         timestamp: (T) -> Long): T? =
    results.filter { fresh(age(it)) }.maxByOrNull(rssi) ?: results.maxByOrNull(timestamp)

  // Callback and filter totals are observations, including stale/lost batches;
  // only fresh positive matches may advance the last RF packet time.
  fun packetEpochMs(receivedEpochMs: Long, ageMs: Double?): Long? =
    if (fresh(ageMs)) (receivedEpochMs - ageMs!!.toLong()).takeIf { it > 0 } else null
}

internal enum class BleDispatchDiagnostic {
  ATTEMPT, ENQUEUED, SKIPPED, OWNER_WAIT, ENQUEUE_FAILED,
}

/** Counters saturate, and expose only a fixed set of aggregate names. */
internal class BleScanCounters(initial: Map<String, Long> = emptyMap()) {
  private val values = KEYS.associateWith { (initial[it] ?: 0).coerceIn(0, MAX) }.toMutableMap()

  fun add(key: String, count: Long = 1) {
    if (key !in KEYS || count <= 0) return
    values[key] = ((values[key] ?: 0) + count.coerceAtMost(MAX)).coerceAtMost(MAX)
  }

  fun snapshot(): Map<String, Long> = values.toMap()

  /** Returns only the age of a positive, fresh matching packet, never callback arrival age. */
  fun callback(error: Int, type: Int, resultCount: Int,
               matches: List<Pair<Double?, BleScanObservationPolicy.Hint>>): Double? {
    add("callbackCount")
    if (resultCount == 0) add("emptyCallbackCount")
    add("resultCount", resultCount.toLong())
    add("filterMatchCount", matches.size.toLong())
    if (error != 0) add("callbackErrorCount")
    if (!BleScanObservationPolicy.positiveCallback(error, type)) return null
    var newestAge: Double? = null
    for ((age, hint) in matches) {
      if (!BleScanObservationPolicy.fresh(age)) {
        add("staleMatchCount")
        continue
      }
      add("freshMatchCount")
      newestAge = minOf(newestAge ?: Double.MAX_VALUE, age!!)
      when (hint) {
        BleScanObservationPolicy.Hint.MISSING -> add("missingReadyHintCount")
        BleScanObservationPolicy.Hint.MALFORMED -> add("malformedReadyHintCount")
        BleScanObservationPolicy.Hint.NOT_READY -> add("targetNotReadyCount")
        else -> Unit
      }
    }
    return newestAge
  }

  companion object {
    const val MAX = 2_147_483_647L
    val KEYS = setOf("callbackCount", "emptyCallbackCount", "resultCount", "filterMatchCount",
      "freshMatchCount", "staleMatchCount", "missingReadyHintCount", "malformedReadyHintCount",
      "targetNotReadyCount", "callbackErrorCount", "dispatchAttemptCount", "dispatchEnqueuedCount",
      "dispatchSkippedCount", "ownerWaitCount", "enqueueFailureCount")
  }
}
