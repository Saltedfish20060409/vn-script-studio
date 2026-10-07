package com.vnss.feature.projects

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vnss.core.common.WordCount
import com.vnss.core.designsystem.EmptyState
import com.vnss.core.designsystem.ErrorBanner
import com.vnss.core.designsystem.InfoBanner
import com.vnss.core.designsystem.LoadingBox
import com.vnss.core.designsystem.SyncBadge
import com.vnss.core.designsystem.VnssCard
import com.vnss.core.model.ChapterSummary
import com.vnss.core.model.SyncState

/** 作品内页：章节列表 + 进入 Agent / 账本 / 协作的入口。 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChapterListRoute(
    onBack: () -> Unit,
    onOpenChapter: (projectId: String, chapterId: String) -> Unit,
    onResolveConflict: (chapterId: String) -> Unit,
    viewModel: ChaptersViewModel = hiltViewModel(),
) {
    val project by viewModel.project.collectAsStateWithLifecycle()
    val chapters by viewModel.chapters.collectAsStateWithLifecycle()
    val state by viewModel.state.collectAsStateWithLifecycle()
    var showCreate by remember { mutableStateOf(false) }
    val projectId = viewModel.projectId

    LaunchedEffect(viewModel) { viewModel.opened.collect { onOpenChapter(projectId, it) } }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(project?.title?.ifBlank { null } ?: "作品") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { showCreate = true }) {
                Icon(Icons.Default.Add, contentDescription = "新建章节")
            }
        },
    ) { padding ->
        PullToRefreshBox(
            isRefreshing = state.refreshing,
            onRefresh = viewModel::refresh,
            modifier = Modifier.padding(padding).fillMaxSize(),
        ) {
            Column(Modifier.fillMaxSize()) {
                state.error?.let {
                    ErrorBanner(it, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), onRetry = viewModel::refresh, onDismiss = viewModel::dismissError)
                }
                state.syncNote?.let {
                    InfoBanner(it, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), onDismiss = viewModel::dismissNote)
                }

                val volumeTitles = remember(project) { project?.volumes.orEmpty().associate { it.id to it.title } }
                when (val items = chapters) {
                    null -> LoadingBox()
                    else -> if (items.isEmpty()) {
                        EmptyState(
                            title = if (state.refreshing) "正在加载章节…" else "还没有章节",
                            hint = "点右下角新建一章，离线也可以写。",
                        )
                    } else {
                        LazyColumn(
                            contentPadding = PaddingValues(16.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                            modifier = Modifier.fillMaxSize(),
                        ) {
                            itemsIndexed(items, key = { _, c -> c.id }) { index, c ->
                                val prev = items.getOrNull(index - 1)
                                if (c.volumeId != null && c.volumeId != prev?.volumeId) {
                                    Text(
                                        volumeTitles[c.volumeId] ?: "分卷",
                                        style = MaterialTheme.typography.titleSmall,
                                        color = MaterialTheme.colorScheme.primary,
                                        modifier = Modifier.padding(top = if (index == 0) 0.dp else 8.dp),
                                    )
                                }
                                ChapterCard(
                                    c,
                                    onClick = {
                                        if (c.syncState == SyncState.CONFLICT) onResolveConflict(c.id)
                                        else onOpenChapter(projectId, c.id)
                                    },
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    if (showCreate) {
        CreateTitleDialog(
            title = "新建章节",
            label = "章节标题（可留空）",
            busy = false,
            allowBlank = true,
            onDismiss = { showCreate = false },
            onConfirm = {
                viewModel.createChapter(it)
                showCreate = false
            },
        )
    }
}

@Composable
private fun ChapterCard(c: ChapterSummary, onClick: () -> Unit) {
    VnssCard(onClick = onClick) {
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    c.title.ifBlank { "（无标题）" },
                    style = MaterialTheme.typography.titleSmall,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                )
                SyncBadge(c.syncState)
            }
            c.synopsis?.takeIf { it.isNotBlank() }?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Text(WordCount.format(c.words), style = MaterialTheme.typography.labelSmall)
                if (c.published) Text("已发布", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
            }
            c.syncError?.let {
                Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
            }
        }
    }
}
