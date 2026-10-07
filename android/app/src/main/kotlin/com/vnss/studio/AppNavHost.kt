package com.vnss.studio

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
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
    const val SETTINGS = "settings"
    fun project(id: String) = "project/$id"
    fun chapter(id: String) = "chapter/$id"
    fun conflict(id: String) = "conflict/$id"
}

private enum class ProjectTab(val label: String, val icon: ImageVector) {
    Chapters("章节", Icons.Default.Edit),
    Agent("Agent", Icons.Default.Send),
    Ledger("账本", Icons.Default.Info),
    Collab("协作", Icons.Default.Person),
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
            ProjectShell(
                onLeaveProject = { nav.popBackStack() },
                onOpenChapter = { nav.navigate(Routes.chapter(it)) },
                onResolveConflict = { nav.navigate(Routes.conflict(it)) },
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
        composable(Routes.SETTINGS) {
            SettingsRoute(onBack = { nav.popBackStack() })
        }
    }
}

@Composable
private fun ProjectShell(
    onLeaveProject: () -> Unit,
    onOpenChapter: (chapterId: String) -> Unit,
    onResolveConflict: (chapterId: String) -> Unit,
) {
    var tab by rememberSaveable { mutableStateOf(ProjectTab.Chapters.name) }
    val current = ProjectTab.entries.firstOrNull { it.name == tab } ?: ProjectTab.Chapters

    Scaffold(
        bottomBar = {
            NavigationBar {
                ProjectTab.entries.forEach { item ->
                    NavigationBarItem(
                        selected = item == current,
                        onClick = { tab = item.name },
                        icon = { Icon(item.icon, contentDescription = item.label) },
                        label = { Text(item.label) },
                    )
                }
            }
        },
    ) { padding ->
        Box(Modifier.padding(padding)) {
            when (current) {
                ProjectTab.Chapters -> ChapterListRoute(
                    onBack = onLeaveProject,
                    onOpenChapter = { _, chapterId -> onOpenChapter(chapterId) },
                    onResolveConflict = onResolveConflict,
                )
                ProjectTab.Agent -> AgentRoute(onBack = onLeaveProject)
                ProjectTab.Ledger -> LedgerRoute(onBack = onLeaveProject)
                ProjectTab.Collab -> CollabRoute(onBack = onLeaveProject)
            }
        }
    }
}
