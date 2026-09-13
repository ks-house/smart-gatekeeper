package com.kshouse.gatekeeper_app.gattworker

import android.app.Application
import android.content.Context
import androidx.work.*
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

/** Real WorkManager 2.9.1 database/unique chain, with no BLE or HTTP execution. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class, manifest = Config.NONE)
class NativeDiagnosticSchedulerIntegrationTest {
  @Test fun migrationKeepsReportAndRunningPredecessorGetsExactlyOneSuccessor() {
    val context = RuntimeEnvironment.getApplication()
    val workers = Executors.newFixedThreadPool(2)
    WorkManagerTestInitHelper.initializeTestWorkManager(context, Configuration.Builder()
      .setExecutor(workers).setTaskExecutor(SynchronousExecutor()).build())
    val manager = WorkManager.getInstance(context)
    val p = context.getSharedPreferences("native_diagnostic_outbox_v1", Context.MODE_PRIVATE)
    try {
      p.edit().clear().putBoolean("enabled", true).putBoolean("auth_required", true)
        .putLong("generation", 7).putString("pending", "immutable-test-report").commit()
      context.getSharedPreferences("native_diagnostic_scheduler", Context.MODE_PRIVATE).edit().clear().commit()
      val legacy = OneTimeWorkRequestBuilder<DiagnosticHoldingWorker>()
        .setInitialDelay(5, TimeUnit.HOURS).build()
      manager.enqueueUniqueWork("native-diagnostic-upload-v1", ExistingWorkPolicy.KEEP, legacy)
        .result.get(5, TimeUnit.SECONDS)
      NativeDiagnosticScheduler.ensurePeriodic(context)
      eventually { manager.getWorkInfoById(legacy.id).get().state == WorkInfo.State.CANCELLED }
      assertEquals(7, p.getLong("generation", 0))
      assertEquals("immutable-test-report", p.getString("pending", null))

      // Hold the actual v2 chain in RUNNING while a late event asks for upload.
      DiagnosticHoldingWorker.started = CountDownLatch(1)
      DiagnosticHoldingWorker.release = CountDownLatch(1)
      val running = OneTimeWorkRequestBuilder<DiagnosticHoldingWorker>().build()
      manager.enqueueUniqueWork("native-diagnostic-upload-v2", ExistingWorkPolicy.REPLACE, running)
        .result.get(5, TimeUnit.SECONDS)
      assertTrue(DiagnosticHoldingWorker.started.await(5, TimeUnit.SECONDS))
      p.edit().remove("auth_required").putLong("next_attempt", System.currentTimeMillis() + 60_000).commit()
      repeat(20) { NativeDiagnosticScheduler.upload(context) }
      eventually {
        manager.getWorkInfosForUniqueWork("native-diagnostic-upload-v2").get()
          .count { it.state == WorkInfo.State.BLOCKED } == 1
      }
      val infos = manager.getWorkInfosForUniqueWork("native-diagnostic-upload-v2").get()
      assertEquals(1, infos.count { it.state == WorkInfo.State.RUNNING })
      assertEquals(1, infos.count { it.state == WorkInfo.State.BLOCKED })
      assertEquals(2, infos.count { !it.state.isFinished })
      assertEquals("immutable-test-report", p.getString("pending", null))
    } finally {
      p.edit().putBoolean("enabled", false).commit()
      DiagnosticHoldingWorker.release.countDown()
      manager.cancelAllWork().result.get(5, TimeUnit.SECONDS)
      workers.shutdownNow()
    }
  }

  private fun eventually(check: () -> Boolean) {
    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
    while (System.nanoTime() < deadline) { if (check()) return; Thread.sleep(10) }
    assertTrue("WorkManager transition did not complete within 5 seconds", check())
  }
}

class DiagnosticHoldingWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
  override fun doWork(): Result {
    started.countDown()
    return if (release.await(10, TimeUnit.SECONDS)) Result.success() else Result.failure()
  }
  companion object {
    @Volatile var started = CountDownLatch(1)
    @Volatile var release = CountDownLatch(1)
  }
}
