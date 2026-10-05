package com.vnss.studio

import androidx.compose.runtime.Composable
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.vnss.feature.agent.AgentRoute
import com.vnss.feature.collab.CollabRoute
import com.vnss.feature.editor.ARG_CHAPTER_ID
import com.vnss.feature.editor.ConflictRoute
import com.vnss.feature.editor.EditorRoute
import com.vnss.feature.ledger.LedgerRoute
import com.vnss.feature.projects.ARG_PROJECT_ID
import com.vnss.feature.projects.ChapterListRoute
import com.vnss.feature.projects.ProjectListRoute
import com.vnss.feature.settings.SettingsRoute

/** 路由表。参数一律走路径段，ViewModel 通过 SavedStateHandle 取（id 均为 UUID / 短 id，不含 `/`）。 */
object Routes {
    const val PROJECTS = "projects"
    const val PROJECT = "project/{$ARG_PROJECT_ID}"
    const val CHAPTER = "chapter/{$ARG_CHAPTER_ID}"
    const val CONFLICT = "conflict/{$ARG_CHAPTER_ID}"
    // 三个页面的参数名都是 "projectId"（各 feature 各自声明了同值常量，这里统一用 projects 的）
    const val AGENT = "agent/{$ARG_PROJECT_ID}"
    const val LEDGER = "ledger/{$ARG_PROJECT_ID}"
    const val COLLAB = "collab/{$ARG_PROJECT_ID}"
    const val SETTINGS = "settings"
    fun collab(projectId: String) = "collab/$projectId"
    fun agent(projectId: String) = "agent/$projectId"
    fun ledger(projectId: String) = "ledger/$projectId"
    fun project(id: String) = "project/$id"
    fun chapter(id: String) = "chapter/$id"
    fun conflict(id: String) = "conflict/$id"
}

@Composable
fun AppNavHost() {
    val nav = rememberNavController()
    NavHost(navController = nav, startDestination = Routes.PROJECTS) {
        composable(Routes.PROJECTS) {
            ProjectListRoute(
                onOpenProject = { nav.navigate(Routes.project(it)) },
                onOpenSettings = { nav.navigate(Routes.SETTINGS) },
            )
        }
        composable(
            Routes.PROJECT,
            arguments = listOf(navArgument(ARG_PROJECT_ID) { type = NavType.StringType }),
        ) {
            ChapterListRoute(
                onBack = { nav.popBackStack() },
                onOpenChapter = { _, chapterId -> nav.navigate(Routes.chapter(chapterId)) },
                onResolveConflict = { nav.navigate(Routes.conflict(it)) },
                onOpenAgent = { nav.navigate(Routes.agent(it)) },
                onOpenLedger = { nav.navigate(Routes.ledger(it)) },
                onOpenCollab = { nav.navigate(Routes.collab(it)) },
            )
        }
        composable(
            Routes.CHAPTER,
            arguments = listOf(navArgument(ARG_CHAPTER_ID) { type = NavType.StringType }),
        ) {
            EditorRoute(
                onBack = { nav.popBackStack() },
                onResolveConflict = { nav.navigate(Routes.conflict(it)) },
            )
        }
        composable(
            Routes.CONFLICT,
            arguments = listOf(navArgument(ARG_CHAPTER_ID) { type = NavType.StringType }),
        ) {
            ConflictRoute(onDone = { nav.popBackStack() })
        }
        composable(
            Routes.AGENT,
            arguments = listOf(navArgument(ARG_PROJECT_ID) { type = NavType.StringType }),
        ) {
            AgentRoute(onBack = { nav.popBackStack() })
        }
        composable(
            Routes.LEDGER,
            arguments = listOf(navArgument(ARG_PROJECT_ID) { type = NavType.StringType }),
        ) {
            LedgerRoute(onBack = { nav.popBackStack() })
        }
        composable(
            Routes.COLLAB,
            arguments = listOf(navArgument(ARG_PROJECT_ID) { type = NavType.StringType }),
        ) {
            CollabRoute(onBack = { nav.popBackStack() })
        }
        composable(Routes.SETTINGS) {
            SettingsRoute(onBack = { nav.popBackStack() })
        }
    }
}
