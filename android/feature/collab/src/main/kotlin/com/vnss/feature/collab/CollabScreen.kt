package com.vnss.feature.collab

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SecondaryTabRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vnss.core.designsystem.EmptyState
import com.vnss.core.designsystem.ErrorBanner
import com.vnss.core.designsystem.InlineSpinner
import com.vnss.core.designsystem.LoadingBox
import com.vnss.core.model.ChapterLock
import com.vnss.core.model.ChapterSummary
import com.vnss.core.model.Comment
import com.vnss.core.model.Member

private val TABS = listOf("批注", "成员与编辑状态")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CollabRoute(onBack: () -> Unit, viewModel: CollabViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val chapters by viewModel.chapters.collectAsStateWithLifecycle()
    var tab by remember { mutableIntStateOf(0) }

    // 只在页面可见时订阅实时事件：切到后台就断开，不耗电也不占服务端连接
    LifecycleResumeEffect(Unit) {
        viewModel.startLive()
        onPauseOrDispose { viewModel.stopLive() }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("协作批注") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回") }
                },
                actions = {
                    if (state.live) Text("实时", Modifier.padding(end = 16.dp), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                },
            )
        },
        bottomBar = {
            if (tab == 0 && !state.loading) Composer(state, chapters, viewModel)
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            state.error?.let {
                ErrorBanner(it, Modifier.padding(horizontal = 12.dp, vertical = 4.dp), onRetry = viewModel::refresh, onDismiss = viewModel::dismissError)
            }
            SecondaryTabRow(selectedTabIndex = tab) {
                TABS.forEachIndexed { i, name -> Tab(selected = tab == i, onClick = { tab = i }, text = { Text(name) }) }
            }
            if (state.loading) {
                LoadingBox()
            } else {
                PullToRefreshBox(isRefreshing = false, onRefresh = viewModel::refresh, modifier = Modifier.fillMaxSize()) {
                    if (tab == 0) {
                        CommentsTab(state, chapters, viewModel)
                    } else {
                        PeopleTab(state.members, state.locks, chapters)
                    }
                }
            }
        }
    }
}

private fun titleOf(chapters: List<ChapterSummary>, id: String): String =
    chapters.firstOrNull { it.id == id }?.title?.ifBlank { null } ?: "（已删除的章节）"

/** ISO 时间戳 → 「2026-05-01 12:30」；解析不了就原样给。 */
private fun shortTime(iso: String): String = iso.take(16).replace('T', ' ')

// ---------------------------------------------------------------- 批注

@Composable
private fun CommentsTab(state: CollabUiState, chapters: List<ChapterSummary>, vm: CollabViewModel) {
    val visible = state.comments
        .filter { state.chapterFilter == null || it.chapterId == state.chapterFilter }
    val top = visible.filter { it.parentId == null }
        .filter { state.showResolved || !it.resolved }
        .sortedByDescending { it.createdAt }
    val replies = visible.filter { it.parentId != null }.groupBy { it.parentId }
    var filterMenu by remember { mutableStateOf(false) }

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                OutlinedButton(onClick = { filterMenu = true }) {
                    Text(state.chapterFilter?.let { titleOf(chapters, it) } ?: "全部章节", maxLines = 1)
                }
                DropdownMenu(expanded = filterMenu, onDismissRequest = { filterMenu = false }) {
                    DropdownMenuItem(text = { Text("全部章节") }, onClick = { vm.setChapterFilter(null); filterMenu = false })
                    chapters.forEach {
                        DropdownMenuItem(text = { Text(it.title.ifBlank { "（无标题）" }) }, onClick = { vm.setChapterFilter(it.id); filterMenu = false })
                    }
                }
            }
            FilterChip(selected = state.showResolved, onClick = { vm.setShowResolved(!state.showResolved) }, label = { Text("显示已解决") })
        }
        if (top.isEmpty()) {
            // LazyColumn 容器让 PullToRefreshBox 在空态也能下拉
            LazyColumn(Modifier.fillMaxSize()) {
                item { EmptyState("还没有批注", hint = "在下方选择章节写第一条；协作者的批注会实时出现。") }
            }
        } else {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                items(top) { c ->
                    CommentCard(c, chapters, replies[c.id].orEmpty().sortedBy { it.createdAt }, vm)
                }
            }
        }
    }
}

@Composable
private fun CommentCard(c: Comment, chapters: List<ChapterSummary>, replies: List<Comment>, vm: CollabViewModel) {
    Card(
        Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (c.resolved) MaterialTheme.colorScheme.surfaceVariant else MaterialTheme.colorScheme.surface,
        ),
    ) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(titleOf(chapters, c.chapterId), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
            CommentBody(c, vm)
            replies.forEach { r ->
                Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
                    Column(Modifier.padding(8.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) { CommentBody(r, vm, reply = true) }
                }
            }
            Row {
                TextButton(onClick = { vm.startReply(c) }) { Text("回复") }
                TextButton(onClick = { vm.toggleResolved(c) }) { Text(if (c.resolved) "重新打开" else "标记已解决") }
            }
        }
    }
}

@Composable
private fun CommentBody(c: Comment, vm: CollabViewModel, reply: Boolean = false) {
    var confirmDelete by remember { mutableStateOf(false) }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(c.username.ifBlank { "未知用户" }, style = MaterialTheme.typography.labelLarge)
        Text(shortTime(c.createdAt), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
        if (c.resolved && !reply) Text("已解决", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
        if (vm.myUserId != null && c.userId == vm.myUserId) {
            Text("删除", Modifier.clickable { confirmDelete = true }, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
        }
    }
    if (c.anchor.isNotBlank()) {
        Text("“${c.anchor}”", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    Text(c.text, style = MaterialTheme.typography.bodyMedium)
    if (confirmDelete) {
        androidx.compose.material3.AlertDialog(
            onDismissRequest = { confirmDelete = false },
            title = { Text("删除这条批注？") },
            confirmButton = { TextButton(onClick = { confirmDelete = false; vm.delete(c) }) { Text("删除") } },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("取消") } },
        )
    }
}

@Composable
private fun Composer(state: CollabUiState, chapters: List<ChapterSummary>, vm: CollabViewModel) {
    var menu by remember { mutableStateOf(false) }
    // 默认选中当前筛选的章节，否则第一章
    LaunchedEffect(chapters.size, state.chapterFilter) {
        if (state.composeChapterId == null || (state.chapterFilter != null && state.composeChapterId != state.chapterFilter)) {
            vm.setComposeChapter(state.chapterFilter ?: chapters.firstOrNull()?.id)
        }
    }
    Surface(tonalElevation = 3.dp) {
        Column(Modifier.imePadding().navigationBarsPadding().padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            val reply = state.replyTo
            if (reply != null) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("回复 ${reply.username}：${reply.text.take(30)}", Modifier.weight(1f), style = MaterialTheme.typography.labelMedium, maxLines = 1)
                    TextButton(onClick = { vm.startReply(null) }) { Text("取消") }
                }
            } else {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Column {
                        OutlinedButton(onClick = { menu = true }, enabled = chapters.isNotEmpty()) {
                            Text(state.composeChapterId?.let { titleOf(chapters, it) } ?: "选择章节", maxLines = 1)
                        }
                        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                            chapters.forEach {
                                DropdownMenuItem(text = { Text(it.title.ifBlank { "（无标题）" }) }, onClick = { vm.setComposeChapter(it.id); menu = false })
                            }
                        }
                    }
                    OutlinedTextField(
                        value = state.anchor,
                        onValueChange = vm::onAnchor,
                        modifier = Modifier.weight(1f),
                        singleLine = true,
                        placeholder = { Text("引用原文（可选）") },
                    )
                }
            }
            Row(verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = state.draft,
                    onValueChange = vm::onDraft,
                    modifier = Modifier.weight(1f),
                    placeholder = { Text(if (reply != null) "写回复…" else "写批注…") },
                    maxLines = 4,
                )
                Button(onClick = vm::post, enabled = state.draft.isNotBlank() && !state.posting) {
                    if (state.posting) InlineSpinner() else Text("发送")
                }
            }
        }
    }
}

// ---------------------------------------------------------------- 成员 / 编辑状态

@Composable
private fun PeopleTab(members: List<Member>, locks: List<ChapterLock>, chapters: List<ChapterSummary>) {
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { Text("正在编辑", style = MaterialTheme.typography.titleSmall) }
        if (locks.isEmpty()) {
            item { Text("现在没有人在编辑章节。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        } else {
            items(locks) { l ->
                Card(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp)) {
                        Text("${l.username.ifBlank { "有人" }} 正在编辑「${titleOf(chapters, l.chapterId)}」", style = MaterialTheme.typography.bodyMedium)
                        Text(
                            "锁到 ${shortTime(l.expiresAt)}。在此期间你保存这一章会被服务端拒绝，稿子会保留在手机上等它释放后自动重试。",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
        item { Text("成员", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 8.dp)) }
        items(members) { m ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(m.username.ifBlank { m.userId }, style = MaterialTheme.typography.bodyMedium)
                Text(roleLabel(m.role), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        item {
            Text(
                "邀请、改权限等成员管理请在网页端操作。",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
    }
}

private fun roleLabel(role: String) = when (role) {
    "owner" -> "所有者"
    "editor" -> "编辑"
    "viewer" -> "只读"
    else -> role
}
