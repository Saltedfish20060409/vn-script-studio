package com.vnss.feature.collab

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vnss.core.common.Outcome
import com.vnss.core.model.AuthRepository
import com.vnss.core.model.ChapterLock
import com.vnss.core.model.ChapterSummary
import com.vnss.core.model.CollabEvent
import com.vnss.core.model.CollabRepository
import com.vnss.core.model.Comment
import com.vnss.core.model.Member
import com.vnss.core.model.ProjectRepository
import com.vnss.core.model.SessionState
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

const val ARG_PROJECT_ID = "projectId"

data class CollabUiState(
    val loading: Boolean = true,
    val comments: List<Comment> = emptyList(),
    val members: List<Member> = emptyList(),
    val locks: List<ChapterLock> = emptyList(),
    /** null = 全部章节。 */
    val chapterFilter: String? = null,
    val showResolved: Boolean = false,
    /** 正在回复的批注（null = 新建顶层批注）。 */
    val replyTo: Comment? = null,
    val composeChapterId: String? = null,
    val draft: String = "",
    val anchor: String = "",
    val posting: Boolean = false,
    val live: Boolean = false,
    val error: String? = null,
)

@HiltViewModel
class CollabViewModel @Inject constructor(
    savedState: SavedStateHandle,
    private val collab: CollabRepository,
    projects: ProjectRepository,
    auth: AuthRepository,
) : ViewModel() {

    val projectId: String = checkNotNull(savedState[ARG_PROJECT_ID]) { "缺少 projectId 参数" }

    val chapters: StateFlow<List<ChapterSummary>> = projects.observeChapters(projectId)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    /** 当前登录用户 id（用于只对自己的批注显示「删除」；服务端仍会再校验权限）。 */
    val myUserId: String? = (auth.session.value as? SessionState.SignedIn)?.user?.id

    private val _state = MutableStateFlow(CollabUiState())
    val state: StateFlow<CollabUiState> = _state.asStateFlow()

    private var liveJob: Job? = null

    init {
        viewModelScope.launch { refreshAll(initial = true) }
    }

    // ------------------------------------------------------------ 数据

    /** [report]：是否把失败显示出来。事件触发的静默刷新不弹错（断网时会很吵）。 */
    private suspend fun refreshAll(initial: Boolean = false, report: Boolean = initial) {
        if (initial) _state.update { it.copy(loading = true) }
        val errors = mutableListOf<String>()
        when (val r = collab.comments(projectId, null)) {
            is Outcome.Success -> _state.update { it.copy(comments = r.value) }
            is Outcome.Failure -> errors += r.error.message
        }
        when (val r = collab.members(projectId)) {
            is Outcome.Success -> _state.update { it.copy(members = r.value) }
            is Outcome.Failure -> errors += r.error.message
        }
        when (val r = collab.locks(projectId)) {
            is Outcome.Success -> _state.update { it.copy(locks = r.value) }
            is Outcome.Failure -> errors += r.error.message
        }
        // 三个接口常因同一原因（断网）一起失败，只显示第一条
        _state.update { it.copy(loading = false, error = if (report) errors.firstOrNull() else it.error) }
    }

    fun refresh() {
        viewModelScope.launch { refreshAll(initial = false, report = true) }
    }

    // ------------------------------------------------------------ 实时事件（仅界面可见时订阅）

    fun startLive() {
        if (liveJob?.isActive == true) return
        liveJob = viewModelScope.launch {
            _state.update { it.copy(live = true) }
            try {
                collab.events(projectId).collect { event ->
                    when (event) {
                        is CollabEvent.CommentChanged -> silentComments()
                        is CollabEvent.LockChanged -> silentLocks()
                        is CollabEvent.MemberChanged -> silentMembers()
                        // 重连后：断线期间可能漏事件，整体刷新一次
                        CollabEvent.Other -> refreshAll()
                    }
                }
            } catch (e: CancellationException) {
                throw e
            } catch (_: Throwable) {
                // 无权限 / 登录失效等重试无意义的错误：停止实时更新，手动刷新仍可用
            } finally {
                _state.update { it.copy(live = false) }
            }
        }
    }

    fun stopLive() {
        liveJob?.cancel()
        liveJob = null
    }

    private suspend fun silentComments() {
        (collab.comments(projectId, null) as? Outcome.Success)?.let { r -> _state.update { it.copy(comments = r.value) } }
    }

    private suspend fun silentLocks() {
        (collab.locks(projectId) as? Outcome.Success)?.let { r -> _state.update { it.copy(locks = r.value) } }
    }

    private suspend fun silentMembers() {
        (collab.members(projectId) as? Outcome.Success)?.let { r -> _state.update { it.copy(members = r.value) } }
    }

    // ------------------------------------------------------------ 交互

    fun setChapterFilter(chapterId: String?) = _state.update { it.copy(chapterFilter = chapterId) }
    fun setShowResolved(show: Boolean) = _state.update { it.copy(showResolved = show) }
    fun onDraft(text: String) = _state.update { it.copy(draft = text) }
    fun onAnchor(text: String) = _state.update { it.copy(anchor = text) }
    fun setComposeChapter(id: String?) = _state.update { it.copy(composeChapterId = id) }
    fun startReply(comment: Comment?) = _state.update { it.copy(replyTo = comment) }
    fun dismissError() = _state.update { it.copy(error = null) }

    fun post() {
        val s = _state.value
        val text = s.draft.trim()
        if (s.posting || text.isEmpty()) return
        val chapterId = s.replyTo?.chapterId ?: s.composeChapterId
        if (chapterId == null) {
            _state.update { it.copy(error = "请先选择要批注的章节") }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(posting = true, error = null) }
            // 回复继承父批注的章节；顶层批注才带锚点原文
            val anchor = if (s.replyTo == null) s.anchor else ""
            when (val r = collab.addComment(projectId, chapterId, text, anchor, s.replyTo?.id)) {
                is Outcome.Success -> _state.update {
                    it.copy(
                        posting = false,
                        draft = "",
                        anchor = "",
                        replyTo = null,
                        comments = it.comments.filterNot { c -> c.id == r.value.id } + r.value,
                    )
                }
                is Outcome.Failure -> _state.update { it.copy(posting = false, error = r.error.message) }
            }
        }
    }

    fun toggleResolved(comment: Comment) {
        viewModelScope.launch {
            when (val r = collab.setResolved(projectId, comment.id, !comment.resolved)) {
                is Outcome.Success -> _state.update { s -> s.copy(comments = s.comments.map { if (it.id == r.value.id) r.value else it }) }
                is Outcome.Failure -> _state.update { it.copy(error = r.error.message) }
            }
        }
    }

    fun delete(comment: Comment) {
        viewModelScope.launch {
            when (val r = collab.deleteComment(projectId, comment.id)) {
                // 只删这一条；它的回复是否被服务端级联删除不在这里猜，重新拉一次列表以服务端为准
                is Outcome.Success -> {
                    _state.update { s -> s.copy(comments = s.comments.filterNot { it.id == comment.id }) }
                    silentComments()
                }
                is Outcome.Failure -> _state.update { it.copy(error = r.error.message) }
            }
        }
    }
}
