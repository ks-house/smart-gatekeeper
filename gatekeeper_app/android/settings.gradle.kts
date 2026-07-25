pluginManagement {
    val flutterSdkPath =
        run {
            val properties = java.util.Properties()
            val localPropertiesFile = file("local.properties")
            if (localPropertiesFile.exists()) {
                localPropertiesFile.inputStream().use { properties.load(it) }
            }
            val sdkPath = properties.getProperty("flutter.sdk") 
                ?: System.getenv("FLUTTER_ROOT") 
                ?: System.getenv("FLUTTER_HOME")
            require(sdkPath != null) { "flutter.sdk not set in local.properties and FLUTTER_ROOT not set" }
            sdkPath
        }


    includeBuild("$flutterSdkPath/packages/flutter_tools/gradle")

    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

plugins {
    id("dev.flutter.flutter-plugin-loader") version "1.0.0"
    id("com.android.application") version "8.6.0" apply false
    id("org.jetbrains.kotlin.android") version "1.9.22" apply false
}



include(":app")
