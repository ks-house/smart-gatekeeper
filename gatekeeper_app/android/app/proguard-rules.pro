# -------------------------------------------------------------------------
# AltBeacon & Flutter Beacon ProGuard/R8 Rules
# -------------------------------------------------------------------------

# 1. AltBeacon Library 보존
# 비콘 파싱(BeaconParser), 백그라운드 프로세싱(AsyncTask/ScanDataProcessor) 등
# R8에 의해 구조가 변경되거나 멤버가 날아가는 것을 방지합니다.
-keep class org.altbeacon.beacon.** { *; }
-keep interface org.altbeacon.beacon.** { *; }
-dontwarn org.altbeacon.beacon.**

# 2. Flutter Beacon (Local 플러그인) 보존
# MethodChannel 통신 및 콜백을 담당하는 플러그인 클래스들이
# 축소(Shrink)되어 MethodNotFound 에러가 발생하는 것을 방지합니다.
-keep class com.flutterbeacon.** { *; }
-keep class com.alannmaulana.flutterbeacon.** { *; }
-dontwarn com.flutterbeacon.**
-dontwarn com.alannmaulana.flutterbeacon.**

# 3. AsyncTask 방어적 보존 (안전망)
# 라이브러리 내부의 AsyncTask 오버라이드 메서드들이 R8의 인라이닝(Inlining) 
# 최적화에 의해 무효화되는 것을 방지합니다.
-keepclassmembers class * extends android.os.AsyncTask {
    protected <methods>;
}
