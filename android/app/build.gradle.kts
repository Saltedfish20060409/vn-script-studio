import java.util.Properties

plugins {
    id("vnss.android.application")
    alias(libs.plugins.kotlin.compose)
}

// 发布签名：keystore.properties 不入库（见 .gitignore）；缺失时 release 仍可构建（用 debug 签名，仅供内测）。
val keystoreProps = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

fun prop(name: String, fallback: String): String =
    (project.findProperty(name) as String?) ?: fallback

android {
    namespace = "com.vnss.studio"

    defaultConfig {
        applicationId = "com.vnss.studio"
        versionCode = 1
        versionName = "0.1.0"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    signingConfigs {
        if (keystoreProps.isNotEmpty()) {
            create("release") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
            buildConfigField("String", "DEFAULT_SERVER_URL", "\"${prop("vnss.debugServerUrl", "https://vnscriptstudio.cn")}\"")
            // 与 release 一致只走 HTTPS；本机调试 http 后端时临时改为 "true"
            manifestPlaceholders["usesCleartext"] = "false"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            buildConfigField("String", "DEFAULT_SERVER_URL", "\"${prop("vnss.releaseServerUrl", "https://vnscriptstudio.cn")}\"")
            manifestPlaceholders["usesCleartext"] = "false"
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    implementation(project(":core:common"))
    implementation(project(":core:model"))
    implementation(project(":core:network"))
    implementation(project(":core:database"))
    implementation(project(":core:datastore"))
    implementation(project(":core:data"))
    implementation(project(":core:designsystem"))

    implementation(project(":feature:auth"))
    implementation(project(":feature:projects"))
    implementation(project(":feature:editor"))
    implementation(project(":feature:agent"))
    implementation(project(":feature:ledger"))
    implementation(project(":feature:collab"))
    implementation(project(":feature:settings"))

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.ui.tooling.preview)
    debugImplementation(libs.androidx.compose.ui.tooling)

    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.hilt.navigation.compose)
    implementation(libs.androidx.hilt.work)
    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.androidx.browser)
    implementation(libs.kotlinx.coroutines.android)
    ksp(libs.androidx.hilt.compiler)

    testImplementation(libs.junit)
}
