plugins {
    id("vnss.android.library")
}

android {
    namespace = "com.vnss.core.common"
}

dependencies {
    api(libs.kotlinx.coroutines.android)
}
