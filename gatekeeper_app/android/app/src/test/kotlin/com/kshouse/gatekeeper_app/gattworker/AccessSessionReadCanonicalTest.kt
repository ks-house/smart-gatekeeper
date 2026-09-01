package com.kshouse.gatekeeper_app.gattworker

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AccessSessionReadCanonicalTest {
  @Test
  fun clientProofTtlLeavesServerClockSkewHeadroom() {
    assertEquals(20L, AccessSessionReadProofSigner.PROOF_TTL_SECONDS)
  }

  @Test
  fun canonicalVectorBindsCredentialTargetSessionNonceAndExpiry() {
    val credential = "00112233445566778899aabbccddeeff".hexToBytes()
    val targetSession = AccessSessionReadCanonical.targetSessionBytes(
      "10213243-5465-4687-89a9-bacbdcedfe0f",
    )
    val nonce = ByteArray(32) { it.toByte() }

    val canonical = AccessSessionReadCanonical.build(
      credential,
      targetSession,
      nonce,
      0x0102030405060708,
    )

    assertEquals(80, canonical.size)
    assertEquals(
      "53474b4153523031" +
        "00112233445566778899aabbccddeeff" +
        "102132435465468789a9bacbdcedfe0f" +
        "000102030405060708090a0b0c0d0e0f" +
        "101112131415161718191a1b1c1d1e1f" +
        "0102030405060708",
      canonical.toHex(),
    )
  }

  @Test
  fun nonCanonicalTargetSessionUuidIsRejected() {
    var rejected = false
    try {
      AccessSessionReadCanonical.targetSessionBytes(
        "10213243-5465-1687-89a9-bacbdcedfe0f",
      )
    } catch (_: IllegalArgumentException) {
      rejected = true
    }
    assertTrue(rejected)
  }
}
