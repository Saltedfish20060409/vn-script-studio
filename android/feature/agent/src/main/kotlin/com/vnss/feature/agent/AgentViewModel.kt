package com.vnss.feature.agent

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vnss.core.common.Outcome
import com.vnss.core.model.AgentConversationSummary
import com.vnss.core.model.AgentEvent
import com.vnss.core.model.AgentMessage
import com.vnss.core.model.AgentRepository
import com.vnss.core.model.AgentRole
import com.vnss.core.model.AgentRunRequest
import com.vnss.core.model.AuthorLens
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

const val ARG_PROJECT_ID = "projectId"

/** 一条聊天气泡。步骤 / 警告只在本机展示，不写回会话（会话里只存 role + content）。 */
data class ChatItem(
    val message: AgentMessage,
    val steps: List<String> = emptyList(),
    val warnings: List<String> = emptyList(),
    val applied: Boolean = false,
)

data class AgentUiState(
    val loading: Boolean = true,
    val conversationId: String? = null,
    val title: String = "新对话",
    val items: List<ChatItem> = emptyList(),
    val input: String = "",
    /** 允许 Agent 直接把改动写进作品。默认关：先给方案，作者看过再说。 */
    val applyActions: Boolean = false,
    val running: Boolean = false,
    /** 运行中的进度行（最新在最后）。 */
    val liveSteps: List<String> = emptyList(),
    val resumable: Boolean = false,
    val error: String? = null,
    /** 本轮运行让服务端改了稿子（提示作者回章节列表查看）。 */
    val notice: String? = null,
    val conversations: List<AgentConversationSummary>? = null,
    val showConversations: Boolean = false,
    /** 作家眼光目录；空表示还没拉到。 */
    val lensCatalog: List<AuthorLens> = emptyList(),
    val activeLensIds: List<String> = emptyList(),
    val maxActiveLenses: Int = 3,
    val showLenses: Boolean = false,
    val lensBusy: Boolean = false,
)

@HiltViewModel
class AgentViewModel @Inject constructor(
    savedState: SavedStateHandle,
    private val agent: AgentRepository,
) : ViewModel() {

    val projectId: String = checkNotNull(savedState[ARG_PROJECT_ID]) { "缺少 projectId 参数" }

    private val _state = MutableStateFlow(AgentUiState())
    val state: StateFlow<AgentUiState> = _state.asStateFlow()

    private var runJob: Job? = null

    init {
        viewModelScope.launch {
            loadLenses()
            openLatest()
        }
    }

    /** 进入页面：接着最近一次对话；没有就等第一次发送时再建（不为「只是看看」白建空会话）。 */
    private suspend fun openLatest() {
        when (val list = agent.listConversations(projectId)) {
            is Outcome.Success -> {
                val latest = list.value.maxByOrNull { it.updatedAt }
                if (latest != null) open(latest.id) else _state.update { it.copy(loading = false, conversations = list.value) }
            }
            // 离线 / 失败：仍可开始新对话（发送时会再尝试联网）
            is Outcome.Failure -> _state.update { it.copy(loading = false, error = list.error.message) }
        }
    }

    private suspend fun loadLenses() {
        when (val r = agent.loadLenses(projectId)) {
            is Outcome.Success -> _state.update {
                it.copy(
                    lensCatalog = r.value.catalog,
                    activeLensIds = r.value.activeIds,
                    maxActiveLenses = r.value.maxActive,
                )
            }
            is Outcome.Failure -> {
                // 眼光加载失败不挡聊天；用户打开面板时会再试
            }
        }
    }

    private suspend fun open(conversationId: String) {
        _state.update { it.copy(loading = true, error = null) }
        when (val r = agent.loadConversation(projectId, conversationId)) {
            is Outcome.Success -> {
                val c = r.value
                _state.update {
                    it.copy(
                        loading = false,
                        conversationId = c.id,
                        title = c.title,
                        items = c.messages.map { m -> ChatItem(m) },
                        resumable = c.resumable,
                        liveSteps = emptyList(),
                        notice = null,
                        showConversations = false,
                    )
                }
            }
            is Outcome.Failure -> _state.update { it.copy(loading = false, error = r.error.message) }
        }
    }

    fun onInput(text: String) = _state.update { it.copy(input = text) }
    fun setApplyActions(on: Boolean) = _state.update { it.copy(applyActions = on) }
    fun dismissError() = _state.update { it.copy(error = null) }
    fun dismissNotice() = _state.update { it.copy(notice = null) }

    fun showConversations(show: Boolean) {
        _state.update { it.copy(showConversations = show) }
        if (show) viewModelScope.launch {
            val r = agent.listConversations(projectId)
            if (r is Outcome.Success) _state.update { it.copy(conversations = r.value.sortedByDescending { c -> c.updatedAt }) }
        }
    }

    fun showLenses(show: Boolean) {
        _state.update { it.copy(showLenses = show) }
        if (show && _state.value.lensCatalog.isEmpty()) {
            viewModelScope.launch { loadLenses() }
        }
    }

    /**
     * 切换作家眼光。点已选中的会取消；空选 = 通用文学编辑。
     * 最多 [AgentUiState.maxActiveLenses] 个，满员后再选会提示。
     */
    fun toggleLens(id: String?) {
        if (_state.value.lensBusy || _state.value.running) return
        val current = _state.value.activeLensIds
        val max = _state.value.maxActiveLenses
        val next = when {
            id == null -> emptyList()
            id in current -> current - id
            current.size >= max -> {
                _state.update { it.copy(error = "最多同时选 $max 位作家眼光") }
                return
            }
            else -> current + id
        }
        viewModelScope.launch {
            _state.update { it.copy(lensBusy = true, error = null) }
            when (val r = agent.setActiveLenses(projectId, next)) {
                is Outcome.Success -> _state.update {
                    it.copy(activeLensIds = r.value, lensBusy = false)
                }
                is Outcome.Failure -> _state.update {
                    it.copy(lensBusy = false, error = r.error.message)
                }
            }
        }
    }

    fun openConversation(id: String) {
        if (_state.value.running) return
        viewModelScope.launch { open(id) }
    }

    fun newConversation() {
        if (_state.value.running) return
        _state.update {
            AgentUiState(
                loading = false,
                applyActions = it.applyActions,
                conversations = it.conversations,
                lensCatalog = it.lensCatalog,
                activeLensIds = it.activeLensIds,
                maxActiveLenses = it.maxActiveLenses,
            )
        }
    }

    fun send() {
        val s = _state.value
        val text = s.input.trim()
        if (s.running || text.isEmpty()) return
        val items = s.items + ChatItem(AgentMessage(AgentRole.USER, text))
        _state.update { it.copy(items = items, input = "", error = null, notice = null, resumable = false) }
        start(items, resume = false)
    }

    /** 失败后用现有消息原样再来一次（不重复追加用户消息）。 */
    fun retry() {
        val s = _state.value
        if (s.running || s.items.lastOrNull()?.message?.role != AgentRole.USER) return
        _state.update { it.copy(error = null, notice = null) }
        start(s.items, resume = false)
    }

    fun resume() {
        val s = _state.value
        if (s.running || !s.resumable) return
        _state.update { it.copy(error = null, notice = null, resumable = false) }
        start(s.items, resume = true)
    }

    fun stop() {
        // 只断开本机的连接；服务端可能仍在跑，所以提示作者稍后刷新
        runJob?.cancel()
    }

    private fun start(items: List<ChatItem>, resume: Boolean) {
        runJob = viewModelScope.launch {
            _state.update { it.copy(running = true, liveSteps = emptyList()) }
            try {
                val convId = ensureConversation(items) ?: return@launch
                val request = AgentRunRequest(
                    projectId = projectId,
                    conversationId = convId,
                    messages = items.map { it.message },
                    chapterId = null,
                    selection = null,
                    applyActions = _state.value.applyActions,
                    resume = resume,
                    lensIds = _state.value.activeLensIds,
                )
                agent.run(request).collect { event -> handle(event, items, convId) }
            } finally {
                // 取消（点停止 / 离开页面）也要把「运行中」状态收回来
                // 正常结束（Final / Error）时 handle 已经把 running 置 false；仍为 true 说明是被中途打断的
                val interrupted = _state.value.running
                _state.update {
                    it.copy(
                        running = false,
                        notice = if (interrupted && it.error == null && it.notice == null) {
                            "已停止等待。服务端可能仍在处理，稍后可刷新作品查看结果。"
                        } else {
                            it.notice
                        },
                    )
                }
            }
        }
    }

    private suspend fun ensureConversation(items: List<ChatItem>): String? {
        _state.value.conversationId?.let { return it }
        val title = items.firstOrNull { it.message.role == AgentRole.USER }?.message?.content?.take(20)
        return when (val r = agent.createConversation(projectId, title)) {
            is Outcome.Success -> {
                _state.update { it.copy(conversationId = r.value.id, title = r.value.title) }
                r.value.id
            }
            is Outcome.Failure -> {
                _state.update { it.copy(error = r.error.message) }
                null
            }
        }
    }

    private suspend fun handle(event: AgentEvent, sent: List<ChatItem>, convId: String) {
        when (event) {
            is AgentEvent.Task -> addLive("任务：${event.text}")
            is AgentEvent.Thought -> addLive("思考：${event.text.take(120)}")
            is AgentEvent.ToolCall -> addLive("调用 ${event.step.name}${event.step.summary.prefixed()}")
            is AgentEvent.ToolResult -> addLive("结果 ${event.step.name}：${event.step.summary}")
            is AgentEvent.Actions -> addLive("生成了 ${event.count} 项改动")
            is AgentEvent.Review -> addLive("自检：${event.text.take(120)}")
            is AgentEvent.Error -> _state.update { it.copy(error = event.message, running = false) }
            is AgentEvent.Final -> {
                val r = event.result
                val reply = ChatItem(
                    message = AgentMessage(AgentRole.ASSISTANT, r.message.ifBlank { "（没有文字回复）" }),
                    steps = _state.value.liveSteps,
                    warnings = r.warnings,
                    applied = r.applied,
                )
                val all = sent + reply
                _state.update {
                    it.copy(
                        items = all,
                        liveSteps = emptyList(),
                        running = false,
                        notice = if (r.applied) "Agent 已把 ${r.actionCount} 项改动写入作品，章节内容已更新。" else null,
                    )
                }
                // 会话保存失败不影响本轮结果：提示一下，下次发送时会带上完整历史
                val saved = agent.saveConversation(projectId, convId, all.map { it.message })
                if (saved is Outcome.Failure) {
                    _state.update { it.copy(error = "回复已生成，但对话记录没能保存：${saved.error.message}") }
                }
            }
        }
    }

    private fun addLive(line: String) = _state.update { it.copy(liveSteps = (it.liveSteps + line).takeLast(MAX_LIVE_STEPS)) }

    private fun String.prefixed() = if (isBlank()) "" else "（$this）"

    private companion object {
        const val MAX_LIVE_STEPS = 40
    }
}
