package com.vnss.feature.ledger

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ScrollableTabRow
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vnss.core.designsystem.EmptyState
import com.vnss.core.designsystem.ErrorBanner
import com.vnss.core.designsystem.LoadingBox
import com.vnss.core.model.ChapterDigest
import com.vnss.core.model.ChapterFacts
import com.vnss.core.model.CharacterState
import com.vnss.core.model.Foreshadow
import com.vnss.core.model.Ledger

private val TABS = listOf("章节摘要", "事实", "角色状态", "伏笔")

/**
 * 写作账本只读查看：服务端每次保存自动抽取，移动端不编辑。
 * 要核对、改写或导出请到网页端。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LedgerRoute(onBack: () -> Unit, viewModel: LedgerViewModel = hiltViewModel()) {
    val data by viewModel.data.collectAsStateWithLifecycle()
    val state by viewModel.state.collectAsStateWithLifecycle()
    var tab by remember { mutableIntStateOf(0) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("账本与摘要") },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回") }
                },
            )
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            state.error?.let {
                ErrorBanner(it, Modifier.padding(horizontal = 12.dp, vertical = 4.dp), onRetry = viewModel::refresh, onDismiss = viewModel::dismissError)
            }
            ScrollableTabRow(selectedTabIndex = tab, edgePadding = 8.dp) {
                TABS.forEachIndexed { i, name -> Tab(selected = tab == i, onClick = { tab = i }, text = { Text(name) }) }
            }
            PullToRefreshBox(
                isRefreshing = state.refreshing,
                onRefresh = viewModel::refresh,
                modifier = Modifier.fillMaxSize(),
            ) {
                val ledger = data
                when {
                    ledger == null -> LoadingBox()
                    else -> when (tab) {
                        0 -> DigestList(ledger.digests)
                        1 -> FactsList(ledger.chapterFacts)
                        2 -> StatesList(ledger.characterStates)
                        else -> ForeshadowList(ledger)
                    }
                }
            }
        }
    }
}

private val ListPadding = androidx.compose.foundation.layout.PaddingValues(16.dp)

@Composable
private fun EmptyTab(what: String) {
    // 可下拉的空态：LazyColumn 保证 PullToRefreshBox 能识别下拉手势
    LazyColumn(Modifier.fillMaxSize()) {
        item { EmptyState("还没有$what", hint = "保存章节后服务端会自动生成；下拉可刷新。") }
    }
}

@Composable
private fun DigestList(list: List<ChapterDigest>) {
    if (list.isEmpty()) return EmptyTab("章节摘要")
    LazyColumn(Modifier.fillMaxSize(), contentPadding = ListPadding, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        items(list) { d ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(d.title.ifBlank { "（无标题）" }, style = MaterialTheme.typography.titleSmall)
                    if (d.synopsis.isNotBlank()) Text(d.synopsis, style = MaterialTheme.typography.bodyMedium)
                    if (d.speakers.isNotEmpty()) Labeled("出场", d.speakers.joinToString("、"))
                    if (d.openHook.isNotBlank()) Labeled("开头钩子", d.openHook)
                    if (d.closeHook.isNotBlank()) Labeled("结尾钩子", d.closeHook)
                }
            }
        }
    }
}

@Composable
private fun FactsList(list: List<ChapterFacts>) {
    val shown = list.filter { it.facts.isNotEmpty() || it.keyQuotes.isNotEmpty() }
    if (shown.isEmpty()) return EmptyTab("事实记录")
    LazyColumn(Modifier.fillMaxSize(), contentPadding = ListPadding, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        items(shown) { f ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(f.title.ifBlank { "（无标题）" }, style = MaterialTheme.typography.titleSmall)
                    f.facts.forEach { Text("• $it", style = MaterialTheme.typography.bodyMedium) }
                    f.keyQuotes.forEach {
                        Text(
                            "“$it”",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun StatesList(list: List<CharacterState>) {
    if (list.isEmpty()) return EmptyTab("角色状态")
    // 按角色归并：同一个角色在各章的状态依次列出，便于看人物弧光
    val grouped = list.groupBy { it.characterName }.toList()
    LazyColumn(Modifier.fillMaxSize(), contentPadding = ListPadding, verticalArrangement = Arrangement.spacedBy(12.dp)) {
        items(grouped) { (name, states) ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(name, style = MaterialTheme.typography.titleSmall)
                    states.forEach { s ->
                        Column {
                            if (s.chapterTitle.isNotBlank()) {
                                Text(s.chapterTitle, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                            }
                            val parts = listOf("情绪" to s.emotion, "身体" to s.body, "关系" to s.relations).filter { it.second.isNotBlank() }
                            parts.forEach { (k, v) -> Labeled(k, v) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ForeshadowList(ledger: Ledger) {
    var filter by remember { mutableStateOf(ForeshadowFilter.OPEN) }
    val titles = remember(ledger) { ledger.digests.associate { it.chapterId to it.title } }
    val all = ledger.foreshadows
    val shown = when (filter) {
        ForeshadowFilter.ALL -> all
        ForeshadowFilter.OPEN -> all.filterNot { it.isPaid }
        ForeshadowFilter.PAID -> all.filter { it.isPaid }
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            ForeshadowFilter.entries.forEach {
                val count = when (it) {
                    ForeshadowFilter.ALL -> all.size
                    ForeshadowFilter.OPEN -> all.count { f -> !f.isPaid }
                    ForeshadowFilter.PAID -> all.count { f -> f.isPaid }
                }
                FilterChip(selected = filter == it, onClick = { filter = it }, label = { Text("${it.label} $count") })
            }
        }
        if (shown.isEmpty()) {
            EmptyTab(if (all.isEmpty()) "伏笔" else "${filter.label}的伏笔")
        } else {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = ListPadding, verticalArrangement = Arrangement.spacedBy(12.dp)) {
                items(shown) { f -> ForeshadowCard(f, titles) }
            }
        }
    }
}

@Composable
private fun ForeshadowCard(f: Foreshadow, titles: Map<String, String>) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    if (f.isPaid) "已回收" else "未回收",
                    style = MaterialTheme.typography.labelMedium,
                    color = if (f.isPaid) MaterialTheme.colorScheme.outline else MaterialTheme.colorScheme.tertiary,
                )
            }
            Text(f.hook, style = MaterialTheme.typography.bodyMedium)
            if (f.plantedChapter.isNotBlank()) Labeled("埋于", titles[f.plantedChapter] ?: f.plantedChapter)
            f.paidInChapter?.let { Labeled("回收于", titles[it] ?: it) }
            if (f.note.isNotBlank()) Labeled("备注", f.note)
        }
    }
}

@Composable
private fun Labeled(label: String, value: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f))
    }
}
