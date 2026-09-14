package com.kshouse.gatekeeper_app.blewake

/** Finite owner transaction. The adapter serializes calls with the registrar. */
internal class ForegroundDiscoverySession(private val port: Port) {
  interface Port {
    fun acquire(): Boolean
    fun stopPrimary()
    fun startAlternative()
    fun stopAlternative()
    fun release()
    fun restore(): String
  }

  var stage = "WAITING_PRIMARY"
    private set
  var restoreStatus: String? = null
    private set
  @Volatile var active = false
    private set
  val acceptingResults: Boolean get() = active && stage == "SCANNING"
  var resultCount = 0
    private set
  var candidateCount = 0
    private set
  var matchCount = 0
    private set
  var errorCount = 0
    private set
  var errorCode: Int? = null
    private set

  fun start(eligible: Boolean) {
    if (active || stage != "WAITING_PRIMARY") return
    if (!eligible) { stage = "ENVIRONMENT_BLOCKED"; return }
    val acquired = try { port.acquire() } catch (_: RuntimeException) { false }
    if (!acquired) { stage = "OWNER_BUSY"; return }
    active = true
    stage = "SCANNING"
    try {
      port.stopPrimary()
      port.startAlternative()
    } catch (_: RuntimeException) { error(null) }
  }

  fun sample(candidate: Boolean, exactFreshMatch: Boolean): Boolean {
    if (!acceptingResults) return false
    resultCount = (resultCount + 1).coerceAtMost(MAX_COUNT)
    if (candidate) candidateCount = (candidateCount + 1).coerceAtMost(MAX_COUNT)
    if (exactFreshMatch) matchCount = (matchCount + 1).coerceAtMost(MAX_COUNT)
    return exactFreshMatch
  }

  fun error(code: Int?) {
    if (!acceptingResults) return
    errorCount = (errorCount + 1).coerceAtMost(MAX_COUNT)
    errorCode = code?.coerceIn(0, 65535)
    finish("SCAN_ERROR")
  }

  fun finish(outcome: String, restore: Boolean = true, radioDisabled: Boolean = false): Boolean {
    if (!active) return false
    stage = outcome
    try { port.stopAlternative() } catch (_: RuntimeException) {
      if (!radioDisabled) {
        // Unknown OS scan state: retain the kernel lease. Neither a new scan
        // nor GATT may start until a later cancellation confirms stop or BT is OFF.
        stage = "STOP_FAILED"
        errorCount = (errorCount + 1).coerceAtMost(MAX_COUNT)
        restoreStatus = "RESTORE_PENDING"
        return false
      }
    }
    try { port.release() } catch (_: RuntimeException) {
      stage = "RELEASE_FAILED"
      errorCount = (errorCount + 1).coerceAtMost(MAX_COUNT)
      restoreStatus = "RESTORE_PENDING"
      return false
    }
    active = false
    restoreStatus = if (restore) try { port.restore() }
      catch (_: RuntimeException) { "RESTORE_PENDING" } else "NOT_REQUESTED"
    return true
  }

  companion object {
    const val WINDOW_MS = 12_000L
    const val PRIMARY_GRACE_MS = 3_000L
    const val MAX_BATCH = 64
    fun inWindow(now: Long, deadline: Long): Boolean = now < deadline && now >= deadline - WINDOW_MS
    const val MAX_COUNT = 1_000_000
    fun candidate(data: ByteArray?): Boolean = data != null && data.size >= 2 &&
      data[0] == 0x02.toByte() && data[1] == 0x15.toByte()
  }
}
