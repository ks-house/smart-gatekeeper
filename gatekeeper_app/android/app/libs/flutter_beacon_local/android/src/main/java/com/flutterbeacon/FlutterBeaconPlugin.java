package com.flutterbeacon;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.RemoteException;
import android.os.PowerManager;
import android.util.Log;

import androidx.annotation.NonNull;

import org.altbeacon.beacon.BeaconManager;
import org.altbeacon.beacon.BeaconParser;

import io.flutter.embedding.engine.plugins.FlutterPlugin;
import io.flutter.embedding.engine.plugins.activity.ActivityAware;
import io.flutter.embedding.engine.plugins.activity.ActivityPluginBinding;
import io.flutter.plugin.common.BinaryMessenger;
import io.flutter.plugin.common.EventChannel;
import io.flutter.plugin.common.MethodCall;
import io.flutter.plugin.common.MethodChannel;
import io.flutter.plugin.common.MethodChannel.MethodCallHandler;
import io.flutter.plugin.common.MethodChannel.Result;
import io.flutter.plugin.common.PluginRegistry;


/**
 * flutter_beacon Android plugin.
 *
 * <h3>Lifecycle contract (issue.md P0-3)</h3>
 *
 * Channels, the {@link BeaconManager} binding and the scanner are owned by the
 * <b>FlutterEngine</b> and the <b>application context</b> — never by the Activity.
 *
 * <p>The original implementation created every channel in
 * {@code onAttachedToActivity()} and tore them all down in
 * {@code onDetachedFromActivity()}, and bound the AltBeacon service through
 * {@code Activity.bindService()}. That made background operation structurally
 * impossible:
 *
 * <ul>
 *   <li>Activity destruction nulled every StreamHandler, so ranging events stopped
 *       being delivered <b>without any error surfacing to Dart</b> — the Dart
 *       subscription stayed alive and simply went silent.</li>
 *   <li>The service binding was owned by the Activity, so Android auto-unbound it
 *       on destruction and scanning stopped outright.</li>
 *   <li>Re-attaching created a <i>new</i> {@code FlutterBeaconScanner} (hence a new
 *       {@code BeaconConsumer}), so {@code isBound()} returned false and the plugin
 *       bound a second time while the previous consumer was left dangling.</li>
 *   <li>{@code onDetachedFromActivityForConfigChanges()} delegated to
 *       {@code onDetachedFromActivity()}, so an Activity-recreating config change
 *       destroyed the channels too.</li>
 * </ul>
 *
 * <p>The Activity is now only needed for the three things that genuinely require
 * one: runtime permission requests, {@code startActivityForResult} and
 * {@code shouldShowRequestPermissionRationale}. Those live in
 * {@link FlutterPlatform}, which tolerates a null Activity.
 */
public class FlutterBeaconPlugin implements FlutterPlugin, ActivityAware, MethodCallHandler,
    PluginRegistry.RequestPermissionsResultListener,
    PluginRegistry.ActivityResultListener {

  private static final String TAG = "FlutterBeaconPlugin";

  private static final BeaconParser iBeaconLayout = new BeaconParser()
      .setBeaconLayout("m:2-3=0215,i:4-19,i:20-21,i:22-23,p:24-24");

  static final int REQUEST_CODE_LOCATION = 1234;
  static final int REQUEST_CODE_BLUETOOTH = 5678;

  private Context applicationContext;
  private ActivityPluginBinding activityPluginBinding;

  private FlutterBeaconScanner beaconScanner;
  private FlutterBeaconBroadcast beaconBroadcast;
  private FlutterPlatform platform;

  private BeaconManager beaconManager;
  Result flutterResult;
  private Result flutterResultBluetooth;
  private EventChannel.EventSink eventSinkLocationAuthorizationStatus;

  private MethodChannel channel;
  private EventChannel eventChannel;
  private EventChannel eventChannelMonitoring;
  private EventChannel eventChannelBluetoothState;
  private EventChannel eventChannelAuthorizationStatus;

  public FlutterBeaconPlugin() {

  }

  // region ENGINE LIFECYCLE — 채널/스캔의 실제 소유자
  @Override
  public void onAttachedToEngine(@NonNull FlutterPluginBinding binding) {
    this.applicationContext = binding.getApplicationContext();
    setupChannels(binding.getBinaryMessenger(), applicationContext);
  }

  @Override
  public void onDetachedFromEngine(@NonNull FlutterPluginBinding binding) {
    teardownChannels();
    this.applicationContext = null;
  }
  // endregion

  // region ACTIVITY LIFECYCLE — 권한/설정 화면 전용. 채널은 절대 건드리지 않는다.
  @Override
  public void onAttachedToActivity(@NonNull ActivityPluginBinding binding) {
    this.activityPluginBinding = binding;
    binding.addActivityResultListener(this);
    binding.addRequestPermissionsResultListener(this);
    if (platform != null) {
      platform.attachActivity(binding.getActivity());
    }
  }

  @Override
  public void onDetachedFromActivityForConfigChanges() {
    onDetachedFromActivity();
  }

  @Override
  public void onReattachedToActivityForConfigChanges(@NonNull ActivityPluginBinding binding) {
    onAttachedToActivity(binding);
  }

  @Override
  public void onDetachedFromActivity() {
    if (activityPluginBinding != null) {
      activityPluginBinding.removeActivityResultListener(this);
      activityPluginBinding.removeRequestPermissionsResultListener(this);
      activityPluginBinding = null;
    }
    if (platform != null) {
      platform.detachActivity();
    }
    // ⚠️ 스캔/채널을 여기서 정리하면 백그라운드 상주가 깨진다. 아무것도 하지 않는다.
  }
  // endregion

  BeaconManager getBeaconManager() {
    return beaconManager;
  }

  private void setupChannels(BinaryMessenger messenger, Context context) {
    beaconManager = BeaconManager.getInstanceForApplication(context);
    if (!beaconManager.getBeaconParsers().contains(iBeaconLayout)) {
      beaconManager.getBeaconParsers().clear();
      beaconManager.getBeaconParsers().add(iBeaconLayout);
    }

    // 자체 포그라운드 서비스로 상주 스캔하는 앱을 전제로 한다.
    // 바인딩 이전인 지금 호출해야 AltBeacon 이 변경을 받아들인다. (issue.md P0-2)
    setEnableScheduledScanJobsQuietly(false);

    platform = new FlutterPlatform(context);
    // 스캐너는 플러그인 생애 동안 단 하나만 존재해야 한다 —
    // BeaconConsumer 인스턴스 동일성이 유지되어야 isBound() 가 정상 동작한다.
    if (beaconScanner == null) {
      beaconScanner = new FlutterBeaconScanner(this, context);
    }
    beaconBroadcast = new FlutterBeaconBroadcast(context, iBeaconLayout);

    channel = new MethodChannel(messenger, "flutter_beacon");
    channel.setMethodCallHandler(this);

    eventChannel = new EventChannel(messenger, "flutter_beacon_event");
    eventChannel.setStreamHandler(beaconScanner.rangingStreamHandler);

    eventChannelMonitoring = new EventChannel(messenger, "flutter_beacon_event_monitoring");
    eventChannelMonitoring.setStreamHandler(beaconScanner.monitoringStreamHandler);

    eventChannelBluetoothState = new EventChannel(messenger, "flutter_bluetooth_state_changed");
    eventChannelBluetoothState.setStreamHandler(new FlutterBluetoothStateReceiver(context));

    eventChannelAuthorizationStatus = new EventChannel(messenger, "flutter_authorization_status_changed");
    eventChannelAuthorizationStatus.setStreamHandler(locationAuthorizationStatusStreamHandler);
  }

  private void teardownChannels() {
    // 이중 호출 / 부분 초기화 상태에서도 NPE 없이 통과해야 한다.
    if (channel != null) {
      channel.setMethodCallHandler(null);
      channel = null;
    }
    if (eventChannel != null) {
      eventChannel.setStreamHandler(null);
      eventChannel = null;
    }
    if (eventChannelMonitoring != null) {
      eventChannelMonitoring.setStreamHandler(null);
      eventChannelMonitoring = null;
    }
    if (eventChannelBluetoothState != null) {
      eventChannelBluetoothState.setStreamHandler(null);
      eventChannelBluetoothState = null;
    }
    if (eventChannelAuthorizationStatus != null) {
      eventChannelAuthorizationStatus.setStreamHandler(null);
      eventChannelAuthorizationStatus = null;
    }

    // 엔진이 사라지면 스캔을 유지할 이유가 없다 — 여기서만 확실히 해제한다.
    if (beaconManager != null && beaconScanner != null) {
      beaconScanner.stopRanging();
      beaconScanner.stopMonitoring();
      if (beaconManager.isBound(beaconScanner.beaconConsumer)) {
        beaconManager.unbind(beaconScanner.beaconConsumer);
      }
    }

    platform = null;
    beaconBroadcast = null;
  }

  @Override
  public void onMethodCall(@NonNull MethodCall call, @NonNull final Result result) {
    if (call.method.equals("isScreenInteractive")) {
      if (applicationContext == null) {
        result.error("Beacon", "application context unavailable", null);
        return;
      }
      PowerManager powerManager =
          (PowerManager) applicationContext.getSystemService(Context.POWER_SERVICE);
      result.success(powerManager == null || powerManager.isInteractive());
      return;
    }

    if (call.method.equals("initialize")) {
      if (nativeGattOwnsScanner()) {
        result.error(
            "BLE_OWNER_EXCLUDED",
            "Native GATT worker owns BLE while the validated feature flag is active",
            null);
        return;
      }
      if (beaconManager != null && !beaconManager.isBound(beaconScanner.beaconConsumer)) {
        this.flutterResult = result;
        this.beaconManager.bind(beaconScanner.beaconConsumer);

        return;
      }

      result.success(true);
      return;
    }

    if (call.method.equals("initializeAndCheck")) {
      initializeAndCheck(result);
      return;
    }

    // ─────────────────────────────────────────────────────────────────────
    // 스캔 주기 / 스캔 모드 튜닝 (issue.md P0-2, P1-9)
    //
    // ⚠️ 각 분기는 반드시 `return` 으로 끝내야 한다. return 이 없으면 제어가
    //    메서드 끝의 result.notImplemented() 까지 흘러가
    //    IllegalStateException: Reply already submitted 로 죽는다.
    //    (원래 setScanPeriod / setBetweenScanPeriod 가 이 버그를 갖고 있었다)
    // ─────────────────────────────────────────────────────────────────────
    if (call.method.equals("setScanPeriod")) {
      Integer scanPeriod = argumentAsInt(call, "scanPeriod");
      if (beaconManager == null || scanPeriod == null) {
        result.error("Beacon", "setScanPeriod: beaconManager unavailable or invalid argument", null);
        return;
      }
      beaconManager.setForegroundScanPeriod(scanPeriod.longValue());
      result.success(updateScanPeriodsQuietly());
      return;
    }

    if (call.method.equals("setBetweenScanPeriod")) {
      Integer betweenScanPeriod = argumentAsInt(call, "betweenScanPeriod");
      if (beaconManager == null || betweenScanPeriod == null) {
        result.error("Beacon", "setBetweenScanPeriod: beaconManager unavailable or invalid argument", null);
        return;
      }
      beaconManager.setForegroundBetweenScanPeriod(betweenScanPeriod.longValue());
      result.success(updateScanPeriodsQuietly());
      return;
    }

    if (call.method.equals("setBackgroundScanPeriod")) {
      Integer scanPeriod = argumentAsInt(call, "scanPeriod");
      if (beaconManager == null || scanPeriod == null) {
        result.error("Beacon", "setBackgroundScanPeriod: beaconManager unavailable or invalid argument", null);
        return;
      }
      beaconManager.setBackgroundScanPeriod(scanPeriod.longValue());
      result.success(updateScanPeriodsQuietly());
      return;
    }

    if (call.method.equals("setBackgroundBetweenScanPeriod")) {
      Integer betweenScanPeriod = argumentAsInt(call, "betweenScanPeriod");
      if (beaconManager == null || betweenScanPeriod == null) {
        result.error("Beacon", "setBackgroundBetweenScanPeriod: beaconManager unavailable or invalid argument", null);
        return;
      }
      // AltBeacon 기본값은 300000ms(5분)다. 이 값을 줄이지 않으면
      // 백그라운드 모드에서 RSSI 가 5분에 한 번만 갱신된다.
      beaconManager.setBackgroundBetweenScanPeriod(betweenScanPeriod.longValue());
      result.success(updateScanPeriodsQuietly());
      return;
    }

    if (call.method.equals("setBackgroundMode")) {
      Boolean enabled = argumentAsBool(call, "backgroundMode");
      if (beaconManager == null || enabled == null) {
        result.error("Beacon", "setBackgroundMode: beaconManager unavailable or invalid argument", null);
        return;
      }
      // ⚠️ AltBeacon 은 backgroundMode 플래그 하나로 두 가지를 동시에 결정한다.
      //      true  → ScanFilter 사용 + SCAN_MODE_LOW_POWER
      //      false → ScanFilter 없음 + SCAN_MODE_LOW_LATENCY
      //    Android 8.1+ 는 화면이 꺼진 동안 "필터 없는 스캔"의 결과를 앱에
      //    전달하지 않는다. 따라서 화면 OFF 에서 동작시키려면 true 가 필수다.
      try {
        beaconManager.setBackgroundMode(enabled);
        Log.d(TAG, "setBackgroundMode = " + enabled);
        result.success(true);
      } catch (Exception e) {
        Log.w(TAG, "setBackgroundMode failed: " + e);
        result.success(false);
      }
      return;
    }

    if (call.method.equals("setEnableScheduledScanJobs")) {
      Boolean enabled = argumentAsBool(call, "enabled");
      if (beaconManager == null || enabled == null) {
        result.error("Beacon", "setEnableScheduledScanJobs: beaconManager unavailable or invalid argument", null);
        return;
      }
      result.success(setEnableScheduledScanJobsQuietly(enabled));
      return;
    }

    if (call.method.equals("setLocationAuthorizationTypeDefault")) {
      // Android does not have the concept of "requestWhenInUse" and "requestAlways" like iOS does,
      // so this method does nothing.
      // (Well, in Android API 29 and higher, there is an "ACCESS_BACKGROUND_LOCATION" option,
      //  which could perhaps be appropriate to add here as an improvement.)
      result.success(true);
      return;
    }

    if (call.method.equals("authorizationStatus")) {
      if (platform == null) {
        result.error("Beacon", "plugin not attached to an engine", null);
        return;
      }
      result.success(platform.checkLocationServicesPermission() ? "ALLOWED" : "NOT_DETERMINED");
      return;
    }

    if (call.method.equals("checkLocationServicesIfEnabled")) {
      if (platform == null) {
        result.error("Beacon", "plugin not attached to an engine", null);
        return;
      }
      result.success(platform.checkLocationServicesIfEnabled());
      return;
    }

    if (call.method.equals("bluetoothState")) {
      if (platform != null) {
        try {
          boolean flag = platform.checkBluetoothIfEnabled();
          result.success(flag ? "STATE_ON" : "STATE_OFF");
          return;
        } catch (RuntimeException ignored) {

        }
      }

      result.success("STATE_UNSUPPORTED");
      return;
    }

    if (call.method.equals("requestAuthorization")) {
      if (platform == null) {
        result.error("Beacon", "plugin not attached to an engine", null);
        return;
      }
      if (!platform.checkLocationServicesPermission()) {
        if (!platform.hasActivity()) {
          // 백그라운드에서는 권한 대화상자를 띄울 수 없다.
          result.error("Beacon", "no foreground activity to request permissions", null);
          return;
        }
        this.flutterResult = result;
        platform.requestAuthorization();
        return;
      }

      // Here, location services permission is granted.
      //
      // It's possible location permission was granted without going through
      // our onRequestPermissionsResult() - for example if a different flutter plugin
      // also requested location permissions, we could end up here with
      // checkLocationServicesPermission() returning true before we ever called requestAuthorization().
      //
      // In that case, we'll never get a notification posted to eventSinkLocationAuthorizationStatus
      //
      // So we could could have flutter code calling requestAuthorization here and expecting to see
      // a change in eventSinkLocationAuthorizationStatus but never receiving it.
      //
      // Ensure an ALLOWED status (possibly duplicate) is posted back.
      if (eventSinkLocationAuthorizationStatus != null) {
        eventSinkLocationAuthorizationStatus.success("ALLOWED");
      }

      result.success(true);
      return;
    }

    if (call.method.equals("openBluetoothSettings")) {
      if (platform == null) {
        result.error("Beacon", "plugin not attached to an engine", null);
        return;
      }
      if (!platform.checkBluetoothIfEnabled()) {
        if (!platform.hasActivity()) {
          result.error("Beacon", "no foreground activity to open bluetooth settings", null);
          return;
        }
        this.flutterResultBluetooth = result;
        platform.openBluetoothSettings();
        return;
      }

      result.success(true);
      return;
    }

    if (call.method.equals("openLocationSettings")) {
      if (platform == null) {
        result.error("Beacon", "plugin not attached to an engine", null);
        return;
      }
      platform.openLocationSettings();
      result.success(true);
      return;
    }

    if (call.method.equals("openApplicationSettings")) {
      result.notImplemented();
      return;
    }

    if (call.method.equals("close")) {
      if (beaconManager != null && beaconScanner != null) {
        beaconScanner.stopRanging();
        beaconScanner.stopMonitoring();
        if (beaconManager.isBound(beaconScanner.beaconConsumer)) {
          beaconManager.unbind(beaconScanner.beaconConsumer);
        }
      }
      result.success(true);
      return;
    }

    if (call.method.equals("startBroadcast")) {
      if (beaconBroadcast == null) {
        result.error("Beacon", "plugin not attached to an engine", null);
        return;
      }
      beaconBroadcast.startBroadcast(call.arguments, result);
      return;
    }

    if (call.method.equals("stopBroadcast")) {
      if (beaconBroadcast == null) {
        result.error("Beacon", "plugin not attached to an engine", null);
        return;
      }
      beaconBroadcast.stopBroadcast(result);
      return;
    }

    if (call.method.equals("isBroadcasting")) {
      if (beaconBroadcast == null) {
        result.error("Beacon", "plugin not attached to an engine", null);
        return;
      }
      beaconBroadcast.isBroadcasting(result);
      return;
    }

    if (call.method.equals("isBroadcastSupported")) {
      if (platform == null) {
        result.error("Beacon", "plugin not attached to an engine", null);
        return;
      }
      result.success(platform.isBroadcastSupported());
      return;
    }

    result.notImplemented();
  }

  /** Fail closed to legacy ownership unless a validated, enabled, unexpired remote flag exists. */
  private boolean nativeGattOwnsScanner() {
    if (applicationContext == null) return false;
    android.content.SharedPreferences prefs = applicationContext.getSharedPreferences(
        "ble_gatt_worker_flags", Context.MODE_PRIVATE);
    return prefs.getBoolean("remote_present", false)
        && prefs.getBoolean("remote_validated", false)
        && prefs.getBoolean("remote_enabled", false)
        && prefs.getLong("remote_expires_epoch_ms", 0L) > System.currentTimeMillis();
  }

  // ─── MethodChannel 인자 파싱 헬퍼 (언박싱 NPE 방지) ──────────────────────
  private static Integer argumentAsInt(MethodCall call, String key) {
    Object value = call.argument(key);
    return (value instanceof Number) ? ((Number) value).intValue() : null;
  }

  private static Boolean argumentAsBool(MethodCall call, String key) {
    Object value = call.argument(key);
    return (value instanceof Boolean) ? (Boolean) value : null;
  }

  private boolean updateScanPeriodsQuietly() {
    try {
      beaconManager.updateScanPeriods();
      return true;
    } catch (RemoteException e) {
      Log.w(TAG, "updateScanPeriods failed: " + e);
      return false;
    }
  }

  /**
   * 자체 포그라운드 서비스로 상주 스캔을 하는 앱에서는 반드시 false 여야 한다.
   * true 로 두면 AltBeacon 이 스캔을 JobScheduler(ScanJob) 에 위임하고,
   * 백그라운드 최소 주기(약 15분)에 묶인다.
   *
   * AltBeacon 은 이미 바인딩된 뒤의 변경을 거부할 수 있으므로 실패를 치명적으로
   * 다루지 않는다 — 바인딩 전에 호출하는 것이 정상 경로다.
   */
  boolean setEnableScheduledScanJobsQuietly(boolean enabled) {
    if (beaconManager == null) {
      return false;
    }
    try {
      beaconManager.setEnableScheduledScanJobs(enabled);
      Log.d(TAG, "setEnableScheduledScanJobs = " + enabled);
      return true;
    } catch (Exception e) {
      Log.w(TAG, "setEnableScheduledScanJobs failed (already bound?): " + e);
      return false;
    }
  }

  private void initializeAndCheck(Result result) {
    if (platform == null) {
      if (result != null) {
        result.error("Beacon", "plugin not attached to an engine", null);
      }
      return;
    }

    if (platform.checkLocationServicesPermission()
        && platform.checkBluetoothIfEnabled()
        && platform.checkLocationServicesIfEnabled()) {
      if (result != null) {
        result.success(true);
        return;
      }
    }

    flutterResult = result;

    // 백그라운드에서는 대화상자/설정 화면을 띄울 수 없으므로, 사유를 그대로 돌려준다.
    if (!platform.hasActivity()) {
      if (result != null) {
        this.flutterResult = null;
        result.error("Beacon", "requirements not met and no foreground activity available", null);
      }
      return;
    }

    if (!platform.checkBluetoothIfEnabled()) {
      platform.openBluetoothSettings();
      return;
    }

    if (!platform.checkLocationServicesPermission()) {
      platform.requestAuthorization();
      return;
    }

    if (!platform.checkLocationServicesIfEnabled()) {
      platform.openLocationSettings();
      return;
    }

    if (beaconManager != null && !beaconManager.isBound(beaconScanner.beaconConsumer)) {
      if (result != null) {
        this.flutterResult = result;
      }

      beaconManager.bind(beaconScanner.beaconConsumer);
      return;
    }

    if (result != null) {
      result.success(true);
    }
  }

  private final EventChannel.StreamHandler locationAuthorizationStatusStreamHandler = new EventChannel.StreamHandler() {
    @Override
    public void onListen(Object arguments, EventChannel.EventSink events) {
      eventSinkLocationAuthorizationStatus = events;
    }

    @Override
    public void onCancel(Object arguments) {
      eventSinkLocationAuthorizationStatus = null;
    }
  };

  // region ACTIVITY CALLBACK
  @Override
  public boolean onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
    if (requestCode != REQUEST_CODE_LOCATION) {
      return false;
    }

    boolean locationServiceAllowed = false;
    if (permissions.length > 0 && grantResults.length > 0) {
      String permission = permissions[0];
      if (platform != null && !platform.shouldShowRequestPermissionRationale(permission)) {
        int grantResult = grantResults[0];
        if (grantResult == PackageManager.PERMISSION_GRANTED) {
          //allowed
          locationServiceAllowed = true;
        }
        if (eventSinkLocationAuthorizationStatus != null) {
          // shouldShowRequestPermissionRationale = false, so if access wasn't granted, the user clicked DENY and checked DON'T SHOW AGAIN
          eventSinkLocationAuthorizationStatus.success(locationServiceAllowed ? "ALLOWED" : "DENIED");
        }
      }
      else {
        // shouldShowRequestPermissionRationale = true, so the user has clicked DENY but not DON'T SHOW AGAIN, we can possibly prompt again
        if (eventSinkLocationAuthorizationStatus != null) {
          eventSinkLocationAuthorizationStatus.success("NOT_DETERMINED");
        }
      }
    }
    else {
      // Permission request was cancelled (another requestPermission active, other interruptions), we can possibly prompt again
      if (eventSinkLocationAuthorizationStatus != null) {
        eventSinkLocationAuthorizationStatus.success("NOT_DETERMINED");
      }
    }

    if (flutterResult != null) {
      if (locationServiceAllowed) {
        flutterResult.success(true);
      } else {
        flutterResult.error("Beacon", "location services not allowed", null);
      }
      this.flutterResult = null;
    }

    return locationServiceAllowed;
  }

  @Override
  public boolean onActivityResult(int requestCode, int resultCode, Intent intent) {
    boolean bluetoothEnabled = requestCode == REQUEST_CODE_BLUETOOTH && resultCode == Activity.RESULT_OK;

    if (bluetoothEnabled) {
      if (platform != null && !platform.checkLocationServicesPermission()) {
        platform.requestAuthorization();
      } else {
        if (flutterResultBluetooth != null) {
          flutterResultBluetooth.success(true);
          flutterResultBluetooth = null;
        } else if (flutterResult != null) {
          flutterResult.success(true);
          flutterResult = null;
        }
      }
    } else {
      if (flutterResultBluetooth != null) {
        flutterResultBluetooth.error("Beacon", "bluetooth disabled", null);
        flutterResultBluetooth = null;
      } else if (flutterResult != null) {
        flutterResult.error("Beacon", "bluetooth disabled", null);
        flutterResult = null;
      }
    }

    return bluetoothEnabled;
  }
  // endregion
}
