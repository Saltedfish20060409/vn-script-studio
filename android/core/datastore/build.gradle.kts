plugins {
    id("vnss.android.library")
    id("vnss.android.hilt")
}

android {
    namespace = "com.vnss.core.datastore"
}

dependencies {
    api(project(":core:model"))
    implementation(project(":core:common"))
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.androidx.security.crypto)
    implementation(libs.kotlinx.coroutines.android)
}
