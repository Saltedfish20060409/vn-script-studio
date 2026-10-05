import org.gradle.api.Plugin
import org.gradle.api.Project
import org.gradle.kotlin.dsl.dependencies

/**
 * feature 模块约定：Compose 库 + Hilt + 公共依赖。
 *
 * feature 只依赖 core:model / core:common / core:designsystem（接口与 UI 基建），
 * **不依赖** core:data / core:network / core:database 的实现——实现由 app 模块在 Hilt 图里装配。
 */
class AndroidFeatureConventionPlugin : Plugin<Project> {
    override fun apply(target: Project) {
        with(target) {
            pluginManager.apply("vnss.android.library.compose")
            pluginManager.apply("vnss.android.hilt")

            dependencies {
                add("implementation", project(":core:model"))
                add("implementation", project(":core:common"))
                add("implementation", project(":core:designsystem"))

                add("implementation", libs.lib("androidx-lifecycle-runtime-compose"))
                add("implementation", libs.lib("androidx-lifecycle-viewmodel-compose"))
                add("implementation", libs.lib("androidx-navigation-compose"))
                add("implementation", libs.lib("androidx-hilt-navigation-compose"))
                add("implementation", libs.lib("kotlinx-coroutines-android"))
            }
        }
    }
}
