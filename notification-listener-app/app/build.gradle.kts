plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

fun envOrDotenv(key: String): String {
    System.getenv(key)?.let { if (it.isNotBlank()) return it }
    val dotenv = rootProject.file("../.env")
    if (dotenv.exists()) {
        for (line in dotenv.readLines()) {
            val trimmed = line.trim()
            if (trimmed.isEmpty() || trimmed.startsWith("#") || !trimmed.contains("=")) continue
            val (k, v) = trimmed.split("=", limit = 2)
            if (k.trim() == key) return v.trim().trim('"', '\'')
        }
    }
    return ""
}

fun String.toKotlinStringLiteral(): String = "\"" + replace("\\", "\\\\").replace("\"", "\\\"") + "\""

val defaultServerUrl = envOrDotenv("BACKEND_URL")
val defaultApiKey = envOrDotenv("ADB_AUTOMATION_API_KEY")

android {
    namespace = "com.inteldesk.notiflistener"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.inteldesk.notiflistener"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        buildConfigField("String", "DEFAULT_SERVER_URL", defaultServerUrl.toKotlinStringLiteral())
        buildConfigField("String", "DEFAULT_API_KEY", defaultApiKey.toKotlinStringLiteral())
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.6.1")
}
