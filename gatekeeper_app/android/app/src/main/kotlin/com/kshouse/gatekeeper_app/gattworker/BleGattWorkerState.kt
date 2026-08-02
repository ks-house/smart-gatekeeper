package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import android.util.AtomicFile
import com.flutterbeacon.CrossProcessBleOwnerCoordinator
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.RandomAccessFile
import java.util.UUID

data class AuthenticatedRemoteFlagState(
  val enabled: Boolean,
  val issuer: String,
  val authorityKeyId: String,
  val revision: Long,
  val issuedEpochMs: Long,
  val expiresEpochMs: Long,
  val credentialIdSha256: ByteArray,
  val credentialPublicKeySha256: ByteArray,
  val signatureDer: ByteArray,
)

data class FeatureFlagDecision(
  val newWorkerEnabled: Boolean,
  val owner: String,
  val status: String,
  val revision: Long? = null,
)

object BleGattFeatureFlagPolicy {
  fun evaluate(
    snapshot: AuthenticatedRemoteFlagState?,
    verification: FeatureFlagVerification?,
    nowEpochMs: Long,
  ): FeatureFlagDecision = when {
    snapshot == null -> FeatureFlagDecision(false, "legacy", "default_off")
    snapshot.expiresEpochMs <= nowEpochMs -> FeatureFlagDecision(false, "legacy", "remote_stale", snapshot.revision)
    verification == null || !verification.authenticated -> FeatureFlagDecision(
      false,
      "legacy",
      "remote_${verification?.status?.name?.lowercase() ?: "unverifiable"}",
      snapshot.revision,
    )
    !snapshot.enabled -> FeatureFlagDecision(false, "legacy", "remote_disabled", snapshot.revision)
    else -> FeatureFlagDecision(true, "native_gatt", "remote_authenticated", snapshot.revision)
  }
}

class BleGattFeatureFlagStore(private val context: Context) {
  fun decision(nowEpochMs: Long = System.currentTimeMillis()): FeatureFlagDecision {
    cleanupUnauthenticatedV1()
    val snapshot = readSnapshot()
    val credentialId = BleCredentialConfigStore(context).credentialId()
    var envelope: RemoteFeatureFlagEnvelope? = null
    try {
      val publicKeyHash = credentialId?.let(::credentialPublicKeyHash)
      envelope = if (
        snapshot != null &&
        credentialId != null &&
        snapshot.credentialIdSha256.contentEquals(GattCanonicalCodec.sha256(credentialId))
      ) {
        snapshot.toEnvelope(credentialId)
      } else {
        null
      }
      val verification = envelope?.let {
        RemoteFeatureFlagAuthenticator.verify(
          envelope = it,
          authority = AndroidFeatureFlagAuthorityConfig.read(context),
          expectedCredentialId = credentialId,
          expectedCredentialPublicKeySha256 = publicKeyHash,
          nowEpochMs = nowEpochMs,
        )
      }
      val decision = BleGattFeatureFlagPolicy.evaluate(snapshot, verification, nowEpochMs)
      val coordinator = CrossProcessBleOwnerCoordinator.forContext(context)
      if (!coordinator.setNativeRequested(decision.newWorkerEnabled)) {
        coordinator.setNativeRequested(false)
        return FeatureFlagDecision(false, "legacy", "owner_state_unavailable", decision.revision)
      }
      return decision
    } finally {
      credentialId?.fill(0)
      envelope?.credentialId?.fill(0)
    }
  }

  /**
   * Authenticated native management-plane seam. Flutter intentionally has no mutation bridge.
   * A revision must be signed, unexpired, strictly monotonic, and bound to the exact Keystore key.
   */
  fun applyAuthenticatedRemoteEnvelope(
    envelope: RemoteFeatureFlagEnvelope,
    nowEpochMs: Long = System.currentTimeMillis(),
  ): FeatureFlagVerification = try {
    withFlagUpdateLock {
      applyAuthenticatedRemoteEnvelopeLocked(envelope, nowEpochMs)
    }
  } catch (_: Exception) {
    FeatureFlagVerification(FeatureFlagVerificationStatus.MALFORMED)
  }

  private fun applyAuthenticatedRemoteEnvelopeLocked(
    envelope: RemoteFeatureFlagEnvelope,
    nowEpochMs: Long,
  ): FeatureFlagVerification {
    cleanupUnauthenticatedV1()
    val credentialId = BleCredentialConfigStore(context).credentialId()
    try {
      val publicKeyHash = credentialId?.let(::credentialPublicKeyHash)
      val verification = RemoteFeatureFlagAuthenticator.verify(
        envelope = envelope,
        authority = AndroidFeatureFlagAuthorityConfig.read(context),
        expectedCredentialId = credentialId,
        expectedCredentialPublicKeySha256 = publicKeyHash,
        nowEpochMs = nowEpochMs,
        minimumExclusiveRevision = readSnapshot()?.revision ?: 0,
      )
      if (!verification.authenticated) return verification
      val snapshot = AuthenticatedRemoteFlagState(
        enabled = envelope.enabled,
        issuer = envelope.issuer,
        authorityKeyId = envelope.authorityKeyId,
        revision = envelope.revision,
        issuedEpochMs = envelope.issuedEpochMs,
        expiresEpochMs = envelope.expiresEpochMs,
        credentialIdSha256 = GattCanonicalCodec.sha256(envelope.credentialId),
        credentialPublicKeySha256 = envelope.credentialPublicKeySha256.copyOf(),
        signatureDer = envelope.signatureDer.copyOf(),
      )
      check(persist(snapshot)) { "failed to persist authenticated remote flag" }
      decision(nowEpochMs)
      return verification
    } finally {
      credentialId?.fill(0)
    }
  }

  private fun credentialPublicKeyHash(credentialId: ByteArray): ByteArray? = try {
    GattCanonicalCodec.sha256(AndroidKeystoreCredentialSigner().publicKeySec1(credentialId))
  } catch (_: CredentialKeyUnavailableException) {
    null
  } catch (_: Exception) {
    null
  }

  private fun AuthenticatedRemoteFlagState.toEnvelope(credentialId: ByteArray) = RemoteFeatureFlagEnvelope(
    enabled = enabled,
    issuer = issuer,
    authorityKeyId = authorityKeyId,
    revision = revision,
    issuedEpochMs = issuedEpochMs,
    expiresEpochMs = expiresEpochMs,
    credentialId = credentialId.copyOf(),
    credentialPublicKeySha256 = credentialPublicKeySha256.copyOf(),
    signatureDer = signatureDer.copyOf(),
  )

  private fun readSnapshot(): AuthenticatedRemoteFlagState? = try {
    if (!flagFile.exists()) {
      null
    } else {
      val value = JSONObject(AtomicFile(flagFile).readFully().toString(Charsets.UTF_8))
      AuthenticatedRemoteFlagState(
        enabled = value.getBoolean(KEY_ENABLED),
        issuer = value.getString(KEY_ISSUER),
        authorityKeyId = value.getString(KEY_AUTHORITY_KEY_ID),
        revision = value.getLong(KEY_REVISION),
        issuedEpochMs = value.getLong(KEY_ISSUED),
        expiresEpochMs = value.getLong(KEY_EXPIRES),
        credentialIdSha256 = value.getString(KEY_CREDENTIAL_HASH).hexToBytes(),
        credentialPublicKeySha256 = value.getString(KEY_PUBLIC_KEY_HASH).hexToBytes(),
        signatureDer = value.getString(KEY_SIGNATURE).hexToBytes(),
      ).takeIf {
        it.credentialIdSha256.size == 32 &&
          it.credentialPublicKeySha256.size == 32 &&
          it.signatureDer.isNotEmpty()
      }
    }
  } catch (_: Exception) {
    null
  }

  private fun persist(snapshot: AuthenticatedRemoteFlagState): Boolean = try {
    val value = JSONObject()
      .put(KEY_ENABLED, snapshot.enabled)
      .put(KEY_ISSUER, snapshot.issuer)
      .put(KEY_AUTHORITY_KEY_ID, snapshot.authorityKeyId)
      .put(KEY_REVISION, snapshot.revision)
      .put(KEY_ISSUED, snapshot.issuedEpochMs)
      .put(KEY_EXPIRES, snapshot.expiresEpochMs)
      .put(KEY_CREDENTIAL_HASH, snapshot.credentialIdSha256.toHex())
      .put(KEY_PUBLIC_KEY_HASH, snapshot.credentialPublicKeySha256.toHex())
      .put(KEY_SIGNATURE, snapshot.signatureDer.toHex())
      .toString()
      .toByteArray(Charsets.UTF_8)
    flagFile.parentFile?.let { parent ->
      if (!parent.exists()) parent.mkdirs()
    }
    val atomic = AtomicFile(flagFile)
    val stream = atomic.startWrite()
    try {
      stream.write(value)
      stream.fd.sync()
      atomic.finishWrite(stream)
      true
    } catch (error: Throwable) {
      atomic.failWrite(stream)
      throw error
    }
  } catch (_: Exception) {
    false
  }

  private fun cleanupUnauthenticatedV1() {
    context.getSharedPreferences(LEGACY_PREFS, Context.MODE_PRIVATE).edit().clear().commit()
    context.getSharedPreferences(LEGACY_PREFS_V2, Context.MODE_PRIVATE).edit().clear().commit()
  }

  private fun <T> withFlagUpdateLock(block: () -> T): T {
    val directory = context.applicationContext.noBackupFilesDir
    if (!directory.exists()) check(directory.mkdirs() || directory.isDirectory) { "flag directory" }
    return RandomAccessFile(File(directory, FLAG_LOCK_FILE), "rw").use { file ->
      file.channel.use { channel ->
        channel.lock().use { block() }
      }
    }
  }

  private val flagFile: File
    get() = File(context.applicationContext.noBackupFilesDir, FLAG_STATE_FILE)

  companion object {
    private const val LEGACY_PREFS = "ble_gatt_worker_flags"
    private const val LEGACY_PREFS_V2 = "ble_gatt_worker_flags_v2"
    private const val FLAG_STATE_FILE = "ble-gatt-authenticated-flag-v3.json"
    private const val FLAG_LOCK_FILE = "ble-gatt-authenticated-flag-v3.lock"
    private const val KEY_ENABLED = "remote_enabled"
    private const val KEY_ISSUER = "remote_issuer"
    private const val KEY_AUTHORITY_KEY_ID = "remote_authority_key_id"
    private const val KEY_REVISION = "remote_revision"
    private const val KEY_ISSUED = "remote_issued_epoch_ms"
    private const val KEY_EXPIRES = "remote_expires_epoch_ms"
    private const val KEY_CREDENTIAL_HASH = "remote_credential_id_sha256"
    private const val KEY_PUBLIC_KEY_HASH = "remote_credential_public_key_sha256"
    private const val KEY_SIGNATURE = "remote_signature_der"
  }
}

enum class DurableSessionState {
  QUEUED,
  RUNNING,
  RETRY_PENDING,
  PROOF_UNCERTAIN,
  SUCCEEDED,
  FAILED,
  DISABLED,
}

data class DurableGattSession(
  val id: String,
  val presenceFingerprint: String,
  val createdEpochMs: Long,
  val updatedEpochMs: Long,
  val attempt: Int,
  val state: DurableSessionState,
  val reasonCode: String? = null,
  val targetReasonCode: Int? = null,
  val targetReasonName: String? = null,
  val transportReason: String? = null,
  val transportStatus: Int? = null,
  val retryAfterMs: Long? = null,
  val scheduledRetryDelayMs: Long? = null,
  val latencyMs: Long? = null,
  val activeAclVersion: Long? = null,
) {
  fun redactedMap(): Map<String, Any?> = mapOf(
    "sessionId" to id,
    "attempt" to attempt,
    "state" to state.name,
    "reasonCode" to reasonCode,
    "targetReasonCode" to targetReasonCode,
    "targetReasonName" to targetReasonName,
    "transportReason" to transportReason,
    "transportStatus" to transportStatus,
    "retryAfterMs" to retryAfterMs,
    "scheduledRetryDelayMs" to scheduledRetryDelayMs,
    "latencyMs" to latencyMs,
    "activeAclVersion" to activeAclVersion,
    "updatedEpochMs" to updatedEpochMs,
  )
}

interface DurableSessionLedger {
  fun findByPresenceFingerprint(fingerprint: String): DurableGattSession?
  fun create(fingerprint: String, nowEpochMs: Long): DurableGattSession
  fun get(id: String): DurableGattSession?
  fun update(session: DurableGattSession)
  fun last(): DurableGattSession?
}

class PresenceCoalescer(
  private val ledger: DurableSessionLedger,
  private val fingerprinter: PresenceFingerprinter,
) {
  fun enqueue(
    deviceAddress: String,
    presenceEventId: String,
    nowEpochMs: Long,
  ): Pair<DurableGattSession, Boolean> {
    val fingerprint = fingerprinter.fingerprint(deviceAddress, presenceEventId)
    val existing = ledger.findByPresenceFingerprint(fingerprint)
    if (existing != null) return existing to true
    return ledger.create(fingerprint, nowEpochMs) to false
  }
}

data class DecodedSessionLedger(
  val sessions: List<DurableGattSession>,
  val containedLegacySensitiveFields: Boolean,
)

object SessionLedgerCodec {
  fun decode(raw: String): DecodedSessionLedger {
    val array = JSONArray(raw)
    var sensitive = false
    val sessions = buildList {
      for (index in 0 until array.length()) {
        val value = array.getJSONObject(index)
        sensitive = sensitive || value.has("device_address") || value.has("credential_id_hex")
        add(fromJson(value))
      }
    }
    return DecodedSessionLedger(sessions, sensitive)
  }

  fun encode(sessions: List<DurableGattSession>): String = JSONArray().apply {
    sessions.forEach { put(toJson(it)) }
  }.toString()

  private fun toJson(session: DurableGattSession): JSONObject = JSONObject()
    .put("id", session.id)
    .put("presence_fingerprint", session.presenceFingerprint)
    .put("created_epoch_ms", session.createdEpochMs)
    .put("updated_epoch_ms", session.updatedEpochMs)
    .put("attempt", session.attempt)
    .put("state", session.state.name)
    .put("reason_code", session.reasonCode)
    .put("target_reason_code", session.targetReasonCode)
    .put("target_reason_name", session.targetReasonName)
    .put("transport_reason", session.transportReason)
    .put("transport_status", session.transportStatus)
    .put("retry_after_ms", session.retryAfterMs)
    .put("scheduled_retry_delay_ms", session.scheduledRetryDelayMs)
    .put("latency_ms", session.latencyMs)
    .put("active_acl_version", session.activeAclVersion)

  private fun fromJson(value: JSONObject): DurableGattSession = DurableGattSession(
    id = value.getString("id"),
    presenceFingerprint = value.getString("presence_fingerprint"),
    createdEpochMs = value.getLong("created_epoch_ms"),
    updatedEpochMs = value.getLong("updated_epoch_ms"),
    attempt = value.getInt("attempt"),
    state = DurableSessionState.valueOf(value.getString("state")),
    reasonCode = value.optionalString("reason_code"),
    targetReasonCode = value.optionalInt("target_reason_code"),
    targetReasonName = value.optionalString("target_reason_name"),
    transportReason = value.optionalString("transport_reason"),
    transportStatus = value.optionalInt("transport_status"),
    retryAfterMs = value.optionalLong("retry_after_ms"),
    scheduledRetryDelayMs = value.optionalLong("scheduled_retry_delay_ms"),
    latencyMs = value.optionalLong("latency_ms"),
    activeAclVersion = value.optionalLong("active_acl_version"),
  )

  private fun JSONObject.optionalString(key: String): String? =
    optString(key).takeIf { has(key) && !isNull(key) && it.isNotEmpty() && it != "null" }

  private fun JSONObject.optionalInt(key: String): Int? = if (!has(key) || isNull(key)) null else getInt(key)
  private fun JSONObject.optionalLong(key: String): Long? = if (!has(key) || isNull(key)) null else getLong(key)
}

class SharedPreferencesSessionLedger(private val context: Context) : DurableSessionLedger {
  @Synchronized
  override fun findByPresenceFingerprint(fingerprint: String): DurableGattSession? =
    readAll().lastOrNull { it.presenceFingerprint == fingerprint }

  @Synchronized
  override fun create(fingerprint: String, nowEpochMs: Long): DurableGattSession {
    val session = DurableGattSession(
      id = UUID.randomUUID().toString(),
      presenceFingerprint = fingerprint,
      createdEpochMs = nowEpochMs,
      updatedEpochMs = nowEpochMs,
      attempt = 0,
      state = DurableSessionState.QUEUED,
    )
    persist((readAll() + session).takeLast(MAX_SESSIONS))
    return session
  }

  @Synchronized
  override fun get(id: String): DurableGattSession? = readAll().firstOrNull { it.id == id }

  @Synchronized
  override fun update(session: DurableGattSession) {
    persist((readAll().filterNot { it.id == session.id } + session).takeLast(MAX_SESSIONS))
  }

  @Synchronized
  override fun last(): DurableGattSession? = readAll().maxByOrNull { it.updatedEpochMs }

  private fun readAll(): List<DurableGattSession> {
    return try {
      val v2 = prefs.getString(KEY_SESSIONS_V2, null)
      if (v2 != null) {
        SessionLedgerCodec.decode(v2).sessions
      } else {
        val legacy = prefs.getString(KEY_SESSIONS_V1, null)
        if (legacy == null) {
          emptyList()
        } else {
          val decoded = SessionLedgerCodec.decode(legacy)
          persist(decoded.sessions)
          check(prefs.edit().remove(KEY_SESSIONS_V1).commit()) { "failed sensitive ledger cleanup" }
          decoded.sessions
        }
      }
    } catch (_: Exception) {
      prefs.edit().remove(KEY_SESSIONS_V1).commit()
      emptyList()
    }
  }

  private fun persist(sessions: List<DurableGattSession>) {
    check(prefs.edit().putString(KEY_SESSIONS_V2, SessionLedgerCodec.encode(sessions)).commit()) {
      "failed to persist GATT session ledger"
    }
  }

  private val prefs
    get() = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

  companion object {
    private const val PREFS = "ble_gatt_worker_sessions"
    private const val KEY_SESSIONS_V1 = "sessions_v1"
    private const val KEY_SESSIONS_V2 = "sessions_v2_redacted"
    private const val MAX_SESSIONS = 50
  }
}
