package com.kshouse.gatekeeper_app.gattworker

import android.app.Application
import android.content.Context
import android.location.LocationManager
import android.os.Looper
import com.kshouse.gatekeeper_app.blewake.BleForegroundDiscovery
import com.kshouse.gatekeeper_app.blewake.BleForegroundDiscoveryStore
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.time.Duration

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class, manifest = Config.NONE)
class ForegroundDiscoveryLifecycleTest {
  private val context: Context get() = RuntimeEnvironment.getApplication()
  private val prefs get() = context.getSharedPreferences("ble_foreground_discovery_v1", Context.MODE_PRIVATE)
  @Before fun setup() {
    BleForegroundDiscovery.onBackground(context)
    prefs.edit().clear().commit()
  }
  @After fun cleanup() { BleForegroundDiscovery.onBackground(context) }

  @Test fun activityRecreationInvalidatesOldTimerAndNewGraceIsThreeSeconds() {
    BleForegroundDiscovery.onForeground(context)
    BleForegroundDiscovery.awaitPrimary(context)
    shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2))
    BleForegroundDiscovery.onBackground(context)
    BleForegroundDiscovery.onForeground(context)
    BleForegroundDiscovery.awaitPrimary(context)
    shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(1))
    assertEquals("WAITING_PRIMARY", prefs.getString("alternativeStage", null))
    shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(2))
    // No enrollment in this test: eligibility must stop before any radio start.
    assertEquals("ENVIRONMENT_BLOCKED", prefs.getString("alternativeStage", null))
  }

  @Test fun updaterCancelsPendingGraceAndCannotBeResurrectedByLateTimer() {
    BleForegroundDiscovery.onForeground(context)
    BleForegroundDiscovery.awaitPrimary(context)
    BleForegroundDiscovery.cancel(context, "CANCELLED_UPDATE")
    shadowOf(Looper.getMainLooper()).idleFor(Duration.ofSeconds(20))
    assertEquals("CANCELLED_UPDATE", prefs.getString("alternativeStage", null))
    assertFalse(prefs.contains("alternativeStartedAtEpochMs"))
    assertFalse(BleForegroundDiscovery.busy())
  }

  @Test fun clearDropsObservationButPreservesCooldownAndSuppressesOldWindowReflush() {
    prefs.edit().putString("alternativeStage", "SCANNING")
      .putLong("alternativeStartedAtEpochMs", 1234).putInt("alternativeResultCount", 900)
      .putString("alternativeRestoreStatus", "RESTORED").commit()
    BleForegroundDiscoveryStore.clear(context, 2000)
    assertFalse(prefs.contains("alternativeStage"))
    assertFalse(prefs.contains("alternativeResultCount"))
    assertEquals(1234L, prefs.getLong("last_attempt", 0))
    assertFalse(BleForegroundDiscoveryStore.visible(context, 1234))
    BleForegroundDiscoveryStore.finishWaiting(context, 1234, "MATCH_OBSERVED")
    assertFalse(prefs.contains("alternativeStage"))
    assertTrue(BleForegroundDiscoveryStore.visible(context, 2001))
  }

  @Test fun newWindowDoesNotAttachOldCountsToPrimaryMatchAndDeadProcessIsNotScanning() {
    prefs.edit().putString("alternativeStage", "SCANNING").putInt("alternativeMatchCount", 7)
      .putLong("alternativeStartedAtEpochMs", 1234).commit()
    assertEquals("PROCESS_INTERRUPTED", BleForegroundDiscovery.snapshot(context)["alternativeStage"])
    BleForegroundDiscoveryStore.waiting(context)
    BleForegroundDiscoveryStore.finishWaiting(context, System.currentTimeMillis(), "MATCH_OBSERVED")
    val snapshot = BleForegroundDiscovery.snapshot(context)
    assertEquals(0, snapshot["alternativeMatchCount"])
    assertNull(snapshot["alternativeStartedAtEpochMs"])
  }

  @Test fun locationSwitchIsObservedIndependentlyOfPermission() {
    val location = context.getSystemService(LocationManager::class.java)
    shadowOf(location).setLocationEnabled(false)
    assertEquals(false, BleGattRuntimeEnvironment.locationServicesEnabled(context))
    shadowOf(location).setLocationEnabled(true)
    assertEquals(true, BleGattRuntimeEnvironment.locationServicesEnabled(context))
  }
}
