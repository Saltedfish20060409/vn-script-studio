plugins {
    id("vnss.android.feature")
}

android {
    namespace = "com.vnss.feature.settings"
}

dependencies {
    implementation(libs.androidx.browser)
    implementation(libs.androidx.activity.compose)
}
