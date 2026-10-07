package com.vnss.feature.agent

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vnss.core.designsystem.ErrorBanner
import com.vnss.core.designsystem.InfoBanner
import com.vnss.core.designsystem.InlineSpinner
import com.vnss.core.designsystem.LoadingBox
import com.vnss.core.model.AgentRole
import com.vnss.core.model.AuthorLens

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgentRoute(onBack: () -> Unit, viewModel: AgentViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val listState = rememberLazyListState()

    // 新消息 / 新进度出现时滚到底；用户正在往上翻历史时（不在底部附近）不抢滚动
    LaunchedEffect(state.items.size, state.liveSteps.size, state.running) {
        val total = listState.layoutInfo.totalItemsCount
        val lastVisible = listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: -1
        if (total > 0 && lastVisible >= total - 3) listState.animateScrollToItem(total - 1)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(state.title, maxLines = 1) },
                navigationIcon = {
                    IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回") }
                },
                actions = {
                    TextButton(
                        onClick = { viewModel.showLenses(true) },
                        enabled = !state.running,
                    ) {
                        Text(
                            lensLabel(state.activeLensIds, state.lensCatalog),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                    TextButton(onClick = { viewModel.showConversations(true) }) { Text("对话") }
                },
            )
        },
        bottomBar = {
            InputBar(
                input = state.input,
                running = state.running,
                applyActions = state.applyActions,
                onInput = viewModel::onInput,
                onSend = viewModel::send,
                onStop = viewModel::stop,
                onApplyActions = viewModel::setApplyActions,
            )
        },
    ) { padding ->
        Box(Modifier.padding(padding).fillMaxSize()) {
            if (state.loading) {
                LoadingBox()
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize(),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(16.dp),
                ) {
                    if (state.items.isEmpty() && !state.running) {
                        item { Hint() }
                    }
                    itemsIndexed(state.items) { _, item -> Bubble(item) }
                    if (state.running) item { LiveProgress(state.liveSteps) }
                    item {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            state.notice?.let { InfoBanner(it, onDismiss = viewModel::dismissNotice) }
                            state.error?.let {
                                val canRetry = state.items.lastOrNull()?.message?.role == AgentRole.USER
                                ErrorBanner(
                                    it,
                                    onRetry = if (canRetry) viewModel::retry else null,
                                    onDismiss = viewModel::dismissError,
                                )
                            }
                            if (state.resumable && !state.running) {
                                OutlinedButton(onClick = viewModel::resume, modifier = Modifier.fillMaxWidth()) {
                                    Text("继续上次中断的运行")
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (state.showConversations) {
        ModalBottomSheet(onDismissRequest = { viewModel.showConversations(false) }) {
            Column(Modifier.navigationBarsPadding().padding(bottom = 16.dp)) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("历史对话", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                    Button(
                        onClick = {
                            viewModel.newConversation()
                            viewModel.showConversations(false)
                        },
                        enabled = !state.running,
                    ) { Text("新对话") }
                }
                val list = state.conversations
                when {
                    list == null -> Text("加载中…", Modifier.padding(20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    list.isEmpty() -> Text("还没有历史对话", Modifier.padding(20.dp), color = MaterialTheme.colorScheme.onSurfaceVariant)
                    else -> LazyColumn {
                        itemsIndexed(list) { i, c ->
                            Column(
                                Modifier
                                    .fillMaxWidth()
                                    .clickable(enabled = !state.running) { viewModel.openConversation(c.id) }
                                    .padding(horizontal = 20.dp, vertical = 12.dp),
                            ) {
                                Text(c.title, style = MaterialTheme.typography.bodyLarge, maxLines = 1)
                                Text(
                                    "${c.messageCount} 条消息",
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                            if (i < list.lastIndex) HorizontalDivider()
                        }
                    }
                }
            }
        }
    }

    if (state.showLenses) {
        LensSheet(
            catalog = state.lensCatalog,
            activeIds = state.activeLensIds,
            maxActive = state.maxActiveLenses,
            busy = state.lensBusy || state.running,
            onToggle = viewModel::toggleLens,
            onDismiss = { viewModel.showLenses(false) },
        )
    }
}

private fun lensLabel(activeIds: List<String>, catalog: List<AuthorLens>): String {
    if (activeIds.isEmpty()) return "作家眼光"
    val names = activeIds.map { id -> catalog.find { it.id == id }?.name ?: id }
    return when {
        names.size == 1 -> names[0]
        else -> "眼光×${names.size}"
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun LensSheet(
    catalog: List<AuthorLens>,
    activeIds: List<String>,
    maxActive: Int,
    busy: Boolean,
    onToggle: (String?) -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            Modifier
                .navigationBarsPadding()
                .verticalScroll(rememberScrollState())
                .padding(start = 20.dp, end = 20.dp, bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("作家眼光", style = MaterialTheme.typography.titleMedium)
            Text(
                "切换的是作家技法视角，不是扮演本人。默认用通用文学编辑；最多同时选 $maxActive 位。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                FilterChip(
                    selected = activeIds.isEmpty(),
                    onClick = { onToggle(null) },
                    enabled = !busy,
                    label = { Text("通用文学编辑") },
                )
                catalog.forEach { pack ->
                    FilterChip(
                        selected = pack.id in activeIds,
                        onClick = { onToggle(pack.id) },
                        enabled = !busy,
                        label = { Text(pack.name) },
                    )
                }
            }
            if (catalog.isEmpty() && busy) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    InlineSpinner()
                    Text("加载中…", style = MaterialTheme.typography.bodySmall)
                }
            } else if (catalog.isEmpty()) {
                Text("暂时拉不到作家目录，请检查网络后重开。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
            }
        }
    }
}

@Composable
private fun Hint() {
    Column(Modifier.fillMaxWidth().padding(top = 48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text("和 Agent 聊聊你的作品", style = MaterialTheme.typography.titleMedium)
        Text(
            "可以问人物设定、前后文是否矛盾、下一章怎么写。顶部可换「作家眼光」换技法视角。手机上的修改会先同步到服务端，Agent 读到的就是最新稿。",
            Modifier.padding(top = 8.dp),
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun Bubble(item: ChatItem) {
    val mine = item.message.role == AgentRole.USER
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = if (mine) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.surface,
            contentColor = if (mine) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSurface,
            modifier = Modifier.fillMaxWidth(if (mine) 0.85f else 0.95f),
            shadowElevation = 0.dp,
            tonalElevation = 0.dp,
        ) {
            Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                SelectionContainer {
                    Text(item.message.content, style = MaterialTheme.typography.bodyMedium)
                }
                if (item.applied) {
                    Text(
                        "已写入作品",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (mine) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.primary,
                    )
                }
                item.warnings.forEach {
                    Text("⚠ $it", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
                }
                if (item.steps.isNotEmpty()) StepsFold(item.steps)
            }
        }
    }
}

@Composable
private fun StepsFold(steps: List<String>) {
    var open by remember { mutableStateOf(false) }
    Text(
        if (open) "收起过程（${steps.size} 步）" else "查看过程（${steps.size} 步）",
        Modifier.clickable { open = !open },
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.primary,
    )
    if (open) {
        steps.forEach {
            Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun LiveProgress(steps: List<String>) {
    Surface(shape = RoundedCornerShape(16.dp), color = MaterialTheme.colorScheme.surfaceVariant, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                InlineSpinner()
                Text(if (steps.isEmpty()) "正在同步并连接 Agent…" else "Agent 正在工作…", style = MaterialTheme.typography.labelLarge)
            }
            steps.takeLast(6).forEach {
                Text(
                    it,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                )
            }
        }
    }
}

@Composable
private fun InputBar(
    input: String,
    running: Boolean,
    applyActions: Boolean,
    onInput: (String) -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
    onApplyActions: (Boolean) -> Unit,
) {
    Surface(tonalElevation = 3.dp) {
        // 边到边显示下底栏不会自动避让键盘与导航条；padding 放在 Surface 内侧，让底色铺满到屏幕边缘
        Column(Modifier.imePadding().navigationBarsPadding().padding(horizontal = 12.dp, vertical = 8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = applyActions, onCheckedChange = onApplyActions, enabled = !running)
                Column(Modifier.padding(start = 8.dp)) {
                    Text("允许 Agent 直接改稿", style = MaterialTheme.typography.labelLarge)
                    Text(
                        if (applyActions) "改动会写入作品并同步回手机" else "只给方案和建议，不动你的稿子",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = input,
                    onValueChange = onInput,
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("说点什么…") },
                    maxLines = 5,
                    enabled = !running,
                )
                if (running) {
                    OutlinedButton(onClick = onStop) { Text("停止") }
                } else {
                    Button(onClick = onSend, enabled = input.isNotBlank()) { Text("发送") }
                }
            }
        }
    }
}
