package com.kshouse.gatekeeper_app.gattworker

import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GattSessionEngineTest {
  private val clientHello = GattCanonicalCodec.clientHello(100)
  private val targetHello = "0001000100010100080000000003000000c80001".hexToBytes()
  private val negotiationHash = GattCanonicalCodec.sha256(clientHello + targetHello)
  private val challenge = (
    "53474b4348414c31000100112233445566778899aabbccddeeff" +
      "102132435465768798a9bacbdcedfe0f" +
      "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f" +
      "ffeeddccbbaa99887766554433221100" +
      "00000000075bcd15000000000000002a" +
      negotiationHash.toHex()
    ).hexToBytes()
  private val credential = "aabbccddeeff00112233445566778899".hexToBytes()
  private val fixtureSignature = (
    "3894dfd39c70ee301d17346632461ac66f168c29fbada9bcaa18b9e408cf35dc" +
      "22ed9694caebf65438228b0bfa4d456a6861c59f917ce3346090ec5f17ecfde8"
    ).hexToBytes()

  @Test
  fun hardwarelessSessionDoesChallengeSignProofAndResultWithoutNetwork() = runBlocking {
    val transport = FakeTransport(targetHello, challenge, successResult(challenge.copyOfRange(26, 42)))
    val signer = DeterministicFakeCredentialSigner(fixtureSignature)
    var now = 100L
    val result = GattSessionEngine(
      transport,
      signer,
      timeoutMs = 1000,
      clock = MonotonicClock { now.also { now += 25 } },
      mobileBuild = 100,
    ).run("00:11:22:33:44:55", credential)

    assertTrue(result is SessionOutcome.Success)
    assertEquals(false, BleGattWorkScheduler.HAS_NETWORK_CONSTRAINT)
    assertArrayEquals(
      GattCanonicalCodec.proofSigningInput(challenge, credential),
      signer.lastCanonical,
    )
    assertEquals(103, transport.proof?.size)
    assertFalse((transport.proof ?: byteArrayOf()).toHex().contains("00:11:22"))
    assertTrue(transport.closed)
  }

  @Test
  fun manualOpenSignsAndWritesExplicitImmediateAction() = runBlocking {
    val transport = FakeTransport(
      targetHello,
      challenge,
      successResult(challenge.copyOfRange(26, 42)),
    )
    val signer = DeterministicFakeCredentialSigner(fixtureSignature)
    val result = GattSessionEngine(
      transport,
      signer,
      timeoutMs = 1000,
      clock = MonotonicClock { 100 },
      mobileBuild = 100,
    ).run(
      "00:11:22:33:44:55",
      credential,
      GattProtocol.ACTION_OPEN_IMMEDIATELY,
    )

    assertTrue(result is SessionOutcome.Success)
    assertEquals(GattProtocol.ACTION_OPEN_IMMEDIATELY, signer.lastCanonical?.get(56)?.toInt())
    assertEquals(GattProtocol.ACTION_OPEN_IMMEDIATELY, transport.proof?.get(34)?.toInt())
  }

  @Test
  fun malformedResultFailsClosedWithSchemaReason() = runBlocking {
    val transport = FakeTransport(targetHello, challenge, byteArrayOf(1, 2, 3))
    val result = GattSessionEngine(
      transport,
      DeterministicFakeCredentialSigner(fixtureSignature),
      timeoutMs = 1000,
      clock = MonotonicClock { 100 },
      mobileBuild = 100,
    ).run("00:11:22:33:44:55", credential)
    assertEquals(AccessReasonCode.MALFORMED_PROOF, (result as SessionOutcome.Failure).reason)
  }

  @Test
  fun boundedTimeoutClosesTransportAndIsRetryable() = runBlocking {
    val transport = FakeTransport(targetHello, challenge, successResult(challenge.copyOfRange(26, 42))).apply {
      blockConnect = true
    }
    val result = GattSessionEngine(
      transport,
      DeterministicFakeCredentialSigner(fixtureSignature),
      timeoutMs = 25,
      clock = MonotonicClock { 100 },
      mobileBuild = 100,
    ).run("00:11:22:33:44:55", credential)
    val failure = result as SessionOutcome.Failure
    assertEquals(AccessReasonCode.GATT_TIMEOUT, failure.reason)
    assertTrue(failure.reason.retryable)
    assertTrue(transport.closed)
  }

  @Test
  fun structuredWriteDisconnectIsNeverMisclassifiedAsOuterTimeout() = runBlocking {
    val transport = FakeTransport(targetHello, challenge, successResult(challenge.copyOfRange(26, 42))).apply {
      negotiateFailure = GattTransportException(TransportFailureCode.DISCONNECTED, 19)
    }
    val result = GattSessionEngine(
      transport,
      DeterministicFakeCredentialSigner(fixtureSignature),
      timeoutMs = 1000,
      clock = MonotonicClock { 100 },
      mobileBuild = 100,
    ).run("00:11:22:33:44:55", credential) as SessionOutcome.Failure

    assertEquals(AccessReasonCode.GATT_DISCONNECTED, result.reason)
    assertEquals(TransportFailureCode.DISCONNECTED, result.transportFailure)
    assertEquals(19, result.transportStatus)
    assertTrue(transport.closed)
  }

  @Test
  fun targetBusyUsesBoundedRetryPolicy() = runBlocking {
    val resultBytes = successResult(challenge.copyOfRange(26, 42), reason = 9, retryAfterMs = 9000)
    val result = GattSessionEngine(
      FakeTransport(targetHello, challenge, resultBytes),
      DeterministicFakeCredentialSigner(fixtureSignature),
      timeoutMs = 1000,
      clock = MonotonicClock { 100 },
      mobileBuild = 100,
    ).run("00:11:22:33:44:55", credential) as SessionOutcome.Failure
    assertEquals(AccessReasonCode.TARGET_BUSY, result.reason)
    assertEquals(9, result.targetReason?.wireCode)
    assertEquals("RATE_LIMITED", result.targetReason?.wireName)
    assertEquals(9000, result.retryAfterMs)
    assertTrue(RetryPolicy.shouldRetry(1, result))
    assertFalse(RetryPolicy.shouldRetry(3, result))
    assertEquals(9000, RetryPolicy.boundedDelayMs(3, result.retryAfterMs))
    assertEquals(
      RetryPolicy.MAX_TARGET_RETRY_AFTER_MS,
      RetryPolicy.boundedDelayMs(1, RetryPolicy.MAX_TARGET_RETRY_AFTER_MS + 1),
    )
  }

  @Test
  fun busyTargetHelloIsRetryableAndNotMisreportedAsProtocolMismatch() = runBlocking {
    val busyTargetHello = targetHello.copyOf().also { it[7] = 2 }
    val result = GattSessionEngine(
      FakeTransport(busyTargetHello, challenge, successResult(challenge.copyOfRange(26, 42))),
      DeterministicFakeCredentialSigner(fixtureSignature),
      timeoutMs = 1000,
      clock = MonotonicClock { 100 },
      mobileBuild = 100,
    ).run("00:11:22:33:44:55", credential) as SessionOutcome.Failure

    assertEquals(AccessReasonCode.TARGET_BUSY, result.reason)
    assertTrue(result.retryable)
    assertFalse(result.proofMayHaveExecuted)
  }

  @Test
  fun everyFrozenTargetReasonRetainsExactWireCodeAndName() = runBlocking {
    for (targetReason in TargetResultReason.entries) {
      val result = GattSessionEngine(
        FakeTransport(
          targetHello,
          challenge,
          successResult(challenge.copyOfRange(26, 42), targetReason.wireCode, 1234),
        ),
        DeterministicFakeCredentialSigner(fixtureSignature),
        timeoutMs = 1000,
        clock = MonotonicClock { 100 },
        mobileBuild = 100,
      ).run("00:11:22:33:44:55", credential) as SessionOutcome.Failure
      assertEquals(targetReason.wireCode, result.targetReason?.wireCode)
      assertEquals(targetReason.wireName, result.targetReason?.wireName)
      assertEquals(targetReason.observabilityReason, result.reason)
      assertEquals(1234, result.retryAfterMs)
    }
  }

  @Test
  fun crashAfterProofWriteLeavesDurableUncertainStateAndRestartCannotRepeatProof() = runBlocking {
    var durableState = DurableSessionState.RUNNING
    val transport = FakeTransport(targetHello, challenge, successResult(challenge.copyOfRange(26, 42)))
    val observer = object : ProofExecutionObserver {
      override fun beforeProofWrite() {
        durableState = DurableSessionState.PROOF_UNCERTAIN
      }

      override fun afterProofWrite() {
        throw SimulatedProcessDeath()
      }
    }
    try {
      GattSessionEngine(
        transport,
        DeterministicFakeCredentialSigner(fixtureSignature),
        timeoutMs = 1000,
        clock = MonotonicClock { 100 },
        mobileBuild = 100,
        proofObserver = observer,
      ).run("00:11:22:33:44:55", credential)
    } catch (_: SimulatedProcessDeath) {
      // Android process death bypasses normal worker completion.
    }
    assertEquals(DurableSessionState.PROOF_UNCERTAIN, durableState)
    assertEquals(1, transport.proofWrites)
    assertFalse(DurableAttemptPolicy.canExecute(durableState))
  }

  @Test
  fun crashAfterResultAndBeforeFinalLedgerCommitCannotRepeatProof() = runBlocking {
    var durableState = DurableSessionState.RUNNING
    val transport = FakeTransport(targetHello, challenge, successResult(challenge.copyOfRange(26, 42)))
    val observer = object : ProofExecutionObserver {
      override fun beforeProofWrite() {
        durableState = DurableSessionState.PROOF_UNCERTAIN
      }

      override fun afterResultReceived(result: TargetResult) {
        throw SimulatedProcessDeath()
      }
    }
    try {
      GattSessionEngine(
        transport,
        DeterministicFakeCredentialSigner(fixtureSignature),
        timeoutMs = 1000,
        clock = MonotonicClock { 100 },
        mobileBuild = 100,
        proofObserver = observer,
      ).run("00:11:22:33:44:55", credential)
    } catch (_: SimulatedProcessDeath) {
    }
    assertEquals(DurableSessionState.PROOF_UNCERTAIN, durableState)
    assertEquals(1, transport.proofWrites)
    assertFalse(DurableAttemptPolicy.canExecute(durableState))
  }
}

private class SimulatedProcessDeath : Error()

private class DeterministicFakeCredentialSigner(
  private val signature: ByteArray,
) : CredentialSigner {
  var lastCanonical: ByteArray? = null

  override fun signCanonical(credentialId: ByteArray, canonical: ByteArray): ByteArray {
    lastCanonical = canonical.copyOf()
    return signature.copyOf()
  }

  override fun publicKeySec1(credentialId: ByteArray): ByteArray = ByteArray(65).also { it[0] = 4 }
}

private class FakeTransport(
  private val targetHello: ByteArray,
  private val challenge: ByteArray,
  private val result: ByteArray,
) : BleGattTransport {
  var proof: ByteArray? = null
  var proofWrites = 0
  var closed = false
  var blockConnect = false
  var negotiateFailure: GattTransportException? = null

  override suspend fun connect(deviceAddress: String) {
    if (blockConnect) delay(Long.MAX_VALUE)
  }

  override suspend fun negotiate(clientHello: ByteArray): ByteArray =
    negotiateFailure?.let { throw it } ?: targetHello.copyOf()
  override suspend fun readChallenge(): ByteArray = challenge.copyOf()
  override suspend fun writeProof(proof: ByteArray) {
    proofWrites += 1
    this.proof = proof.copyOf()
  }
  override suspend fun awaitResult(): ByteArray = result.copyOf()
  override fun close() { closed = true }
}
