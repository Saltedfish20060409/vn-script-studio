package com.vnss.feature.projects

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import com.vnss.core.designsystem.EmptyState
import com.vnss.core.designsystem.ErrorBanner
import com.vnss.core.designsystem.InfoBanner
import com.vnss.core.designsystem.LoadingBox
import com.vnss.core.designsystem.VnssCard
import com.vnss.core.model.ProjectSummary

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ProjectListRoute(
    onOpenProject: (String) -> Unit,
    onOpenSettings: () -> Unit,
    viewModel: ProjectsViewModel = hiltViewModel(),
) {
    val list by viewModel.list.collectAsStateWithLifecycle()
    val state by viewModel.state.collectAsStateWithLifecycle()
    val pending by viewModel.pendingCount.collectAsStateWithLifecycle()
    var showCreate by remember { mutableStateOf(false) }

    LaunchedEffect(viewModel) { viewModel.opened.collect(onOpenProject) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("我的作品")
                        if (pending > 0) {
                            Text(
                                "有 $pending 章待同步",
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.tertiary,
                            )
                        }
                    }
                },
                actions = {
                    IconButton(onClick = onOpenSettings) { Icon(Icons.Default.Settings, contentDescription = "设置") }
                },
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = { showCreate = true }) {
                Icon(Icons.Default.Add, contentDescription = "新建作品")
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
                when (val items = list) {
                    null -> LoadingBox()
                    else -> if (items.isEmpty()) {
                        EmptyState(
                            title = if (state.refreshing) "正在加载作品…" else "还没有作品",
                            hint = "下拉可刷新；也可以点右下角新建一部。",
                        )
                    } else {
                        ProjectList(items, onOpenProject)
                    }
                }
            }
        }
    }

    if (showCreate) {
        CreateTitleDialog(
            title = "新建作品",
            label = "作品名称",
            busy = state.creating,
            onDismiss = { showCreate = false },
            onConfirm = {
                viewModel.createProject(it)
                showCreate = false
            },
        )
    }
}

@Composable
private fun ProjectList(items: List<ProjectSummary>, onOpen: (String) -> Unit) {
    LazyColumn(
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        modifier = Modifier.fillMaxSize(),
    ) {
        items(items, key = { it.id }) { p ->
            VnssCard(onClick = { onOpen(p.id) }) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(p.title.ifBlank { "未命名作品" }, style = MaterialTheme.typography.titleMedium)
                    p.logline?.takeIf { it.isNotBlank() }?.let {
                        Text(
                            it,
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                        )
                    }
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("${p.chaptersCount} 章", style = MaterialTheme.typography.labelMedium)
                        p.updatedAt?.take(10)?.let {
                            Text(it, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        if (p.conflictChapters > 0) {
                            Text("${p.conflictChapters} 章冲突", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.error)
                        } else if (p.dirtyChapters > 0) {
                            Text("${p.dirtyChapters} 章待同步", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.tertiary)
                        }
                    }
                }
            }
        }
    }
}

/** 单行输入的确认对话框（新建作品 / 新建章节共用）。 */
@Composable
fun CreateTitleDialog(
    title: String,
    label: String,
    busy: Boolean,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
    initial: String = "",
    allowBlank: Boolean = false,
    confirmLabel: String = "创建",
) {
    var text by remember { mutableStateOf(initial) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                label = { Text(label) },
                singleLine = true,
                enabled = !busy,
            )
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(text) }, enabled = !busy && (allowBlank || text.isNotBlank())) { Text(confirmLabel) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
    )
}
