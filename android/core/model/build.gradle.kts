plugins {
    id("vnss.android.library")
}

android {
    namespace = "com.vnss.core.model"
}

dependencies {
    api(project(":core:common"))
    api(libs.kotlinx.coroutines.android)
}
