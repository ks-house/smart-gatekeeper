package com.kshouse.gatekeeper_app.gattworker

import java.io.ByteArrayOutputStream
import java.math.BigInteger
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.MessageDigest
import java.util.UUID

object GattProtocol {
  val SERVICE_UUID: UUID = UUID.fromString("9f4d1000-7d9e-4fb1-9c54-6f4d53474b31")
  val HELLO_UUID: UUID = UUID.fromString("9f4d1001-7d9e-4fb1-9c54-6f4d53474b31")
  val CHALLENGE_UUID: UUID = UUID.fromString("9f4d1002-7d9e-4fb1-9c54-6f4d53474b31")
  val PROOF_UUID: UUID = UUID.fromString("9f4d1003-7d9e-4fb1-9c54-6f4d53474b31")
  val RESULT_UUID: UUID = UUID.fromString("9f4d1004-7d9e-4fb1-9c54-6f4d53474b31")
  val FAST_RX_UUID: UUID = UUID.fromString("9f4d1005-7d9e-4fb1-9c54-6f4d53474b31")
  val FAST_TX_UUID: UUID = UUID.fromString("9f4d1006-7d9e-4fb1-9c54-6f4d53474b31")
  val CCCD_UUID: UUID = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb")

  const val PROTOCOL_VERSION = 1
  const val FAST_PROTOCOL_VERSION = 2
  const val FRAMING_VERSION = 1
  const val MAX_MESSAGE_BYTES = 2048
  const val CLIENT_CAPABILITIES = 3L
  const val ACTION_ARM_FOR_SENSOR = 1
  const val ACTION_OPEN_IMMEDIATELY = 2
  const val CLIENT_HELLO = 0x01
  const val TARGET_HELLO = 0x02
  const val CHALLENGE = 0x10
  const val PROOF = 0x11
  const val RESULT = 0x12
  const val FAST_CHALLENGE = 0x20
  const val FAST_PROOF = 0x21
  const val FAST_RESULT = 0x22
}

enum class GattProtocolMode { LEGACY_V1, FAST_V2 }

internal fun selectGattProtocolMode(
  fastRxPresent: Boolean,
  fastTxPresent: Boolean,
): GattProtocolMode {
  require(fastRxPresent == fastTxPresent) { "partial v2 service is invalid" }
  return if (fastRxPresent) GattProtocolMode.FAST_V2 else GattProtocolMode.LEGACY_V1
}

data class Challenge(
  val canonical: ByteArray,
  val protocolVersion: Int,
  val doorId: ByteArray,
  val sessionId: ByteArray,
  val targetBootId: ByteArray,
  val negotiationHash: ByteArray,
)

data class TargetHello(
  val canonical: ByteArray,
  val selectedProtocol: Int,
  val status: Int,
  val securityFloor: Int,
)

data class TargetResult(
  val protocolVersion: Int,
  val sessionId: ByteArray,
  val reason: Int,
  val retryAfterMs: Long,
  val activeAclVersion: Long,
)

class TargetHelloRejectedException(val status: Int) :
  IllegalArgumentException("target hello rejected with status $status")

object GattCanonicalCodec {
  private val fastNegotiationTranscript = byteArrayOf(
    'S'.code.toByte(), 'G'.code.toByte(), 'K'.code.toByte(), 'F'.code.toByte(),
    'A'.code.toByte(), 'S'.code.toByte(), 'T'.code.toByte(), '2'.code.toByte(),
    0x00, 0x02, 0x01, 0x00, 0x03,
  )

  fun fastNegotiationHash(): ByteArray = sha256(fastNegotiationTranscript)

  fun clientHello(mobileBuild: Long = 0L): ByteArray = ByteBuffer.allocate(16)
    .order(ByteOrder.BIG_ENDIAN)
    .putShort(GattProtocol.PROTOCOL_VERSION.toShort())
    .putShort(GattProtocol.PROTOCOL_VERSION.toShort())
    .put(GattProtocol.FRAMING_VERSION.toByte())
    .put(GattProtocol.FRAMING_VERSION.toByte())
    .putShort(GattProtocol.MAX_MESSAGE_BYTES.toShort())
    .putInt(GattProtocol.CLIENT_CAPABILITIES.toInt())
    .putInt(mobileBuild.toInt())
    .array()

  fun parseTargetHello(bytes: ByteArray): TargetHello {
    require(bytes.size == 20) { "malformed target hello length" }
    val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN)
    val selected = buffer.short.toInt() and 0xffff
    val targetMin = buffer.short.toInt() and 0xffff
    val targetMax = buffer.short.toInt() and 0xffff
    val framing = buffer.get().toInt() and 0xff
    val status = buffer.get().toInt() and 0xff
    val maxMessage = buffer.short.toInt() and 0xffff
    buffer.int // capabilities
    buffer.int // firmware build
    val securityFloor = buffer.short.toInt() and 0xffff
    if (status != 0) throw TargetHelloRejectedException(status)
    require(selected == GattProtocol.PROTOCOL_VERSION) { "unsupported protocol" }
    require(selected in targetMin..targetMax && selected >= securityFloor) { "unsafe protocol selection" }
    require(framing == GattProtocol.FRAMING_VERSION) { "unsupported framing" }
    require(maxMessage in 1..GattProtocol.MAX_MESSAGE_BYTES) { "invalid target message limit" }
    return TargetHello(bytes.copyOf(), selected, status, securityFloor)
  }

  fun parseChallenge(
    bytes: ByteArray,
    expectedNegotiationHash: ByteArray,
    expectedProtocol: Int = GattProtocol.PROTOCOL_VERSION,
  ): Challenge {
    require(bytes.size == 138) { "malformed challenge length" }
    val expectedMagic = if (expectedProtocol == GattProtocol.FAST_PROTOCOL_VERSION) {
      "SGKCHAL2"
    } else {
      "SGKCHAL1"
    }.toByteArray(Charsets.US_ASCII)
    require(bytes.copyOfRange(0, 8).contentEquals(expectedMagic)) { "malformed challenge magic" }
    val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN)
    buffer.position(8)
    val protocol = buffer.short.toInt() and 0xffff
    require(protocol == expectedProtocol) { "unsupported challenge protocol" }
    val door = ByteArray(16).also(buffer::get)
    val session = ByteArray(16).also(buffer::get)
    val nonce = ByteArray(32).also(buffer::get)
    val boot = ByteArray(16).also(buffer::get)
    val expiry = buffer.long
    val aclVersion = buffer.long
    val negotiationHash = ByteArray(32).also(buffer::get)
    require(door.any { it.toInt() != 0 }) { "all-zero door id" }
    require(session.any { it.toInt() != 0 }) { "all-zero session id" }
    require(nonce.any { it.toInt() != 0 }) { "all-zero nonce" }
    require(boot.any { it.toInt() != 0 }) { "all-zero target boot id" }
    require(expiry > 0 && aclVersion > 0) { "invalid challenge deadline or ACL version" }
    require(negotiationHash.contentEquals(expectedNegotiationHash)) { "negotiation hash mismatch" }
    return Challenge(bytes.copyOf(), protocol, door, session, boot, negotiationHash)
  }

  fun proofSigningInput(
    challengeCanonical: ByteArray,
    credentialId: ByteArray,
    action: Int = GattProtocol.ACTION_ARM_FOR_SENSOR,
    clientCapabilities: Long = GattProtocol.CLIENT_CAPABILITIES,
    protocolVersion: Int = GattProtocol.PROTOCOL_VERSION,
  ): ByteArray {
    require(challengeCanonical.size == 138) { "challenge canonical length" }
    require(credentialId.size == 16) { "credential id length" }
    return ByteBuffer.allocate(61)
      .order(ByteOrder.BIG_ENDIAN)
      .put(
        if (protocolVersion == GattProtocol.FAST_PROTOCOL_VERSION) {
          "SGKPRF02"
        } else {
          "SGKPRF01"
        }.toByteArray(Charsets.US_ASCII),
      )
      .put(sha256(challengeCanonical))
      .put(credentialId)
      .put(action.toByte())
      .putInt(clientCapabilities.toInt())
      .array()
  }

  fun proofWire(
    challenge: Challenge,
    credentialId: ByteArray,
    signatureRaw64: ByteArray,
    action: Int = GattProtocol.ACTION_ARM_FOR_SENSOR,
    clientCapabilities: Long = GattProtocol.CLIENT_CAPABILITIES,
  ): ByteArray {
    require(credentialId.size == 16) { "credential id length" }
    require(signatureRaw64.size == 64) { "signature length" }
    return ByteBuffer.allocate(103)
      .order(ByteOrder.BIG_ENDIAN)
      .putShort(challenge.protocolVersion.toShort())
      .put(challenge.sessionId)
      .put(credentialId)
      .put(action.toByte())
      .putInt(clientCapabilities.toInt())
      .put(signatureRaw64)
      .array()
  }

  fun parseResult(
    bytes: ByteArray,
    expectedSessionId: ByteArray,
    expectedProtocol: Int = GattProtocol.PROTOCOL_VERSION,
  ): TargetResult {
    require(bytes.size == 32) { "malformed result length" }
    val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.BIG_ENDIAN)
    val protocol = buffer.short.toInt() and 0xffff
    val session = ByteArray(16).also(buffer::get)
    val reason = buffer.short.toInt() and 0xffff
    val retryAfter = buffer.int.toLong() and 0xffffffffL
    val aclVersion = buffer.long
    require(protocol == expectedProtocol) { "unsupported result protocol" }
    require(session.contentEquals(expectedSessionId)) { "result session mismatch" }
    require(reason in 0..10) { "unknown result reason" }
    require(aclVersion >= 0) { "invalid ACL version" }
    return TargetResult(protocol, session, reason, retryAfter, aclVersion)
  }

  /**
   * Mirrors the Target canonical-event UUID projection. The protocol session
   * bytes are random and are not required to arrive with UUID version/variant
   * bits set, while the Target MQTT event sink normalizes those bits before it
   * renders `session_id`. Keeping the exact same projection is required for an
   * Android session to query its own later access lifecycle.
   */
  fun canonicalSessionUuid(sessionId: ByteArray): String {
    require(sessionId.size == 16) { "session id length" }
    val canonical = sessionId.copyOf()
    canonical[6] = ((canonical[6].toInt() and 0x0f) or 0x40).toByte()
    canonical[8] = ((canonical[8].toInt() and 0x3f) or 0x80).toByte()
    val buffer = ByteBuffer.wrap(canonical).order(ByteOrder.BIG_ENDIAN)
    return UUID(buffer.long, buffer.long).toString()
  }

  fun sha256(bytes: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(bytes)
}

object EcdsaSignatureCodec {
  private val p256Order = BigInteger(
    "FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551",
    16,
  )
  private val halfOrder = p256Order.shiftRight(1)

  fun derToLowSRaw64(der: ByteArray): ByteArray {
    var index = 0
    fun readByte(): Int {
      require(index < der.size) { "truncated DER" }
      return der[index++].toInt() and 0xff
    }
    fun readLength(): Int {
      val first = readByte()
      if (first < 0x80) return first
      val octets = first and 0x7f
      require(octets in 1..2) { "unsupported DER length" }
      var length = 0
      repeat(octets) { length = (length shl 8) or readByte() }
      require(length >= 0x80) { "non-minimal DER length" }
      return length
    }
    require(readByte() == 0x30) { "DER signature sequence" }
    val sequenceLength = readLength()
    require(sequenceLength == der.size - index) { "DER trailing or truncated bytes" }
    fun readInteger(): BigInteger {
      require(readByte() == 0x02) { "DER integer tag" }
      val length = readLength()
      require(length in 1..33 && index + length <= der.size) { "DER integer length" }
      val encoded = der.copyOfRange(index, index + length)
      index += length
      require(encoded[0].toInt() and 0x80 == 0) { "negative DER integer" }
      require(!(encoded.size > 1 && encoded[0] == 0.toByte() && encoded[1].toInt() and 0x80 == 0)) {
        "non-minimal DER integer"
      }
      return BigInteger(1, encoded)
    }
    val r = readInteger()
    var s = readInteger()
    require(index == der.size) { "DER trailing bytes" }
    require(r >= BigInteger.ONE && r < p256Order && s >= BigInteger.ONE && s < p256Order) {
      "ECDSA scalar out of range"
    }
    if (s > halfOrder) s = p256Order.subtract(s)
    return fixed32(r) + fixed32(s)
  }

  private fun fixed32(value: BigInteger): ByteArray {
    val bytes = value.toByteArray().let { if (it.size == 33 && it[0] == 0.toByte()) it.copyOfRange(1, 33) else it }
    require(bytes.size <= 32) { "ECDSA scalar too large" }
    return ByteArray(32 - bytes.size) + bytes
  }
}

data class GattFrame(
  val messageType: Int,
  val messageId: Int,
  val fragmentIndex: Int,
  val fragmentCount: Int,
  val totalLength: Int,
  val payload: ByteArray,
)

object GattFraming {
  fun fragment(messageType: Int, messageId: Int, payload: ByteArray, attMtu: Int): List<ByteArray> {
    require(payload.size in 1..GattProtocol.MAX_MESSAGE_BYTES) { "message length" }
    val capacity = attMtu - 3 - 10
    require(capacity > 0) { "ATT MTU too small" }
    val count = (payload.size + capacity - 1) / capacity
    require(count in 1..255) { "fragment count" }
    return (0 until count).map { index ->
      val start = index * capacity
      val end = minOf(start + capacity, payload.size)
      ByteBuffer.allocate(10 + end - start)
        .order(ByteOrder.BIG_ENDIAN)
        .put('S'.code.toByte())
        .put('G'.code.toByte())
        .put(GattProtocol.FRAMING_VERSION.toByte())
        .put(messageType.toByte())
        .putShort(messageId.toShort())
        .put(index.toByte())
        .put(count.toByte())
        .putShort(payload.size.toShort())
        .put(payload, start, end - start)
        .array()
    }
  }

  fun parse(frame: ByteArray): GattFrame {
    require(frame.size >= 11) { "frame too short" }
    val buffer = ByteBuffer.wrap(frame).order(ByteOrder.BIG_ENDIAN)
    require(buffer.get() == 'S'.code.toByte() && buffer.get() == 'G'.code.toByte()) { "frame magic" }
    require(buffer.get().toInt() and 0xff == GattProtocol.FRAMING_VERSION) { "frame version" }
    val type = buffer.get().toInt() and 0xff
    val id = buffer.short.toInt() and 0xffff
    val index = buffer.get().toInt() and 0xff
    val count = buffer.get().toInt() and 0xff
    val total = buffer.short.toInt() and 0xffff
    require(count in 1..255 && index < count && total in 1..GattProtocol.MAX_MESSAGE_BYTES) { "frame bounds" }
    return GattFrame(type, id, index, count, total, ByteArray(buffer.remaining()).also(buffer::get))
  }
}

class GattReassembler {
  private var first: GattFrame? = null
  private val output = ByteArrayOutputStream()

  fun accept(bytes: ByteArray): Pair<Int, ByteArray>? {
    val frame = GattFraming.parse(bytes)
    val expected = first
    if (expected == null) {
      require(frame.fragmentIndex == 0) { "first fragment index" }
      first = frame
    } else {
      require(frame.messageType == expected.messageType && frame.messageId == expected.messageId) { "mixed message" }
      require(frame.fragmentCount == expected.fragmentCount && frame.totalLength == expected.totalLength) { "changed frame header" }
      require(frame.fragmentIndex == outputFragmentCount()) { "non-contiguous fragment" }
    }
    output.write(frame.payload)
    require(output.size() <= frame.totalLength) { "fragment overflow" }
    if (frame.fragmentIndex + 1 != frame.fragmentCount) return null
    val result = output.toByteArray()
    require(result.size == frame.totalLength) { "fragment length mismatch" }
    val type = frame.messageType
    first = null
    output.reset()
    return type to result
  }

  private fun outputFragmentCount(): Int {
    val expected = first ?: return 0
    val capacity = expected.payload.size
    return if (capacity == 0) 0 else output.size() / capacity
  }
}

fun ByteArray.toHex(): String = joinToString("") { "%02x".format(it.toInt() and 0xff) }

fun String.hexToBytes(): ByteArray {
  require(length % 2 == 0) { "hex length" }
  return chunked(2).map { it.toInt(16).toByte() }.toByteArray()
}
