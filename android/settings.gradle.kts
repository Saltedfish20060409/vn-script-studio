pluginManagement {
    includeBuild("build-logic")
    repositories {
        // CI（GitHub Actions）优先走官方源；国内本机再回落到阿里云镜像。
        google()
        mavenCentral()
        gradlePluginPortal()
        maven("https://maven.aliyun.com/repository/google")
        maven("https://maven.aliyun.com/repository/public")
    }
}
// 不启用 foojay-resolver：国内镜像常拉不到该插件；本机用 Android Studio / JAVA_HOME 的 JDK 即可。

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
        maven("https://maven.aliyun.com/repository/google")
        maven("https://maven.aliyun.com/repository/public")
    }
}

rootProject.name = "vnss-android"

include(":app")

include(":core:common")
include(":core:model")
include(":core:network")
include(":core:database")
include(":core:datastore")
include(":core:data")
include(":core:designsystem")

include(":feature:auth")
include(":feature:projects")
include(":feature:editor")
include(":feature:agent")
include(":feature:ledger")
include(":feature:collab")
include(":feature:settings")
