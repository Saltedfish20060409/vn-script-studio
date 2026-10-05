plugins {
    id("vnss.android.library.compose")
}

android {
    namespace = "com.vnss.core.designsystem"
}

dependencies {
    api(project(":core:model"))
    implementation(libs.androidx.core.ktx)
}
