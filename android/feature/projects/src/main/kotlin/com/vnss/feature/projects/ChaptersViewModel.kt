package com.vnss.feature.projects

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vnss.core.common.Outcome
import com.vnss.core.model.ChapterSummary
import com.vnss.core.model.Project
import com.vnss.core.model.ProjectRepository
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

const val ARG_PROJECT_ID = "projectId"

data class ChaptersUiState(
    val refreshing: Boolean = false,
    val error: String? = null,
    val syncNote: String? = null,
)

@HiltViewModel
class ChaptersViewModel @Inject constructor(
    savedState: SavedStateHandle,
    private val projects: ProjectRepository,
    private val sync: SyncRepository,
) : ViewModel() {

    val projectId: String = checkNotNull(savedState[ARG_PROJECT_ID]) { "缺少 projectId 参数" }

    val project: StateFlow<Project?> = projects.observeProject(projectId)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val chapters: StateFlow<List<ChapterSummary>?> = projects.observeChapters(projectId)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    private val _state = MutableStateFlow(ChaptersUiState())
    val state: StateFlow<ChaptersUiState> = _state.asStateFlow()

    private val _opened = Channel<String>(Channel.BUFFERED)
    /** 新建章节后直接进入编辑。 */
    val opened = _opened.receiveAsFlow()

    init {
        refresh()
    }

    fun refresh() {
        if (_state.value.refreshing) return
        viewModelScope.launch {
            _state.update { it.copy(refreshing = true, error = null) }
            // 先推后拉：本地 DIRTY 章节不会被拉取覆盖（见 ProjectCache），但先推能让「待同步」尽快清零
            val report = sync.syncProject(projectId)
            val result = projects.refreshProject(projectId)
            _state.update {
                it.copy(
                    refreshing = false,
                    error = (result as? Outcome.Failure)?.error?.message,
                    syncNote = ProjectsViewModel.syncNote(report.pushed, report.merged, report.conflicts),
                )
            }
        }
    }

    fun createChapter(title: String) {
        viewModelScope.launch { _opened.send(projects.createChapter(projectId, title)) }
    }

    fun dismissError() = _state.update { it.copy(error = null) }
    fun dismissNote() = _state.update { it.copy(syncNote = null) }
}
