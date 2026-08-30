package com.kshouse.gatekeeper_app.gattworker

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.security.KeyStore
import java.security.MessageDigest
import java.security.SecureRandom
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.Mac
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

data class LocatorSecret(
  val deviceAddress: String,
  val credentialId: ByteArray,
) {
  init {
    require(deviceAddress.matches(Regex("^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$"))) { "device address" }
    require(credentialId.size == 16) { "credential id length" }
  }
}

/**
 * The latest Target locator is a recovery capability, not a user supplied address.
 * It is written only after the OS accepted the immutable Target advertisement filter,
 * encrypted in no-backup storage, and revalidated against the current credential and
 * Bluetooth state before a manual retry is scheduled.
 */
data class CurrentTargetLocator(
  val deviceAddress: String,
  val identityTag: String,
  val lastSeenEpochMs: Long,
)

class AuthenticatedTargetLocatorStore(private val context: Context) {
  private val store = NoBackupAeadStore(context.applicationContext)

  fun record(deviceAddress: String, lastSeenEpochMs: Long = System.currentTimeMillis()) {
    require(deviceAddress.matches(Regex("^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$"))) { "device address" }
    val normalized = deviceAddress.uppercase()
    val identityTag = AndroidKeystorePresenceFingerprinter(context).fingerprint(normalized, "target-locator-v1")
    val plaintext = ByteArrayOutputStream().use { output ->
      DataOutputStream(output).use { data ->
        data.writeByte(1)
        data.writeUTF(normalized)
        data.writeUTF(identityTag)
        data.writeLong(lastSeenEpochMs)
      }
      output.toByteArray()
    }
    store.write(NAME, plaintext)
    plaintext.fill(0)
  }

  fun resolve(maxAgeMs: Long = MAX_AGE_MS): CurrentTargetLocator? {
    val plaintext = store.read(NAME) ?: return null
    return try {
      DataInputStream(ByteArrayInputStream(plaintext)).use { data ->
        require(data.readUnsignedByte() == 1) { "target locator schema" }
        val address = data.readUTF()
        val identity = data.readUTF()
        val seen = data.readLong()
        require(data.read() == -1) { "target locator trailing bytes" }
        val expected = AndroidKeystorePresenceFingerprinter(context).fingerprint(address, "target-locator-v1")
        require(identity == expected) { "target locator identity" }
        require(System.currentTimeMillis() - seen <= maxAgeMs) { "target locator stale" }
        require(BleCredentialConfigStore(context).credentialId() != null) { "credential unavailable" }
        val manager = context.getSystemService(android.bluetooth.BluetoothManager::class.java)
        require(manager?.adapter?.isEnabled == true) { "bluetooth disabled" }
        CurrentTargetLocator(address, identity, seen)
      }
    } catch (_: Exception) {
      store.delete(NAME)
      null
    } finally {
      plaintext.fill(0)
    }
  }

  fun clear(): Boolean = try {
    store.delete(NAME)
    true
  } catch (_: Exception) {
    false
  }

  companion object {
    private const val NAME = "current-target-locator-v1"
    private const val MAX_AGE_MS = 24L * 60L * 60L * 1000L
  }
}

interface LocatorVault {
  fun store(sessionId: String, secret: LocatorSecret)
  fun load(sessionId: String): LocatorSecret?
  fun delete(sessionId: String)
  fun cleanupExcept(activeSessionIds: Set<String>)
}

class AndroidEncryptedLocatorVault(context: Context) : LocatorVault {
  private val store = NoBackupAeadStore(context.applicationContext)

  override fun store(sessionId: String, secret: LocatorSecret) {
    requireSessionId(sessionId)
    val plaintext = ByteArrayOutputStream().use { output ->
      DataOutputStream(output).use { data ->
        data.writeByte(1)
        data.writeUTF(secret.deviceAddress.uppercase())
        data.write(secret.credentialId)
      }
      output.toByteArray()
    }
    store.write(locatorName(sessionId), plaintext)
    plaintext.fill(0)
  }

  override fun load(sessionId: String): LocatorSecret? {
    requireSessionId(sessionId)
    val plaintext = store.read(locatorName(sessionId)) ?: return null
    return try {
      DataInputStream(ByteArrayInputStream(plaintext)).use { data ->
        require(data.readUnsignedByte() == 1) { "locator schema" }
        val address = data.readUTF()
        val credential = ByteArray(16).also(data::readFully)
        require(data.read() == -1) { "locator trailing bytes" }
        LocatorSecret(address, credential)
      }
    } catch (_: Exception) {
      delete(sessionId)
      null
    } finally {
      plaintext.fill(0)
    }
  }

  override fun delete(sessionId: String) {
    requireSessionId(sessionId)
    store.delete(locatorName(sessionId))
  }

  override fun cleanupExcept(activeSessionIds: Set<String>) {
    store.names("locator-").forEach { name ->
      val sessionId = name.removePrefix("locator-")
      if (sessionId !in activeSessionIds) store.delete(name)
    }
  }

  fun clearAll(): Boolean = try {
    store.names("locator-").forEach(store::delete)
    true
  } catch (_: Exception) {
    false
  }

  private fun requireSessionId(sessionId: String) {
    require(sessionId.matches(Regex("^[0-9a-fA-F-]{36}$"))) { "session id" }
  }

  private fun locatorName(sessionId: String) = "locator-$sessionId"
}

class BleCredentialConfigStore(private val context: Context) {
  private val store = NoBackupAeadStore(context.applicationContext)

  fun credentialId(): ByteArray? {
    store.read(CREDENTIAL_NAME)?.let { value ->
      if (value.size == 16) return value
      value.fill(0)
      store.delete(CREDENTIAL_NAME)
    }
    val legacyPrefs = context.getSharedPreferences(LEGACY_PREFS, Context.MODE_PRIVATE)
    val legacy = legacyPrefs.getString(LEGACY_KEY, null)
      ?.takeIf { it.matches(Regex("^[0-9a-f]{32}$")) }
      ?.hexToBytes()
      ?: return null
    store.write(CREDENTIAL_NAME, legacy)
    check(legacyPrefs.edit().remove(LEGACY_KEY).commit()) { "failed credential migration cleanup" }
    return legacy
  }

  /** Native enrollment seam; private key material is never accepted by this API. */
  fun applyCredentialId(credentialId: ByteArray): Boolean = try {
    require(credentialId.size == 16) { "credential id length" }
    store.write(CREDENTIAL_NAME, credentialId)
    context.getSharedPreferences(LEGACY_PREFS, Context.MODE_PRIVATE).edit().remove(LEGACY_KEY).commit()
  } catch (_: Exception) {
    false
  }

  fun clear(): Boolean = try {
    store.delete(CREDENTIAL_NAME)
    context.getSharedPreferences(LEGACY_PREFS, Context.MODE_PRIVATE)
      .edit().remove(LEGACY_KEY).commit()
  } catch (_: Exception) {
    false
  }

  private companion object {
    const val CREDENTIAL_NAME = "credential-v1"
    const val LEGACY_PREFS = "ble_gatt_worker_credential"
    const val LEGACY_KEY = "credential_id_hex"
  }
}

data class LocalGattConsentStatus(
  val present: Boolean,
  val valid: Boolean,
  val enabled: Boolean,
  val credentialProvisioned: Boolean,
  val reason: String,
)

data class LocalGattConsentMutation(
  val accepted: Boolean,
  val reason: String,
)

data class LocalGattEnrollmentMaterial(
  val accepted: Boolean,
  val reason: String,
  val credentialIdHex: String? = null,
  val publicKeySec1Hex: String? = null,
)

/**
 * APK-authorized manual-local consent stored under AndroidKeyStore AES-GCM.
 *
 * The record contains only hashes of the device credential and public key. The
 * private P-256 key remains non-exportable, and an existing credential whose
 * key disappeared is never silently replaced. A future authenticated remote
 * rollout snapshot still has precedence over this local bootstrap.
 */
class LocalGattConsentStore(private val context: Context) {
  private val store = NoBackupAeadStore(context.applicationContext)
  private val credentialStore = BleCredentialConfigStore(context.applicationContext)
  private val signer = AndroidKeystoreCredentialSigner()

  fun status(): LocalGattConsentStatus {
    val credentialId = credentialStore.credentialId()
      ?: return LocalGattConsentStatus(false, false, false, false, "credential_absent")
    var publicKey: ByteArray? = null
    var plaintext: ByteArray? = null
    return try {
      publicKey = signer.publicKeySec1(credentialId)
      val currentPublicKey = publicKey
        ?: throw CredentialKeyUnavailableException()
      plaintext = store.read(CONSENT_NAME)
        ?: return LocalGattConsentStatus(false, false, false, true, "consent_absent")
      DataInputStream(ByteArrayInputStream(plaintext)).use { data ->
        require(data.readUnsignedByte() == SCHEMA_VERSION) { "local consent schema" }
        val enabledByte = data.readUnsignedByte()
        require(enabledByte in 0..1) { "local consent enabled" }
        val credentialHash = ByteArray(32).also(data::readFully)
        val publicKeyHash = ByteArray(32).also(data::readFully)
        data.readLong() // Durable diagnostic timestamp; not an authorization clock.
        require(data.read() == -1) { "local consent trailing bytes" }
        val credentialMatches = MessageDigest.isEqual(
          credentialHash,
          GattCanonicalCodec.sha256(credentialId),
        )
        val publicKeyMatches = MessageDigest.isEqual(
          publicKeyHash,
          GattCanonicalCodec.sha256(currentPublicKey),
        )
        credentialHash.fill(0)
        publicKeyHash.fill(0)
        if (!credentialMatches || !publicKeyMatches) {
          LocalGattConsentStatus(true, false, false, true, "credential_binding_invalid")
        } else {
          LocalGattConsentStatus(
            present = true,
            valid = true,
            enabled = enabledByte == 1,
            credentialProvisioned = true,
            reason = if (enabledByte == 1) "local_keystore_authenticated" else "local_user_disabled",
          )
        }
      }
    } catch (_: CredentialKeyUnavailableException) {
      LocalGattConsentStatus(true, false, false, true, "credential_key_missing")
    } catch (_: Exception) {
      LocalGattConsentStatus(true, false, false, true, "local_consent_invalid")
    } finally {
      credentialId.fill(0)
      publicKey?.fill(0)
      plaintext?.fill(0)
    }
  }

  fun setEnabled(enabled: Boolean): LocalGattConsentMutation {
    var credentialId = credentialStore.credentialId()
    var generatedCredential = false
    var publicKey: ByteArray? = null
    return try {
      if (credentialId == null) {
        if (!enabled) {
          store.delete(CONSENT_NAME)
          return LocalGattConsentMutation(true, "local_user_disabled")
        }
        credentialId = generateCredentialId()
        generatedCredential = true
        publicKey = signer.createCredentialKey(credentialId)
        if (!credentialStore.applyCredentialId(credentialId)) {
          return LocalGattConsentMutation(false, "credential_store_unavailable")
        }
      } else {
        // Never recreate a missing key for an existing credential identity.
        publicKey = signer.publicKeySec1(credentialId)
      }
      val currentCredentialId = credentialId
        ?: throw CredentialKeyUnavailableException()
      val currentPublicKey = publicKey
        ?: throw CredentialKeyUnavailableException()

      val encoded = ByteArrayOutputStream().use { output ->
        DataOutputStream(output).use { data ->
          data.writeByte(SCHEMA_VERSION)
          data.writeByte(if (enabled) 1 else 0)
          data.write(GattCanonicalCodec.sha256(currentCredentialId))
          data.write(GattCanonicalCodec.sha256(currentPublicKey))
          data.writeLong(System.currentTimeMillis())
        }
        output.toByteArray()
      }
      try {
        store.write(CONSENT_NAME, encoded)
      } finally {
        encoded.fill(0)
      }
      LocalGattConsentMutation(
        true,
        if (enabled) {
          if (generatedCredential) "local_bootstrap_created" else "local_keystore_authenticated"
        } else {
          "local_user_disabled"
        },
      )
    } catch (_: CredentialKeyUnavailableException) {
      LocalGattConsentMutation(false, "credential_key_missing")
    } catch (_: Exception) {
      LocalGattConsentMutation(false, "local_consent_store_unavailable")
    } finally {
      credentialId?.fill(0)
      publicKey?.fill(0)
    }
  }

  /**
   * Creates or loads the one public enrollment identity for this app install.
   * Only public SEC1 material leaves this native boundary; the private key
   * remains non-exportable in AndroidKeyStore.
   */
  fun prepareEnrollmentMaterial(): LocalGattEnrollmentMaterial {
    var credentialId = credentialStore.credentialId()
    var publicKey: ByteArray? = null
    return try {
      if (credentialId == null) {
        credentialId = generateCredentialId()
        publicKey = signer.createCredentialKey(credentialId)
        if (!credentialStore.applyCredentialId(credentialId)) {
          return LocalGattEnrollmentMaterial(false, "credential_store_unavailable")
        }
      } else {
        publicKey = signer.publicKeySec1(credentialId)
      }
      val currentCredentialId = credentialId
        ?: throw CredentialKeyUnavailableException()
      val currentPublicKey = publicKey
        ?: throw CredentialKeyUnavailableException()
      LocalGattEnrollmentMaterial(
        accepted = true,
        reason = "enrollment_material_ready",
        credentialIdHex = currentCredentialId.toHex(),
        publicKeySec1Hex = currentPublicKey.toHex(),
      )
    } catch (_: CredentialKeyUnavailableException) {
      LocalGattEnrollmentMaterial(false, "credential_key_missing")
    } catch (_: Exception) {
      LocalGattEnrollmentMaterial(false, "enrollment_material_unavailable")
    } finally {
      credentialId?.fill(0)
      publicKey?.fill(0)
    }
  }

  fun clear(): Boolean = try {
    store.delete(CONSENT_NAME)
    true
  } catch (_: Exception) {
    false
  }

  private fun generateCredentialId(): ByteArray {
    val random = SecureRandom()
    repeat(4) {
      val candidate = ByteArray(16).also(random::nextBytes)
      if (candidate.any { value -> value.toInt() != 0 }) return candidate
      candidate.fill(0)
    }
    throw IllegalStateException("credential CSPRNG unavailable")
  }

  private companion object {
    const val CONSENT_NAME = "local-gatt-consent-v1"
    const val SCHEMA_VERSION = 1
  }
}

fun interface PresenceFingerprinter {
  fun fingerprint(deviceAddress: String, presenceEventId: String): String
}

class AndroidKeystorePresenceFingerprinter(private val context: Context) : PresenceFingerprinter {
  override fun fingerprint(deviceAddress: String, presenceEventId: String): String {
    cleanupLegacySecret()
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(getOrCreateHmacKey())
    return mac.doFinal(
      "i4-presence-v2|${deviceAddress.uppercase()}|$presenceEventId".toByteArray(Charsets.UTF_8),
    ).toHex()
  }

  private fun getOrCreateHmacKey(): SecretKey {
    val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
    (keyStore.getKey(HMAC_ALIAS, null) as? SecretKey)?.let { return it }
    return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_HMAC_SHA256, ANDROID_KEYSTORE).apply {
      init(
        KeyGenParameterSpec.Builder(
          HMAC_ALIAS,
          KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
        ).setDigests(KeyProperties.DIGEST_SHA256).build(),
      )
    }.generateKey()
  }

  private fun cleanupLegacySecret() {
    context.applicationContext.getSharedPreferences(LEGACY_INTERNAL_PREFS, Context.MODE_PRIVATE)
      .edit()
      .remove(LEGACY_FINGERPRINT_KEY)
      .commit()
  }

  companion object {
    private const val ANDROID_KEYSTORE = "AndroidKeyStore"
    private const val HMAC_ALIAS = "sgk.presence.hmac.v1"
    private const val LEGACY_INTERNAL_PREFS = "ble_gatt_worker_internal"
    private const val LEGACY_FINGERPRINT_KEY = "fingerprint_key_hex"
  }
}

class DeterministicPresenceFingerprinter(key: ByteArray) : PresenceFingerprinter {
  private val keyCopy = key.copyOf()

  override fun fingerprint(deviceAddress: String, presenceEventId: String): String {
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(keyCopy, "HmacSHA256"))
    return mac.doFinal(
      "i4-presence-v2|${deviceAddress.uppercase()}|$presenceEventId".toByteArray(Charsets.UTF_8),
    ).toHex()
  }
}

private class NoBackupAeadStore(context: Context) {
  private val directory = File(context.noBackupFilesDir, "ble-gatt-secure-v1")
  private val aead = AndroidKeystoreAead()

  fun write(name: String, plaintext: ByteArray) {
    requireName(name)
    if (!directory.exists()) check(directory.mkdirs() || directory.isDirectory) { "secure directory" }
    val encoded = aead.encrypt(name.toByteArray(Charsets.UTF_8), plaintext)
    val atomic = AtomicFile(File(directory, name))
    val stream = atomic.startWrite()
    try {
      stream.write(encoded)
      stream.fd.sync()
      atomic.finishWrite(stream)
    } catch (error: Throwable) {
      atomic.failWrite(stream)
      throw error
    } finally {
      encoded.fill(0)
    }
  }

  fun read(name: String): ByteArray? {
    requireName(name)
    val file = File(directory, name)
    if (!file.exists()) return null
    return try {
      aead.decrypt(name.toByteArray(Charsets.UTF_8), AtomicFile(file).readFully())
    } catch (_: Exception) {
      file.delete()
      null
    }
  }

  fun delete(name: String) {
    requireName(name)
    AtomicFile(File(directory, name)).delete()
  }

  fun names(prefix: String): List<String> = directory.list()?.filter { it.startsWith(prefix) }.orEmpty()

  private fun requireName(name: String) {
    require(name.matches(Regex("^[a-z0-9-]{1,64}$"))) { "secure record name" }
  }
}

private class AndroidKeystoreAead {
  fun encrypt(aad: ByteArray, plaintext: ByteArray): ByteArray {
    val cipher = Cipher.getInstance(TRANSFORMATION).apply {
      init(Cipher.ENCRYPT_MODE, getOrCreateKey())
      updateAAD(aad)
    }
    val ciphertext = cipher.doFinal(plaintext)
    return ByteArrayOutputStream().use { output ->
      DataOutputStream(output).use { data ->
        data.writeByte(1)
        data.writeByte(cipher.iv.size)
        data.write(cipher.iv)
        data.writeInt(ciphertext.size)
        data.write(ciphertext)
      }
      output.toByteArray()
    }.also { ciphertext.fill(0) }
  }

  fun decrypt(aad: ByteArray, encoded: ByteArray): ByteArray =
    DataInputStream(ByteArrayInputStream(encoded)).use { data ->
      require(data.readUnsignedByte() == 1) { "secure record schema" }
      val ivSize = data.readUnsignedByte()
      require(ivSize == 12) { "GCM IV length" }
      val iv = ByteArray(ivSize).also(data::readFully)
      val ciphertextSize = data.readInt()
      require(ciphertextSize in 17..4096) { "ciphertext length" }
      val ciphertext = ByteArray(ciphertextSize).also(data::readFully)
      require(data.read() == -1) { "secure record trailing bytes" }
      Cipher.getInstance(TRANSFORMATION).run {
        init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(128, iv))
        updateAAD(aad)
        doFinal(ciphertext)
      }.also { ciphertext.fill(0) }
    }

  private fun getOrCreateKey(): SecretKey {
    val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
    (keyStore.getKey(AES_ALIAS, null) as? SecretKey)?.let { return it }
    return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE).apply {
      init(
        KeyGenParameterSpec.Builder(
          AES_ALIAS,
          KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
          .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
          .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
          .setRandomizedEncryptionRequired(true)
          .build(),
      )
    }.generateKey()
  }

  private companion object {
    const val ANDROID_KEYSTORE = "AndroidKeyStore"
    const val AES_ALIAS = "sgk.locator.aesgcm.v1"
    const val TRANSFORMATION = "AES/GCM/NoPadding"
  }
}
