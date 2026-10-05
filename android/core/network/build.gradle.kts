plugins {
    id("vnss.android.library")
    id("vnss.android.hilt")
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.vnss.core.network"

    sourceSets {
        // 后端 API 契约夹具（shared/test-fixtures）作为单测资源读取，与后端 test_android_contract.py 共用同一份。
        getByName("test").resources.srcDir("../../../shared/test-fixtures")
    }
}

dependencies {
    api(project(":core:model"))
    api(project(":core:common"))

    api(libs.kotlinx.serialization.json)
    api(libs.retrofit)
    api(libs.retrofit.kotlinx.serialization)
    api(libs.okhttp)
    api(libs.okhttp.sse)
    implementation(libs.okhttp.logging)

    testImplementation(libs.okhttp.mockwebserver)
}
