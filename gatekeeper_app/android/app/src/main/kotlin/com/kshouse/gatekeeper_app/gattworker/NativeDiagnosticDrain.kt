package com.kshouse.gatekeeper_app.gattworker

import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter

/** Shared by the actual Worker and deterministic network/clock/queue regression tests. */
internal object NativeDiagnosticDrain {
  const val MAX_BATCHES = 4
  const val BUDGET_MS = 30_000L
  enum class Disposition { ACCEPTED, RETRY, QUARANTINE, AUTH_REQUIRED, CANCELLED }
  data class Attempt(val code: String, val disposition: Disposition, val retryAfterMs: Long = 0,
                     val targetBaseline: NativeDiagnosticBaseline? = null)
  interface Port {
    fun stopped(): Boolean
    fun elapsedMs(): Long
    fun next(): Boolean
    fun send(): Attempt
    fun finish(attempt: Attempt)
    fun continueLater()
  }

  fun run(port: Port): Int {
    val started = port.elapsedMs()
    var completed = 0
    while (!port.stopped() && completed < MAX_BATCHES && port.elapsedMs() - started < BUDGET_MS) {
      if (!port.next()) return completed
      val attempt = port.send()
      port.finish(attempt)
      if (attempt.disposition != Disposition.ACCEPTED && attempt.disposition != Disposition.QUARANTINE) {
        if (attempt.disposition == Disposition.RETRY) port.continueLater()
        return completed
      }
      completed++
    }
    if (!port.stopped()) port.continueLater()
    return completed
  }

  fun http(status: Int, accepted: Boolean, retryAfter: String?, now: Long): Attempt = when {
    status in 200..299 && accepted -> Attempt("ACCEPTED", Disposition.ACCEPTED)
    status in 200..299 -> Attempt("INVALID_ACK", Disposition.RETRY)
    status == 401 || status == 403 -> Attempt("HTTP_$status", Disposition.AUTH_REQUIRED)
    status == 400 || status == 413 || status == 422 -> Attempt("HTTP_$status", Disposition.QUARANTINE)
    else -> Attempt("HTTP_$status", Disposition.RETRY, retryAfterMs(retryAfter, now))
  }

  fun delayMs(attempt: Int, retryAfterMs: Long = 0): Long = maxOf(
    (30_000L * (1L shl (attempt - 1).coerceIn(0, 5))).coerceAtMost(15 * 60_000L), retryAfterMs)

  fun retryAfterMs(value: String?, now: Long): Long {
    if (value == null || value.length > 128) return 0
    val seconds = value.trim().toLongOrNull()
    if (seconds != null) return seconds.coerceIn(0, 7 * 24 * 3600).times(1000)
    return runCatching {
      (ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli() - now)
        .coerceIn(0, 7 * 24 * 3600_000L)
    }.getOrDefault(0)
  }

  /** A RUNNING predecessor requires a successor; KEEP would lose this wake. */
  fun needsSuccessor(states: Collection<String>): Boolean = states.none { it == "ENQUEUED" || it == "BLOCKED" }
}
