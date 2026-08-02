package com.kshouse.gatekeeper_app.gattworker

import com.flutterbeacon.CrossProcessBleOwnerCoordinator
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.nio.file.Files

class BleOwnershipCoordinatorTest {
  @Test
  fun liveLegacyToNativeRollbackTransitionNeverHasTwoOwners() {
    val directory = Files.createTempDirectory("ble-owner-test").toFile()
    try {
      val legacyProcess = CrossProcessBleOwnerCoordinator(directory)
      val nativeProcess = CrossProcessBleOwnerCoordinator(directory)
      val legacyLease = legacyProcess.tryAcquireLegacy()
      assertNotNull(legacyLease)

      assertTrue(nativeProcess.setNativeRequested(true))
      assertNull(nativeProcess.tryAcquireNative())
      assertNull(legacyProcess.tryAcquireLegacy())

      legacyLease!!.close()
      val nativeLease = nativeProcess.tryAcquireNative()
      assertNotNull(nativeLease)
      assertNull(legacyProcess.tryAcquireLegacy())

      assertTrue(nativeProcess.setNativeRequested(false))
      assertNull(legacyProcess.tryAcquireLegacy())
      nativeLease!!.close()
      val rollbackLegacyLease = legacyProcess.tryAcquireLegacy()
      assertNotNull(rollbackLegacyLease)
      rollbackLegacyLease!!.close()
      assertFalse(nativeProcess.isNativeRequested())
    } finally {
      directory.deleteRecursively()
    }
  }
}
