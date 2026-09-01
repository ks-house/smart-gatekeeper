package com.kshouse.gatekeeper_app.gattworker

import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.math.BigInteger

class GattProtocolVectorTest {
  private val vector by lazy { loadVector() }

  @Test
  fun exactCanonicalProofMatchesSharedVector() {
    val hello = vector.getJSONObject("hello")
    val challenge = vector.getJSONObject("challenge")
    val proof = vector.getJSONObject("proof")
    val client = GattCanonicalCodec.clientHello(100)
    val target = hello.getJSONObject("expected").getString("target_hex").hexToBytes()
    val negotiationHash = GattCanonicalCodec.sha256(client + target)
    val parsed = GattCanonicalCodec.parseChallenge(
      challenge.getJSONObject("expected").getString("canonical_hex").hexToBytes(),
      negotiationHash,
    )
    val input = GattCanonicalCodec.proofSigningInput(
      parsed.canonical,
      proof.getJSONObject("fields").getString("credential_id").hexToBytes(),
    )

    assertEquals(hello.getJSONObject("expected").getString("client_hex"), client.toHex())
    assertEquals(challenge.getJSONObject("expected").getString("sha256"), GattCanonicalCodec.sha256(parsed.canonical).toHex())
    assertEquals(proof.getJSONObject("expected").getString("input_hex"), input.toHex())
    assertEquals(proof.getJSONObject("expected").getString("sha256"), GattCanonicalCodec.sha256(input).toHex())
  }

  @Test
  fun defaultMtuFramingMatchesEverySharedFrame() {
    val framing = vector.getJSONObject("framing")
    val challengeHex = vector.getJSONObject("challenge").getJSONObject("expected").getString("canonical_hex")
    val actual = GattFraming.fragment(
      framing.getInt("message_type"),
      framing.getInt("message_id"),
      challengeHex.hexToBytes(),
      framing.getInt("att_mtu"),
    )
    val expected = framing.getJSONObject("expected").getJSONArray("frames_hex")
    assertEquals(expected.length(), actual.size)
    actual.forEachIndexed { index, bytes -> assertEquals(expected.getString(index), bytes.toHex()) }
  }

  @Test
  fun strictDerConversionProducesLowSRaw64AndRejectsTrailingBytes() {
    val raw = vector.getJSONObject("proof").getJSONObject("expected")
      .getString("signature_raw64").hexToBytes()
    val der = rawToDer(raw)
    assertArrayEquals(raw, EcdsaSignatureCodec.derToLowSRaw64(der))
    assertFails { EcdsaSignatureCodec.derToLowSRaw64(der + byteArrayOf(0x00)) }
  }

  @Test
  fun resultParserRejectsMalformedOrCrossSessionResult() {
    val expectedSession = "102132435465768798a9bacbdcedfe0f".hexToBytes()
    assertFails { GattCanonicalCodec.parseResult(ByteArray(31), expectedSession) }
    val wrong = successResult(ByteArray(16) { 1 })
    assertFails { GattCanonicalCodec.parseResult(wrong, expectedSession) }
  }

  @Test
  fun targetSessionBytesUseTheSameCanonicalUuidProjectionAsTargetEvents() {
    val raw = "102132435465768709a9bacbdcedfe0f".hexToBytes()

    assertEquals(
      "10213243-5465-4687-89a9-bacbdcedfe0f",
      GattCanonicalCodec.canonicalSessionUuid(raw),
    )
    assertEquals("102132435465768709a9bacbdcedfe0f", raw.toHex())
    assertFails { GattCanonicalCodec.canonicalSessionUuid(ByteArray(15)) }
  }

  private fun rawToDer(raw: ByteArray): ByteArray {
    fun integer(bytes: ByteArray): ByteArray {
      val strippedBytes = bytes.dropWhile { it == 0.toByte() }.toByteArray()
      val stripped = if (strippedBytes.isEmpty()) byteArrayOf(0) else strippedBytes
      val positive = if (stripped[0].toInt() and 0x80 != 0) byteArrayOf(0) + stripped else stripped
      return byteArrayOf(0x02, positive.size.toByte()) + positive
    }
    val content = integer(raw.copyOfRange(0, 32)) + integer(raw.copyOfRange(32, 64))
    return byteArrayOf(0x30, content.size.toByte()) + content
  }

  private fun assertFails(block: () -> Unit) {
    var failed = false
    try {
      block()
    } catch (_: IllegalArgumentException) {
      failed = true
    }
    assertTrue(failed)
  }

  private fun loadVector(): JSONObject {
    val candidates = listOf(
      File("/repo-protocol/test_vectors/v1.json"),
      File("../../../protocol/test_vectors/v1.json"),
      File("../../../../protocol/test_vectors/v1.json"),
      File("protocol/test_vectors/v1.json"),
    )
    val file = candidates.firstOrNull(File::isFile)
      ?: error("protocol/test_vectors/v1.json not found from ${File(".").absolutePath}")
    return JSONObject(file.readText(Charsets.UTF_8))
  }
}

internal fun successResult(
  sessionId: ByteArray,
  reason: Int = 0,
  retryAfterMs: Long = if (reason == 9) 1000 else 0,
): ByteArray = java.nio.ByteBuffer
  .allocate(32)
  .order(java.nio.ByteOrder.BIG_ENDIAN)
  .putShort(1.toShort())
  .put(sessionId)
  .putShort(reason.toShort())
  .putInt(retryAfterMs.toInt())
  .putLong(42)
  .array()
