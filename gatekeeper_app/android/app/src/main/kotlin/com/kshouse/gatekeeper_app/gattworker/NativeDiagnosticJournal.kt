package com.kshouse.gatekeeper_app.gattworker

import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/** Bounded diagnostic work only. A slow disk must never backpressure Bluetooth callbacks. */
internal class NativeDiagnosticJournal(capacity: Int = 128) {
  private val rejected = AtomicLong()
  private val executor = ThreadPoolExecutor(1, 1, 0L, TimeUnit.MILLISECONDS,
    ArrayBlockingQueue<Runnable>(capacity), { task ->
      Thread(task, "sgk-diagnostic-journal").apply { isDaemon = true }
    }, ThreadPoolExecutor.AbortPolicy())

  fun submit(task: () -> Unit): Boolean = try {
    executor.execute(task)
    true
  } catch (_: RejectedExecutionException) {
    // No CallerRuns, disk write, blocking wait or unbounded overflow queue.
    rejected.incrementAndGet()
    false
  }

  fun pendingCount(): Int = executor.queue.size
  fun totalDropped(persisted: Long): Long = persisted + rejected.get()
  fun drainDropped(): Long = rejected.getAndSet(0)
  fun restoreDropped(count: Long) { rejected.addAndGet(count) }
  fun clearPending() { executor.queue.clear(); rejected.set(0) }
  fun close() { executor.shutdownNow() }
}
