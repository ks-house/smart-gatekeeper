package com.flutterbeacon;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.location.LocationManager;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;

import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import org.altbeacon.beacon.BeaconTransmitter;

import java.lang.ref.WeakReference;

/**
 * Platform capability / permission checks.
 *
 * <p>All <b>read-only checks</b> run against the application context so they keep
 * working while the app has no foreground Activity (issue.md P0-3).
 *
 * <p>Only the three operations that genuinely require an Activity — runtime
 * permission requests, {@code startActivityForResult} and
 * {@code shouldShowRequestPermissionRationale} — need one, and each degrades
 * gracefully when the Activity is absent. Call {@link #hasActivity()} first.
 */
class FlutterPlatform {
  private static final String TAG = "FlutterPlatform";

  private final Context applicationContext;
  private WeakReference<Activity> activityWeakReference;

  FlutterPlatform(Context context) {
    this.applicationContext = context.getApplicationContext();
  }

  void attachActivity(Activity activity) {
    this.activityWeakReference = new WeakReference<>(activity);
  }

  void detachActivity() {
    this.activityWeakReference = null;
  }

  private Activity getActivity() {
    return activityWeakReference == null ? null : activityWeakReference.get();
  }

  boolean hasActivity() {
    return getActivity() != null;
  }

  void openLocationSettings() {
    Intent intent = new Intent(Settings.ACTION_LOCATION_SOURCE_SETTINGS);
    intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    // FLAG_ACTIVITY_NEW_TASK 가 설정되어 있으므로 application context 로도 동작한다.
    Activity activity = getActivity();
    if (activity != null) {
      activity.startActivity(intent);
    } else {
      applicationContext.startActivity(intent);
    }
  }

  void openBluetoothSettings() {
    Activity activity = getActivity();
    if (activity == null) {
      Log.w(TAG, "openBluetoothSettings requires a foreground activity");
      return;
    }
    Intent intent = new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE);
    activity.startActivityForResult(intent, FlutterBeaconPlugin.REQUEST_CODE_BLUETOOTH);
  }

  /**
   * Requests every permission AltBeacon needs to actually receive scan results.
   *
   * <p>Location alone is not sufficient from Android 12 (API 31) onwards —
   * {@code BLUETOOTH_SCAN} is also required, and without it scans return zero
   * results with no error. The original implementation requested location only,
   * so {@code initializeAndCheck()} could report success while scanning was
   * silently impossible (issue.md P1-8).
   */
  void requestAuthorization() {
    Activity activity = getActivity();
    if (activity == null) {
      Log.w(TAG, "requestAuthorization requires a foreground activity");
      return;
    }

    String[] permissions;
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
      permissions = new String[]{
          Manifest.permission.ACCESS_COARSE_LOCATION,
          Manifest.permission.ACCESS_FINE_LOCATION,
          Manifest.permission.BLUETOOTH_SCAN,
          Manifest.permission.BLUETOOTH_CONNECT
      };
    } else {
      permissions = new String[]{
          Manifest.permission.ACCESS_COARSE_LOCATION,
          Manifest.permission.ACCESS_FINE_LOCATION
      };
    }

    ActivityCompat.requestPermissions(activity, permissions, FlutterBeaconPlugin.REQUEST_CODE_LOCATION);
  }

  /**
   * @return true only when every permission required for BLE scanning is granted.
   */
  boolean checkLocationServicesPermission() {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
      return true;
    }

    boolean locationGranted = isPermissionGranted(Manifest.permission.ACCESS_COARSE_LOCATION);

    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
      // Android 12+ 에서는 BLUETOOTH_SCAN 없이는 스캔 결과가 오지 않는다.
      return locationGranted && isPermissionGranted(Manifest.permission.BLUETOOTH_SCAN);
    }

    return locationGranted;
  }

  private boolean isPermissionGranted(String permission) {
    return ContextCompat.checkSelfPermission(applicationContext, permission)
        == PackageManager.PERMISSION_GRANTED;
  }

  boolean checkLocationServicesIfEnabled() {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
      LocationManager locationManager =
          (LocationManager) applicationContext.getSystemService(Context.LOCATION_SERVICE);
      return locationManager != null && locationManager.isLocationEnabled();
    }

    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
      int mode = Settings.Secure.getInt(applicationContext.getContentResolver(),
          Settings.Secure.LOCATION_MODE, Settings.Secure.LOCATION_MODE_OFF);
      return (mode != Settings.Secure.LOCATION_MODE_OFF);
    }

    return true;
  }

  @SuppressLint("MissingPermission")
  boolean checkBluetoothIfEnabled() {
    BluetoothManager bluetoothManager = (BluetoothManager)
        applicationContext.getSystemService(Context.BLUETOOTH_SERVICE);
    if (bluetoothManager == null) {
      throw new RuntimeException("No bluetooth service");
    }

    BluetoothAdapter adapter = bluetoothManager.getAdapter();

    return (adapter != null) && (adapter.isEnabled());
  }

  boolean isBroadcastSupported() {
    return BeaconTransmitter.checkTransmissionSupported(applicationContext) == 0;
  }

  boolean shouldShowRequestPermissionRationale(String permission) {
    Activity activity = getActivity();
    if (activity == null) {
      // Activity 가 없으면 rationale 을 판단할 수 없다.
      // 호출부는 이 값이 false 일 때 "영구 거부"로 해석하므로 false 를 돌려준다.
      return false;
    }
    return ActivityCompat.shouldShowRequestPermissionRationale(activity, permission);
  }
}
