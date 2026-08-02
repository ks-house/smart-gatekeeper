package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

data class ValidatedRemoteFlag(
  val enabled: Boolean,
  val validated: Boolean,
  val revision: String,
  val expiresEpochMs: Long,
)

data class FeatureFlagDecision(
  val newWorkerEnabled: Boolean,
  val owner: String,
  val status: String,
)

object BleGattFeatureFlagPolicy {
  fun evaluate(snapshot: ValidatedRemoteFlag?, nowEpochMs: Long): FeatureFlagDecision = when {
    snapshot == null -> FeatureFlagDecision(false, "legacy", "default_off")
    !snapshot.validated -> FeatureFlagDecision(false, "legacy", "remote_unvalidated")
    snapshot.expiresEpochMs <= nowEpochMs -> FeatureFlagDecision(false, "legacy", "remote_stale")
    !snapshot.enabled -> FeatureFlagDecision(false, "legacy", "remote_disabled")
    else -> FeatureFlagDecision(true, "native_gatt", "remote_enabled")
  }
}

class BleGattFeatureFlagStore(private val context: Context) {
  fun decision(nowEpochMs: Long = System.currentTimeMillis()): FeatureFlagDecision =
    BleGattFeatureFlagPolicy.evaluate(readSnapshot(), nowEpochMs)

  /** Native management-plane seam. Flutter's bridge intentionally does not expose this mutation. */
  fun applyValidatedRemoteSnapshot(snapshot: ValidatedRemoteFlag): Boolean = prefs.edit()
    .putBoolean(KEY_PRESENT, true)
    .putBoolean(KEY_ENABLED, snapshot.enabled)
    .putBoolean(KEY_VALIDATED, snapshot.validated)
    .putString(KEY_REVISION, snapshot.revision)
    .putLong(KEY_EXPIRES, snapshot.expiresEpochMs)
    .commit()

  private fun readSnapshot(): ValidatedRemoteFlag? {
    if (!prefs.getBoolean(KEY_PRESENT, false)) return null
    return ValidatedRemoteFlag(
      enabled = prefs.getBoolean(KEY_ENABLED, false),
      validated = prefs.getBoolean(KEY_VALIDATED, false),
      revision = prefs.getString(KEY_REVISION, "").orEmpty(),
      expiresEpochMs = prefs.getLong(KEY_EXPIRES, 0),
    )
  }

  private val prefs
    get() = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

  companion object {
    const val PREFS = "ble_gatt_worker_flags"
    const val KEY_PRESENT = "remote_present"
    const val KEY_ENABLED = "remote_enabled"
    const val KEY_VALIDATED = "remote_validated"
    const val KEY_EXPIRES = "remote_expires_epoch_ms"
    private const val KEY_REVISION = "remote_revision"
  }
}

enum class DurableSessionState {
  QUEUED,
  RUNNING,
  RETRY_PENDING,
  SUCCEEDED,
  FAILED,
  DISABLED,
}

data class DurableGattSession(
  val id: String,
  val presenceFingerprint: String,
  val deviceAddress: String,
  val credentialIdHex: String,
  val createdEpochMs: Long,
  val updatedEpochMs: Long,
  val attempt: Int,
  val state: DurableSessionState,
  val reasonCode: String? = null,
  val latencyMs: Long? = null,
  val activeAclVersion: Long? = null,
) {
  fun redactedMap(): Map<String, Any?> = mapOf(
    "sessionId" to id,
    "attempt" to attempt,
    "state" to state.name,
    "reasonCode" to reasonCode,
    "latencyMs" to latencyMs,
    "activeAclVersion" to activeAclVersion,
    "updatedEpochMs" to updatedEpochMs,
  )
}

interface DurableSessionLedger {
  fun findCoalescible(fingerprint: String, nowEpochMs: Long, windowMs: Long): DurableGattSession?
  fun create(fingerprint: String, deviceAddress: String, credentialIdHex: String, nowEpochMs: Long): DurableGattSession
  fun get(id: String): DurableGattSession?
  fun update(session: DurableGattSession)
  fun last(): DurableGattSession?
}

class PresenceCoalescer(
  private val ledger: DurableSessionLedger,
  private val fingerprintKey: ByteArray,
  private val windowMs: Long = 30_000,
) {
  fun enqueue(
    deviceAddress: String,
    credentialIdHex: String,
    nowEpochMs: Long,
  ): Pair<DurableGattSession, Boolean> {
    val fingerprint = fingerprint(deviceAddress)
    val existing = ledger.findCoalescible(fingerprint, nowEpochMs, windowMs)
    if (existing != null) return existing to true
    return ledger.create(fingerprint, deviceAddress, credentialIdHex, nowEpochMs) to false
  }

  private fun fingerprint(deviceAddress: String): String {
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(fingerprintKey, "HmacSHA256"))
    return mac.doFinal("i4-presence-v1|$deviceAddress".toByteArray(Charsets.UTF_8)).toHex()
  }
}

class SharedPreferencesSessionLedger(private val context: Context) : DurableSessionLedger {
  @Synchronized
  override fun findCoalescible(
    fingerprint: String,
    nowEpochMs: Long,
    windowMs: Long,
  ): DurableGattSession? = readAll().lastOrNull {
    it.presenceFingerprint == fingerprint &&
      it.state in ACTIVE_STATES &&
      nowEpochMs - it.createdEpochMs in 0..windowMs
  }

  @Synchronized
  override fun create(
    fingerprint: String,
    deviceAddress: String,
    credentialIdHex: String,
    nowEpochMs: Long,
  ): DurableGattSession {
    val session = DurableGattSession(
      id = UUID.randomUUID().toString(),
      presenceFingerprint = fingerprint,
      deviceAddress = deviceAddress,
      credentialIdHex = credentialIdHex,
      createdEpochMs = nowEpochMs,
      updatedEpochMs = nowEpochMs,
      attempt = 0,
      state = DurableSessionState.QUEUED,
    )
    val all = (readAll() + session).takeLast(MAX_SESSIONS)
    persist(all)
    return session
  }

  @Synchronized
  override fun get(id: String): DurableGattSession? = readAll().firstOrNull { it.id == id }

  @Synchronized
  override fun update(session: DurableGattSession) {
    val all = readAll().filterNot { it.id == session.id } + session
    persist(all.takeLast(MAX_SESSIONS))
  }

  @Synchronized
  override fun last(): DurableGattSession? = readAll().maxByOrNull { it.updatedEpochMs }

  private fun readAll(): List<DurableGattSession> = try {
    val array = JSONArray(prefs.getString(KEY_SESSIONS, "[]"))
    buildList {
      for (index in 0 until array.length()) add(fromJson(array.getJSONObject(index)))
    }
  } catch (_: Exception) {
    emptyList()
  }

  private fun persist(sessions: List<DurableGattSession>) {
    val array = JSONArray()
    sessions.forEach { array.put(toJson(it)) }
    check(prefs.edit().putString(KEY_SESSIONS, array.toString()).commit()) {
      "failed to persist GATT session ledger"
    }
  }

  private fun toJson(session: DurableGattSession): JSONObject = JSONObject()
    .put("id", session.id)
    .put("presence_fingerprint", session.presenceFingerprint)
    .put("device_address", session.deviceAddress)
    .put("credential_id_hex", session.credentialIdHex)
    .put("created_epoch_ms", session.createdEpochMs)
    .put("updated_epoch_ms", session.updatedEpochMs)
    .put("attempt", session.attempt)
    .put("state", session.state.name)
    .put("reason_code", session.reasonCode)
    .put("latency_ms", session.latencyMs)
    .put("active_acl_version", session.activeAclVersion)

  private fun fromJson(value: JSONObject): DurableGattSession = DurableGattSession(
    id = value.getString("id"),
    presenceFingerprint = value.getString("presence_fingerprint"),
    deviceAddress = value.getString("device_address"),
    credentialIdHex = value.getString("credential_id_hex"),
    createdEpochMs = value.getLong("created_epoch_ms"),
    updatedEpochMs = value.getLong("updated_epoch_ms"),
    attempt = value.getInt("attempt"),
    state = DurableSessionState.valueOf(value.getString("state")),
    reasonCode = value.optString("reason_code").takeIf { it.isNotEmpty() && it != "null" },
    latencyMs = if (value.isNull("latency_ms")) null else value.getLong("latency_ms"),
    activeAclVersion = if (value.isNull("active_acl_version")) null else value.getLong("active_acl_version"),
  )

  private val prefs
    get() = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

  companion object {
    private const val PREFS = "ble_gatt_worker_sessions"
    private const val KEY_SESSIONS = "sessions_v1"
    private const val MAX_SESSIONS = 50
    private val ACTIVE_STATES = setOf(
      DurableSessionState.QUEUED,
      DurableSessionState.RUNNING,
      DurableSessionState.RETRY_PENDING,
    )
  }
}

class BleCredentialConfigStore(private val context: Context) {
  fun credentialId(): ByteArray? = context
    .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    .getString(KEY_CREDENTIAL_ID, null)
    ?.takeIf { it.matches(Regex("^[0-9a-f]{32}$")) }
    ?.hexToBytes()

  /** Native enrollment seam; private key material is never accepted by this API. */
  fun applyCredentialId(credentialId: ByteArray): Boolean {
    require(credentialId.size == 16) { "credential id length" }
    return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
      .edit()
      .putString(KEY_CREDENTIAL_ID, credentialId.toHex())
      .commit()
  }

  private companion object {
    const val PREFS = "ble_gatt_worker_credential"
    const val KEY_CREDENTIAL_ID = "credential_id_hex"
  }
}

object BleGattWorkerSecrets {
  fun fingerprintKey(context: Context): ByteArray {
    val prefs = context.getSharedPreferences("ble_gatt_worker_internal", Context.MODE_PRIVATE)
    val existing = prefs.getString("fingerprint_key_hex", null)
    if (existing != null && existing.matches(Regex("^[0-9a-f]{64}$"))) return existing.hexToBytes()
    val generated = ByteArray(32).also(java.security.SecureRandom()::nextBytes)
    check(prefs.edit().putString("fingerprint_key_hex", generated.toHex()).commit()) {
      "failed to persist fingerprint key"
    }
    return generated
  }
}
