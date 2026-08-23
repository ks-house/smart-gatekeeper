import java.io.FileInputStream
import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

val keystoreProperties = Properties()
val keystorePropertiesFile = rootProject.file("key.properties")
if (keystorePropertiesFile.exists()) {
    keystoreProperties.load(FileInputStream(keystorePropertiesFile))
}
val unsignedCiRelease = System.getenv("SGK_UNSIGNED_CI_RELEASE") == "1"

android {
    namespace = "com.kshouse.gatekeeper_app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.kshouse.gatekeeper_app"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

signingConfigs {
    create("release") {
        val storeFilePath = keystoreProperties.getProperty("storeFile")
            if (storeFilePath != null && keystoreProperties.getProperty("storePassword") != null) {
                val storeFileCandidate = file(storeFilePath)
                val resolvedStoreFile = if (storeFileCandidate.exists()) storeFileCandidate else rootProject.file(storeFilePath)
                if (resolvedStoreFile.exists()) {
                    storeFile = resolvedStoreFile
                    storePassword = keystoreProperties.getProperty("storePassword")
                    keyAlias = keystoreProperties.getProperty("keyAlias")
                    keyPassword = keystoreProperties.getProperty("keyPassword")
                }
            }
        }
    }

    buildTypes {
        release {
            val releaseRequested = gradle.startParameter.taskNames.any {
                it.contains("release", ignoreCase = true)
            }
            val releaseKeyPath = keystoreProperties.getProperty("storeFile")
            val releaseKey = releaseKeyPath?.let { path ->
                val candidate = file(path)
                if (candidate.exists()) candidate else rootProject.file(path)
            }
            if (releaseRequested && !unsignedCiRelease &&
                (releaseKey == null || !releaseKey.exists() ||
                    keystoreProperties.getProperty("storePassword").isNullOrBlank() ||
                    keystoreProperties.getProperty("keyAlias").isNullOrBlank() ||
                    keystoreProperties.getProperty("keyPassword").isNullOrBlank())) {
                throw GradleException("Release signing is fail-closed: configure key.properties with a real release keystore; debug signing is forbidden.")
            }
            if (!unsignedCiRelease) {
                signingConfig = signingConfigs.getByName("release")
            }
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}

dependencies {
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.8.1")
    testImplementation("org.json:json:20240303")
}
