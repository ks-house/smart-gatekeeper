package com.kshouse.gatekeeper_app.gattworker

import java.io.File
import org.junit.Assert.*
import org.junit.Test

/** Cross-boundary source guards complement the pure packet/session replay tests. */
class BleFieldRecoverySourceTest {
  private val sources by lazy {
    BleFieldRecoveryTestSources.resolve(File(System.getProperty("user.dir")))
  }
  private fun source(path: String) = File(sources, path).readText()

  @Test fun sourceRootSupportsDockerModuleAndRepositoryWorkingDirectories() {
    val layouts = listOf(
      "/workspace" to "/workspace/android/app",
      "/workspace/android" to "/workspace/android/app",
      "/workspace/android/app" to "/workspace/android/app",
      "/checkout" to "/checkout/gatekeeper_app/android/app",
      "/checkout/gatekeeper_app" to "/checkout/gatekeeper_app/android/app",
      "/checkout/gatekeeper_app/android" to "/checkout/gatekeeper_app/android/app",
      "/checkout/gatekeeper_app/android/app" to "/checkout/gatekeeper_app/android/app",
    )
    for ((cwd, module) in layouts) {
      val expected = File(module, BleFieldRecoveryTestSources.SOURCE_PATH)
      val files = BleFieldRecoveryTestSources.REQUIRED_FILES.map { File(expected, it).path }.toSet()
      assertEquals(expected, BleFieldRecoveryTestSources.resolve(File(cwd)) { it.path in files })
    }
  }

  @Test fun missingOrPartialSourceRootsFailExplicitlyWithoutSkippingAssertions() {
    val absent = runCatching { BleFieldRecoveryTestSources.resolve(File("/missing")) { false } }.exceptionOrNull()
    assertTrue(absent is AssertionError)
    assertTrue(absent!!.message.orEmpty().contains("BLE source root unavailable"))
    val partial = runCatching {
      BleFieldRecoveryTestSources.resolve(File("/workspace/android")) { it.name == "BleWakeNativeEntrypoint.kt" }
    }.exceptionOrNull()
    assertTrue(partial is AssertionError)
  }

  @Test fun allMatchAndFirstMatchShareFreshRfCheckAndNeverUseCachedAddressAsPresence() {
    val entry = source("blewake/BleWakeNativeEntrypoint.kt")
    val positive = entry.substringAfter("BleWakeDispatchAction.PRESENCE ->")
      .substringBefore("BleWakeDispatchAction.IGNORE ->")
    assertTrue(positive.contains("BleScanObservationPolicy.fresh(event.latencyMs)"))
    assertTrue(positive.contains("ContinuousPresenceTracker.observe("))
    assertTrue(positive.contains("event.readyHintMalformed"))
    assertTrue(positive.contains("onMissingReadyHint("))
    assertTrue(positive.indexOf("BleScanObservationPolicy.fresh(event.latencyMs)") <
      positive.indexOf("ContinuousPresenceTracker.observe("))
    assertTrue(positive.indexOf("event.readyHintMalformed") < positive.indexOf("onMissingReadyHint("))
    assertFalse(positive.contains(".resolve()"))
    assertFalse(positive.contains("CALLBACK_TYPE_ALL_MATCHES"))
    val receiver = source("blewake/BleWakeScanReceiver.kt")
    assertTrue(receiver.contains("BleScanObservationPolicy.selectMatching"))
    assertFalse(receiver.contains("coerceAtLeast(0L)")) // Future scan timestamps cannot look fresh.
  }

  @Test fun missingHintProbeRequiresDurableV2AndChecksRfBeforeConnectAndBeforeProof() {
    val worker = source("gattworker/BleGattCredentialWorker.kt")
    assertTrue(worker.contains("ContinuousPresencePolicy.missingHintBlockingReason(last, now)"))
    assertTrue(worker.contains("requiresFastV2 = epoch == null"))
    assertTrue(worker.contains("requireFastV2 = initial.requiresFastV2"))
    val transport = source("gattworker/AndroidBleGattTransport.kt")
    assertTrue(transport.contains("if (requireFastV2 && protocolMode != GattProtocolMode.FAST_V2)"))
    assertTrue(transport.indexOf("if (requireFastV2 &&") < transport.indexOf("enableIndication(GattProtocol.HELLO_UUID)"))
    val run = worker.substringAfter("private suspend fun runSession()")
    assertTrue(run.contains("initial.requiresFreshPresence && !ContinuousPresenceTracker.fresh("))
    assertTrue(run.indexOf("initial.requiresFreshPresence && !ContinuousPresenceTracker.fresh(") <
      run.indexOf("transport = AndroidBleGattTransport("))
    val proof = run.substringAfter("override fun beforeProofWrite()")
    assertTrue(proof.contains("ContinuousPresenceTracker.fresh("))
    assertTrue(proof.contains("ledgerUpdateUncertain("))
    assertTrue(proof.indexOf("ContinuousPresenceTracker.fresh(") < proof.indexOf("ledgerUpdateUncertain("))
    val engine = source("gattworker/GattSessionEngine.kt")
    assertTrue(engine.contains("if (requireFastV2 &&"))
    assertTrue(engine.indexOf("if (requireFastV2 &&") < engine.indexOf("transport.negotiate(clientHello)"))
    assertTrue(worker.contains("outcome.proofMayHaveExecuted && outcome.targetReason == null"))
  }

  @Test fun finiteObservationDoesNotAddScannerOrClaimRfFromAcceptedRegistration() {
    val observer = source("blewake/BleScanRecoveryObserver.kt")
    assertFalse(observer.contains("startScan("))
    assertFalse(observer.contains("BleGattWorkScheduler"))
    assertTrue(observer.contains("ExistingWorkPolicy.REPLACE"))
    assertTrue(observer.contains("setInitialDelay(BleScanRecoveryPolicy.CONFIRMATION_WINDOW_MS"))
    val registrar = source("blewake/BleWakeRegistrar.kt")
    assertTrue(registrar.contains("fun onAppForeground(context: Context)"))
    val register = registrar.substringAfter("private fun registerOnce(").substringBefore("fun stop(")
    assertTrue(register.contains("tryAcquireNative()"))
    assertTrue(register.contains("scanner.stopScan("))
    assertTrue(register.indexOf("tryAcquireNative()") < register.indexOf("scanner.stopScan("))
    assertFalse(register.contains("BleScanDiagnostics.callback("))
    val transport = source("gattworker/AndroidBleGattTransport.kt")
    assertFalse(transport.contains("getMethod(\"refresh\""))
    assertTrue(transport.contains("GattDiscoveryFailurePolicy.callback("))
  }
}

/** Closed module layouts used by Docker and CI; a missing source is a test failure. */
private object BleFieldRecoveryTestSources {
  const val SOURCE_PATH = "src/main/kotlin/com/kshouse/gatekeeper_app"
  val REQUIRED_FILES = listOf(
    "blewake/BleWakeNativeEntrypoint.kt", "blewake/BleWakeScanReceiver.kt",
    "blewake/BleScanRecoveryObserver.kt", "blewake/BleWakeRegistrar.kt",
    "gattworker/BleGattCredentialWorker.kt", "gattworker/AndroidBleGattTransport.kt",
    "gattworker/GattSessionEngine.kt",
  )

  fun resolve(cwd: File, isFile: (File) -> Boolean = { it.isFile }): File {
    val candidates = listOf(cwd, File(cwd, "app"), File(cwd, "android/app"),
      File(cwd, "gatekeeper_app/android/app")).map { File(it, SOURCE_PATH) }.distinct()
    return candidates.firstOrNull { root -> REQUIRED_FILES.all { isFile(File(root, it)) } }
      ?: throw AssertionError("BLE source root unavailable from ${cwd.path}; checked: " +
        candidates.joinToString { it.path })
  }
}
