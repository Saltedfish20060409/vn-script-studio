plugins {
    id("vnss.android.library")
    id("vnss.android.hilt")
    id("vnss.android.room")
}

android {
    namespace = "com.vnss.core.database"
}

dependencies {
    api(project(":core:common"))
    api(libs.androidx.room.runtime)
    api(libs.androidx.room.ktx)
    implementation(libs.kotlinx.coroutines.android)
}
