package com.vnss.feature.projects

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vnss.core.common.Outcome
import com.vnss.core.model.ProjectRepository
import com.vnss.core.model.ProjectSummary
import com.vnss.core.model.SyncRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ProjectsUiState(
    val refreshing: Boolean = false,
    val creating: Boolean = false,
    val error: String? = null,
    /** 最近一次同步的提示（成功合并 / 有冲突等）。 */
    val syncNote: String? = null,
)

@HiltViewModel
class ProjectsViewModel @Inject constructor(
    private val projects: ProjectRepository,
    private val sync: SyncRepository,
) : ViewModel() {

    /** null = 本地库还没读出来（显示加载），空列表 = 真的没有作品。 */
    val list: StateFlow<List<ProjectSummary>?> = projects.observeProjects()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val pendingCount: StateFlow<Int> = sync.observePendingCount()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), 0)

    private val _state = MutableStateFlow(ProjectsUiState())
    val state: StateFlow<ProjectsUiState> = _state.asStateFlow()

    private val _opened = Channel<String>(Channel.BUFFERED)
    /** 新建成功后跳转到该作品。 */
    val opened = _opened.receiveAsFlow()

    init {
        refresh()
    }

    fun refresh() {
        if (_state.value.refreshing) return
        viewModelScope.launch {
            _state.update { it.copy(refreshing = true, error = null) }
            // 先把本地待同步的推上去再拉列表：否则列表里的字数 / 状态是旧的
            val report = sync.syncAll()
            val result = projects.refreshProjects()
            _state.update {
                it.copy(
                    refreshing = false,
                    error = (result as? Outcome.Failure)?.error?.message,
                    syncNote = syncNote(report.pushed, report.merged, report.conflicts),
                )
            }
        }
    }

    fun createProject(title: String) {
        if (_state.value.creating) return
        viewModelScope.launch {
            _state.update { it.copy(creating = true, error = null) }
            when (val r = projects.createProject(title)) {
                is Outcome.Success -> {
                    _state.update { it.copy(creating = false) }
                    _opened.send(r.value)
                }
                is Outcome.Failure -> _state.update { it.copy(creating = false, error = r.error.message) }
            }
        }
    }

    fun dismissError() = _state.update { it.copy(error = null) }
    fun dismissNote() = _state.update { it.copy(syncNote = null) }

    companion object {
        fun syncNote(pushed: Int, merged: Int, conflicts: Int): String? = when {
            conflicts > 0 -> "有 $conflicts 章与网页端的修改冲突，请进入作品处理。"
            merged > 0 -> "已同步 $pushed 章，其中 $merged 章自动合并了网页端的修改。"
            pushed > 0 -> "已同步 $pushed 章。"
            else -> null
        }
    }
}
