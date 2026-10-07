plugins {
    id("vnss.android.library")
    id("vnss.android.hilt")
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.vnss.core.data"
}

dependencies {
    api(project(":core:model"))
    implementation(project(":core:common"))
    implementation(project(":core:network"))
    implementation(project(":core:database"))
    implementation(project(":core:datastore"))

    implementation(libs.kotlinx.serialization.json)
    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.androidx.hilt.work)
    implementation(libs.androidx.core.ktx)
    ksp(libs.androidx.hilt.compiler)
}