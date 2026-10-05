package com.vnss.feature.editor

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SecondaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import com.vnss.core.common.Outcome
import com.vnss.core.common.WordCount
import com.vnss.core.designsystem.EmptyState
import com.vnss.core.designsystem.ErrorBanner
import com.vnss.core.designsystem.InlineSpinner
import com.vnss.core.designsystem.LoadingBox
import com.vnss.core.designsystem.ProseTextStyle
import com.vnss.core.model.ChapterConflict
import com.vnss.core.model.ConflictResolution
import com.vnss.core.model.SyncRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ConflictUiState(
    val loading: Boolean = true,
    val conflict: ChapterConflict? = null,
    val busy: Boolean = false,
    val error: String? = null,
    val done: Boolean = false,
)

@HiltViewModel
class ConflictViewModel @Inject constructor(
    savedState: SavedStateHandle,
    private val sync: SyncRepository,
) : ViewModel() {

    private val chapterId: String = checkNotNull(savedState[ARG_CHAPTER_ID]) { "缺少 chapterId 参数" }

    private val _state = MutableStateFlow(ConflictUiState())
    val state: StateFlow<ConflictUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            val c = sync.loadConflict(chapterId)
            // 取不到冲突（已被解决 / 章节没了）：直接视为完成，回到上一页
            _state.update { if (c == null) it.copy(loading = false, done = true) else it.copy(loading = false, conflict = c) }
        }
    }

    fun resolve(resolution: ConflictResolution) {
        if (_state.value.busy) return
        viewModelScope.launch {
            _state.update { it.copy(busy = true, error = null) }
            when (val r = sync.resolveConflict(chapterId, resolution)) {
                is Outcome.Success -> _state.update { it.copy(busy = false, done = true) }
                is Outcome.Failure -> _state.update { it.copy(busy = false, error = r.error.message) }
            }
        }
    }

    fun dismissError() = _state.update { it.copy(error = null) }
}

/**
 * 冲突裁决：同一章在手机和别处都被修改且无法自动合并。三份文本都摆出来，让用户明确选择，
 * 任何一种选择都不会静默丢内容（「保留两份」会把服务器版本另存为新章节）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConflictRoute(onDone: () -> Unit, viewModel: ConflictViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(state.done) { if (state.done) onDone() }
    var tab by remember { mutableIntStateOf(0) }
    var confirmServer by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("处理冲突") },
                navigationIcon = {
                    IconButton(onClick = onDone) { Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回") }
                },
            )
        },
    ) { padding ->
        val c = state.conflict
        Column(Modifier.padding(padding).fillMaxSize()) {
            when {
                state.loading -> LoadingBox()
                c == null -> EmptyState("没有需要处理的冲突")
                else -> {
                    Text(
                        "「${c.title.ifBlank { "无标题" }}」在手机和别处都被修改了，且改动位置重叠，无法自动合并。",
                        Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    state.error?.let { ErrorBanner(it, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), onDismiss = viewModel::dismissError) }

                    val tabs = listOf(
                        "我的（手机）" to c.local,
                        "服务器" to c.remote,
                        "共同祖先" to c.base,
                    )
                    SecondaryTabRow(selectedTabIndex = tab) {
                        tabs.forEachIndexed { i, (name, _) ->
                            Tab(selected = tab == i, onClick = { tab = i }, text = { Text(name) })
                        }
                    }
                    Text(
                        "${WordCount.count(tabs[tab].second)} 字",
                        Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 16.dp)) {
                        Text(
                            tabs[tab].second.ifEmpty { "（空）" },
                            style = ProseTextStyle,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }

                    Column(Modifier.fillMaxWidth().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = { viewModel.resolve(ConflictResolution.KEEP_BOTH) },
                            enabled = !state.busy,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            if (state.busy) InlineSpinner() else Text("两份都保留（推荐）")
                        }
                        Text(
                            "我的版本覆盖原章节，服务器版本另存为新章节「…（服务器版本）」，之后再手动整合。",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        OutlinedButton(
                            onClick = { viewModel.resolve(ConflictResolution.KEEP_MINE) },
                            enabled = !state.busy,
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("保留我的，覆盖服务器") }
                        OutlinedButton(
                            onClick = { confirmServer = true },
                            enabled = !state.busy,
                            modifier = Modifier.fillMaxWidth(),
                        ) { Text("采用服务器版本，丢弃我的修改") }
                    }
                }
            }
        }
    }

    if (confirmServer) {
        AlertDialog(
            onDismissRequest = { confirmServer = false },
            title = { Text("丢弃手机上的修改？") },
            text = { Text("这一章在手机上的未同步修改将被服务器版本替换，无法恢复。") },
            confirmButton = {
                TextButton(onClick = {
                    confirmServer = false
                    viewModel.resolve(ConflictResolution.USE_SERVER)
                }) { Text("丢弃并采用服务器版本") }
            },
            dismissButton = { TextButton(onClick = { confirmServer = false }) { Text("取消") } },
        )
    }
}
