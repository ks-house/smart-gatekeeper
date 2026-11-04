package com.kshouse.gatekeeper_app.gattworker

import android.app.Application
import android.content.Context
import androidx.work.Configuration
import androidx.work.WorkManager
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.TestWorkerBuilder
import androidx.work.testing.WorkManagerTestInitHelper
import com.kshouse.gatekeeper_app.blewake.BleWakeReconciliationWorker
import org.junit.Assert.assertFalse
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

/** Executes the actual native worker without Flutter, radio access or credentials. */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], application = Application::class, manifest = Config.NONE)
class BleWakeLifecycleRecoveryTest {
  @Test fun queuedReconciliationRechecksDisabledFeatureBeforeRegistering() {
    val context = RuntimeEnvironment.getApplication()
    val executor = SynchronousExecutor()
    WorkManagerTestInitHelper.initializeTestWorkManager(context,
      Configuration.Builder().setExecutor(executor).setTaskExecutor(executor).build())
    val registration = context.getSharedPreferences("ble_wake_poc", Context.MODE_PRIVATE)
    registration.edit().clear().putBoolean("registration_enabled", true).commit()
    try {
      // Models work enqueued before a remote/local feature decision becomes disabled.
      // An absent credential/consent is an actual default-OFF decision, not a mock.
      val worker = TestWorkerBuilder<BleWakeReconciliationWorker>(context, executor).build()
      worker.doWork()
      assertFalse("background recovery must honor the current native feature decision",
        registration.getBoolean("registration_enabled", true))
    } finally {
      WorkManager.getInstance(context).cancelAllWork().result.get()
    }
  }
}
