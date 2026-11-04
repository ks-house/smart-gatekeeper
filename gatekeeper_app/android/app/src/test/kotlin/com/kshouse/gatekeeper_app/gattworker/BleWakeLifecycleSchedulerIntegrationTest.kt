package com.kshouse.gatekeeper_app.gattworker

import android.app.Application
import android.content.Context
import androidx.work.*
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import com.kshouse.gatekeeper_app.blewake.BleScanRecoveryReason
import com.kshouse.gatekeeper_app.blewake.BleWakeReconciliationScheduler
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowSystemClock
import java.time.Duration
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Real unique-work chain; holds only the worker so no Bluetooth work executes. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class, manifest = Config.NONE)
class BleWakeLifecycleSchedulerIntegrationTest {
  @Test fun repeatedLifecycleEventsKeepOneSuccessorWhileRegistrationPassIsRunning() {
    withHoldingPass { context, manager ->
      repeat(20) {
        BleWakeReconciliationScheduler.scheduleLifecycle(context, BleScanRecoveryReason.APP_BACKGROUND)
      }
      eventually {
        manager.getWorkInfosForUniqueWork(BleWakeReconciliationScheduler.LIFECYCLE_WORK).get()
          .count { it.state == WorkInfo.State.BLOCKED } == 1
      }
      ShadowSystemClock.advanceBy(Duration.ofSeconds(61))
      repeat(20) {
        BleWakeReconciliationScheduler.scheduleLifecycle(context, BleScanRecoveryReason.SCREEN_OFF)
      }
      // An already pending pass covers new events even after the throttle expires.
      eventually {
        manager.getWorkInfosForUniqueWork(BleWakeReconciliationScheduler.LIFECYCLE_WORK).get()
          .count { !it.state.isFinished } == 2
      }
      val infos = manager.getWorkInfosForUniqueWork(BleWakeReconciliationScheduler.LIFECYCLE_WORK).get()
      assertEquals(1, infos.count { it.state == WorkInfo.State.RUNNING })
      assertEquals(1, infos.count { it.state == WorkInfo.State.BLOCKED })
    }
  }

  @Test fun newEventAfterCancelledChainIsNotLostToKeepOrOldGeneration() {
    withHoldingPass { context, manager ->
      BleWakeReconciliationScheduler.scheduleLifecycle(context, BleScanRecoveryReason.APP_BACKGROUND)
      eventually {
        manager.getWorkInfosForUniqueWork(BleWakeReconciliationScheduler.LIFECYCLE_WORK).get()
          .any { it.state == WorkInfo.State.BLOCKED }
      }
      BleWakeReconciliationScheduler.cancel(context)
      eventually {
        manager.getWorkInfosForUniqueWork(BleWakeReconciliationScheduler.LIFECYCLE_WORK).get()
          .all { it.state.isFinished }
      }
      LifecycleHoldingWorker.release.countDown()
      ShadowSystemClock.advanceBy(Duration.ofSeconds(61))
      // A new held predecessor models a registration pass in the next enable cycle.
      LifecycleHoldingWorker.started = CountDownLatch(1)
      LifecycleHoldingWorker.release = CountDownLatch(1)
      val next = OneTimeWorkRequestBuilder<LifecycleHoldingWorker>().build()
      manager.enqueueUniqueWork(BleWakeReconciliationScheduler.LIFECYCLE_WORK, ExistingWorkPolicy.REPLACE, next)
        .result.get(5, TimeUnit.SECONDS)
      assertTrue(LifecycleHoldingWorker.started.await(5, TimeUnit.SECONDS))
      BleWakeReconciliationScheduler.scheduleLifecycle(context, BleScanRecoveryReason.SCREEN_OFF)
      eventually {
        manager.getWorkInfosForUniqueWork(BleWakeReconciliationScheduler.LIFECYCLE_WORK).get()
          .any { it.state == WorkInfo.State.BLOCKED }
      }
    }
  }

  @Test fun disabledRegistrationIntentNeverQueuesLifecycleRecovery() {
    withHoldingPass { context, manager ->
      context.getSharedPreferences("ble_wake_poc", Context.MODE_PRIVATE).edit()
        .putBoolean("registration_enabled", false).commit()
      BleWakeReconciliationScheduler.scheduleLifecycle(context, BleScanRecoveryReason.SCREEN_OFF)
      val infos = manager.getWorkInfosForUniqueWork(BleWakeReconciliationScheduler.LIFECYCLE_WORK).get()
      assertEquals(1, infos.count { !it.state.isFinished })
    }
  }

  private fun withHoldingPass(block: (Context, WorkManager) -> Unit) {
    val context = RuntimeEnvironment.getApplication()
    val workers = Executors.newFixedThreadPool(2)
    WorkManagerTestInitHelper.initializeTestWorkManager(context, Configuration.Builder()
      .setExecutor(workers).setTaskExecutor(SynchronousExecutor()).build())
    val manager = WorkManager.getInstance(context)
    context.getSharedPreferences("ble_wake_poc", Context.MODE_PRIVATE).edit().clear()
      .putBoolean("registration_enabled", true).commit()
    context.getSharedPreferences("ble_wake_lifecycle_recovery_v1", Context.MODE_PRIVATE).edit().clear().commit()
    context.getSharedPreferences("ble_scan_diagnostics_v1", Context.MODE_PRIVATE).edit().clear().commit()
    LifecycleHoldingWorker.started = CountDownLatch(1)
    LifecycleHoldingWorker.release = CountDownLatch(1)
    try {
      val running = OneTimeWorkRequestBuilder<LifecycleHoldingWorker>().build()
      manager.enqueueUniqueWork(BleWakeReconciliationScheduler.LIFECYCLE_WORK, ExistingWorkPolicy.REPLACE, running)
        .result.get(5, TimeUnit.SECONDS)
      assertTrue(LifecycleHoldingWorker.started.await(5, TimeUnit.SECONDS))
      block(context, manager)
    } finally {
      context.getSharedPreferences("ble_wake_poc", Context.MODE_PRIVATE).edit()
        .putBoolean("registration_enabled", false).commit()
      BleWakeReconciliationScheduler.cancel(context)
      LifecycleHoldingWorker.release.countDown()
      manager.cancelAllWork().result.get(5, TimeUnit.SECONDS)
      workers.shutdownNow()
    }
  }

  private fun eventually(check: () -> Boolean) {
    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
    while (System.nanoTime() < deadline) {
      if (check()) return
      Thread.sleep(10)
    }
    assertTrue("native lifecycle recovery did not enqueue within five seconds", check())
  }
}

class LifecycleHoldingWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
  override fun doWork(): Result {
    started.countDown()
    return if (release.await(10, TimeUnit.SECONDS)) Result.success() else Result.failure()
  }
  companion object {
    @Volatile var started = CountDownLatch(1)
    @Volatile var release = CountDownLatch(1)
  }
}
