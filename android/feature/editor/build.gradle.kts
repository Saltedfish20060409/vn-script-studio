plugins {
    id("vnss.android.feature")
    alias(libs.plugins.kotlin.serialization)
}

android {
    namespace = "com.vnss.feature.editor"

    sourceSets {
        // 跨端一致性夹具（shared/test-fixtures）直接作为单测资源读取，不复制一份
        getByName("test").resources.srcDir("../../../shared/test-fixtures")
    }
}

dependencies {
    testImplementation(libs.kotlinx.serialization.json)
}
