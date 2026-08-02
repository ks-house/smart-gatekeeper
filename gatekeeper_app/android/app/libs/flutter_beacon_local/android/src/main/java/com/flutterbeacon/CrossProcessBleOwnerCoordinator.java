package com.flutterbeacon;

import android.content.Context;
import android.content.Intent;

import androidx.annotation.Nullable;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;

/**
 * Cross-process BLE ownership gate shared by the legacy scanner and native worker.
 *
 * <p>The requested-owner marker and the exclusive owner lease live in no-backup storage. Android
 * releases the file lock if an owning process dies, so restored preferences or a stale process
 * cannot manufacture ownership. No peer address, credential locator, or token is written here.
 */
public final class CrossProcessBleOwnerCoordinator {
  public static final String ACTION_STOP_LEGACY_BLE =
      "com.kshouse.gatekeeper_app.action.STOP_LEGACY_BLE_FOR_NATIVE";

  private static final String STATE_FILE = "ble-owner-request-v1";
  private static final String OWNER_FILE = "ble-owner-lease-v1";

  private final File directory;
  @Nullable private final Context applicationContext;

  public static CrossProcessBleOwnerCoordinator forContext(Context context) {
    Context appContext = context.getApplicationContext();
    return new CrossProcessBleOwnerCoordinator(appContext.getNoBackupFilesDir(), appContext);
  }

  /** Test seam: two instances over the same directory model distinct Android processes. */
  public CrossProcessBleOwnerCoordinator(File directory) {
    this(directory, null);
  }

  private CrossProcessBleOwnerCoordinator(File directory, @Nullable Context applicationContext) {
    this.directory = directory;
    this.applicationContext = applicationContext;
  }

  public boolean setNativeRequested(boolean requested) {
    ensureDirectory();
    File state = new File(directory, STATE_FILE);
    boolean changed;
    try (RandomAccessFile file = new RandomAccessFile(state, "rw");
         FileChannel channel = file.getChannel();
         FileLock ignored = channel.lock()) {
      boolean previous = file.length() > 0 && file.readByte() == 1;
      changed = previous != requested;
      file.seek(0);
      file.writeByte(requested ? 1 : 0);
      file.setLength(1);
      channel.force(true);
    } catch (IOException error) {
      return false;
    }
    if (changed && requested && applicationContext != null) {
      Intent intent = new Intent(ACTION_STOP_LEGACY_BLE).setPackage(applicationContext.getPackageName());
      applicationContext.sendBroadcast(intent);
    }
    return true;
  }

  public boolean isNativeRequested() {
    ensureDirectory();
    File state = new File(directory, STATE_FILE);
    if (!state.exists()) return false;
    try (RandomAccessFile file = new RandomAccessFile(state, "rw");
         FileChannel channel = file.getChannel();
         FileLock ignored = channel.lock()) {
      file.seek(0);
      return file.length() > 0 && file.readByte() == 1;
    } catch (IOException error) {
      return false;
    }
  }

  @Nullable
  public Lease tryAcquireLegacy() {
    if (isNativeRequested()) return null;
    Lease lease = tryAcquire("legacy");
    if (lease == null) return null;
    if (isNativeRequested()) {
      lease.close();
      return null;
    }
    return lease;
  }

  @Nullable
  public Lease tryAcquireNative() {
    if (!isNativeRequested()) return null;
    Lease lease = tryAcquire("native_gatt");
    if (lease == null) return null;
    if (!isNativeRequested()) {
      lease.close();
      return null;
    }
    return lease;
  }

  @Nullable
  private Lease tryAcquire(String owner) {
    ensureDirectory();
    try {
      RandomAccessFile file = new RandomAccessFile(new File(directory, OWNER_FILE), "rw");
      FileChannel channel = file.getChannel();
      FileLock lock;
      try {
        lock = channel.tryLock();
      } catch (OverlappingFileLockException error) {
        lock = null;
      }
      if (lock == null) {
        channel.close();
        file.close();
        return null;
      }
      return new Lease(owner, file, channel, lock);
    } catch (IOException error) {
      return null;
    }
  }

  private void ensureDirectory() {
    if (!directory.exists()) directory.mkdirs();
  }

  public static final class Lease implements Closeable {
    public final String owner;
    private final RandomAccessFile file;
    private final FileChannel channel;
    private final FileLock lock;
    private boolean closed;

    private Lease(String owner, RandomAccessFile file, FileChannel channel, FileLock lock) {
      this.owner = owner;
      this.file = file;
      this.channel = channel;
      this.lock = lock;
    }

    @Override
    public synchronized void close() {
      if (closed) return;
      closed = true;
      try {
        lock.release();
      } catch (IOException ignored) {
        // File ownership is fail-closed; process death also releases the kernel lock.
      }
      try {
        channel.close();
      } catch (IOException ignored) {
      }
      try {
        file.close();
      } catch (IOException ignored) {
      }
    }
  }
}
