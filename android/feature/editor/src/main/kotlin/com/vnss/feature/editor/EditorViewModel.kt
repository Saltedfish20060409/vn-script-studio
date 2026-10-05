package com.vnss.feature.editor

import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vnss.core.common.DispatcherProvider
import com.vnss.core.common.ThreeWayMerge
import com.vnss.core.common.WordCount
import com.vnss.core.model.Chapter
import com.vnss.core.model.ProjectRepository
import com.vnss.core.model.SettingsRepository
import com.vnss.core.model.SyncState
import com.vnss.feature.editor.check.FindOptions
import com.vnss.feature.editor.check.FindReplace
import com.vnss.feature.editor.check.MatchRange
import com.vnss.feature.editor.check.PairInput
import com.vnss.feature.editor.check.ProseLinter
import com.vnss.feature.editor.check.SCENE_SEPARATOR
import com.vnss.feature.editor.check.SceneBlock
import com.vnss.feature.editor.check.SceneParser
import com.vnss.feature.editor.check.TextIssue
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Named

const val ARG_CHAPTER_ID = "chapterId"

/** 一次体检的结果，连同它所针对的文本一起保存（文本变了高亮就作废，避免错位）。 */
data class LintResult(
    val text: String,
    val issues: List<TextIssue>,
    val scenes: List<SceneBlock>,
    val markers: List<MatchRange> = emptyList(),
) {
    companion object {
        val EMPTY = LintResult("", emptyList(), emptyList())
    }
}

data class FindUiState(
    val visible: Boolean = false,
    val query: String = "",
    val replacement: String = "",
    val caseSensitive: Boolean = false,
    val regex: Boolean = false,
    val ranges: List<MatchRange> = emptyList(),
    /** 当前命中在 [ranges] 中的下标，-1 = 无。 */
    val currentIndex: Int = -1,
    val invalidRegex: Boolean = false,
)

/** 要求界面把某个偏移滚动到可见位置（nonce 递增表示一次新的请求）。 */
data class RevealRequest(val offset: Int, val focusBody: Boolean, val nonce: Int)

data class EditorUiState(
    val loading: Boolean = true,
    val missing: Boolean = false,
    val title: String = "",
    val body: TextFieldValue = TextFieldValue(""),
    val syncState: SyncState = SyncState.SYNCED,
    val syncError: String? = null,
    val scriptOnly: Boolean = false,
    val words: Int = 0,
    /** 本次打开编辑器以来净增的字数（可为负）。 */
    val sessionDelta: Int = 0,
    val dailyGoal: Int = 0,
    val canUndo: Boolean = false,
    val canRedo: Boolean = false,
    val lint: LintResult = LintResult.EMPTY,
    val find: FindUiState = FindUiState(),
    val reveal: RevealRequest? = null,
    val notice: String? = null,
)

@OptIn(FlowPreview::class)
@HiltViewModel
class EditorViewModel @Inject constructor(
    savedState: SavedStateHandle,
    private val projects: ProjectRepository,
    private val settings: SettingsRepository,
    private val dispatchers: DispatcherProvider,
    @Named("appScope") private val appScope: CoroutineScope,
) : ViewModel() {

    val chapterId: String = checkNotNull(savedState[ARG_CHAPTER_ID]) { "缺少 chapterId 参数" }

    private val _state = MutableStateFlow(EditorUiState())
    val state: StateFlow<EditorUiState> = _state.asStateFlow()

    private val history = EditHistory()
    private val saveMutex = Mutex()
    private val saveTrigger = MutableSharedFlow<Unit>(extraBufferCapacity = 1, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    private val lintTrigger = MutableSharedFlow<Unit>(extraBufferCapacity = 1, onBufferOverflow = BufferOverflow.DROP_OLDEST)

    /** 本地库里（我们所知的）最后一次内容；与它比较才能区分「我自己保存的回声」和「别处改的」。 */
    private var lastSavedTitle = ""
    private var lastSavedProse = ""
    private var initialWords = 0
    private var revealNonce = 0

    init {
        viewModelScope.launch { observeChapter() }
        viewModelScope.launch { saveTrigger.debounce(SAVE_DEBOUNCE_MS).collect { persist() } }
        viewModelScope.launch { lintTrigger.debounce(LINT_DEBOUNCE_MS).collect { runLint() } }
    }

    // ------------------------------------------------------------------ 加载 / 外部变化

    private suspend fun observeChapter() {
        val goal = settings.local.first().dailyGoalWords
        projects.observeChapter(chapterId).collect { chapter ->
            if (chapter == null) {
                _state.update { it.copy(loading = false, missing = true) }
            } else {
                onChapter(chapter, goal)
            }
        }
    }

    private fun onChapter(ch: Chapter, dailyGoal: Int) {
        val s = _state.value
        if (s.loading) {
            lastSavedTitle = ch.title
            lastSavedProse = ch.prose
            initialWords = WordCount.count(ch.prose)
            _state.value = s.copy(
                loading = false,
                missing = false,
                title = ch.title,
                body = TextFieldValue(ch.prose),
                syncState = ch.syncState,
                syncError = ch.syncError,
                scriptOnly = ch.scriptOnly,
                words = initialWords,
                dailyGoal = dailyGoal,
            )
            lintTrigger.tryEmit(Unit)
            return
        }

        var next = s.copy(syncState = ch.syncState, syncError = ch.syncError, scriptOnly = ch.scriptOnly)
        var needSave = false

        if (ch.title != lastSavedTitle && s.title == lastSavedTitle) {
            next = next.copy(title = ch.title)
        }

        if (ch.prose != lastSavedProse) {
            // 本地库里的正文不是我保存的那份：同步引擎或别处更新了它
            val draft = s.body.text
            if (draft == lastSavedProse) {
                next = next.copy(body = clampTo(s.body, ch.prose), notice = "此章已在别处更新，已载入最新内容。")
            } else {
                when (val m = ThreeWayMerge.merge(lastSavedProse, draft, ch.prose)) {
                    is ThreeWayMerge.Result.Clean -> {
                        next = next.copy(body = clampTo(s.body, m.text), notice = "已自动合并其他位置对此章的修改。")
                        needSave = true
                    }
                    is ThreeWayMerge.Result.Conflict -> {
                        next = next.copy(notice = "此章在别处也被修改了，你刚输入的内容已保留；同步时可能需要你处理冲突。")
                    }
                }
            }
        }
        lastSavedTitle = ch.title
        lastSavedProse = ch.prose

        val words = WordCount.count(next.body.text)
        _state.value = next.copy(words = words, sessionDelta = words - initialWords)
        if (next.body.text != s.body.text) lintTrigger.tryEmit(Unit)
        if (needSave || next.body.text != ch.prose || next.title != ch.title) saveTrigger.tryEmit(Unit)
    }

    private fun clampTo(old: TextFieldValue, text: String) = TextFieldValue(
        text,
        TextRange(old.selection.start.coerceIn(0, text.length), old.selection.end.coerceIn(0, text.length)),
    )

    // ------------------------------------------------------------------ 编辑

    fun onTitleChange(title: String) {
        if (_state.value.title == title) return
        _state.update { it.copy(title = title) }
        saveTrigger.tryEmit(Unit)
    }

    fun onBodyChange(incoming: TextFieldValue) {
        val old = _state.value.body
        var value = incoming
        if (incoming.text != old.text && incoming.composition == null) {
            val key = PairInput.detectTypedChar(old.text, old.selection.min, old.selection.max, incoming.text)
            val edit = key?.let { PairInput.applyMobile(old.text, old.selection.min, old.selection.max, it) }
            if (edit != null) {
                value = TextFieldValue(edit.text, edit.selection?.let { TextRange(it.from, it.to) } ?: TextRange(edit.caret))
            }
        }
        applyBody(value)
    }

    private fun applyBody(value: TextFieldValue, recordHistory: Boolean = true) {
        val s = _state.value
        val textChanged = value.text != s.body.text
        if (textChanged && recordHistory) {
            history.record(
                EditHistory.Snapshot(s.body.text, s.body.selection.start, s.body.selection.end),
                System.currentTimeMillis(),
            )
        }
        val words = if (textChanged) WordCount.count(value.text) else s.words
        _state.update {
            it.copy(
                body = value,
                words = words,
                sessionDelta = words - initialWords,
                canUndo = history.canUndo,
                canRedo = history.canRedo,
            )
        }
        if (textChanged) {
            saveTrigger.tryEmit(Unit)
            lintTrigger.tryEmit(Unit)
            if (_state.value.find.visible) recomputeFind(moveSelection = false)
        }
    }

    fun undo() {
        val s = _state.value
        val snap = history.undo(EditHistory.Snapshot(s.body.text, s.body.selection.start, s.body.selection.end)) ?: return
        applyBody(snapshotValue(snap), recordHistory = false)
    }

    fun redo() {
        val s = _state.value
        val snap = history.redo(EditHistory.Snapshot(s.body.text, s.body.selection.start, s.body.selection.end)) ?: return
        applyBody(snapshotValue(snap), recordHistory = false)
    }

    private fun snapshotValue(s: EditHistory.Snapshot) = TextFieldValue(
        s.text,
        TextRange(s.selStart.coerceIn(0, s.text.length), s.selEnd.coerceIn(0, s.text.length)),
    )

    /** 在光标处插入（有选区则替换选区）。语音输入、快捷符号、分场线都走这里。 */
    fun insert(text: String) {
        val body = _state.value.body
        val start = body.selection.min
        val end = body.selection.max
        val newText = body.text.substring(0, start) + text + body.text.substring(end)
        applyBody(TextFieldValue(newText, TextRange(start + text.length)))
    }

    /** 插入一对中文标点（「」等），光标留在中间；有选区则把选区包起来。 */
    fun insertPair(open: String) {
        val body = _state.value.body
        val edit = PairInput.applyPairOnKey(body.text, body.selection.min, body.selection.max, open) ?: return
        applyBody(TextFieldValue(edit.text, edit.selection?.let { TextRange(it.from, it.to) } ?: TextRange(edit.caret)))
    }

    fun insertSceneSeparator() {
        val body = _state.value.body
        val before = body.text.substring(0, body.selection.min)
        val prefix = if (before.isEmpty() || before.endsWith("\n")) "" else "\n"
        insert("$prefix$SCENE_SEPARATOR\n")
    }

    /** 跳到并选中 [offset, offset+length)，同时请求界面滚动到那里。 */
    fun jumpTo(offset: Int, length: Int) {
        val body = _state.value.body
        val start = offset.coerceIn(0, body.text.length)
        val end = (offset + length).coerceIn(start, body.text.length)
        _state.update {
            it.copy(
                body = it.body.copy(selection = TextRange(start, end)),
                reveal = RevealRequest(start, focusBody = true, nonce = ++revealNonce),
            )
        }
    }

    fun dismissNotice() = _state.update { it.copy(notice = null) }

    // ------------------------------------------------------------------ 保存

    private suspend fun persist() {
        saveMutex.withLock {
            val s = _state.value
            if (s.loading || s.missing) return
            val title = s.title
            val prose = s.body.text
            if (title == lastSavedTitle && prose == lastSavedProse) return
            // 先更新「已知的库内容」再写库：库的回声事件到达时不会被误认为别处的修改
            lastSavedTitle = title
            lastSavedProse = prose
            projects.saveDraft(chapterId, title, prose)
        }
    }

    /**
     * 立刻落库，离开页面 / 应用进后台时调用。放在进程级作用域里跑：
     * 页面销毁时 viewModelScope 已被取消，用它写库会把最后几个字丢掉。
     */
    fun flushNow() {
        appScope.launch { persist() }
    }

    // ------------------------------------------------------------------ 体检

    private suspend fun runLint() {
        val text = _state.value.body.text
        val result = withContext(dispatchers.default) {
            LintResult(text, ProseLinter.lintProse(text), SceneParser.parseScenes(text), SceneParser.markerLines(text))
        }
        _state.update { it.copy(lint = result) }
    }

    // ------------------------------------------------------------------ 查找 / 替换

    fun toggleFind() {
        _state.update {
            if (it.find.visible) it.copy(find = FindUiState()) else it.copy(find = it.find.copy(visible = true))
        }
        if (_state.value.find.visible) recomputeFind(moveSelection = false)
    }

    fun onFindQuery(q: String) {
        _state.update { it.copy(find = it.find.copy(query = q)) }
        recomputeFind(moveSelection = true)
    }

    fun onReplacement(r: String) = _state.update { it.copy(find = it.find.copy(replacement = r)) }

    fun toggleCaseSensitive() {
        _state.update { it.copy(find = it.find.copy(caseSensitive = !it.find.caseSensitive)) }
        recomputeFind(moveSelection = true)
    }

    fun toggleRegex() {
        _state.update { it.copy(find = it.find.copy(regex = !it.find.regex)) }
        recomputeFind(moveSelection = true)
    }

    private fun options(f: FindUiState) = FindOptions(f.caseSensitive, f.regex)

    private fun recomputeFind(moveSelection: Boolean) {
        val s = _state.value
        val f = s.find
        val ranges = FindReplace.findMatches(s.body.text, f.query, options(f))
        if (ranges == null) {
            _state.update { it.copy(find = f.copy(ranges = emptyList(), currentIndex = -1, invalidRegex = true)) }
            return
        }
        val sel = s.body.selection
        // 当前命中 = 选区正好覆盖的那个；否则按光标位置取下一个
        var index = ranges.indexOfFirst { it.from == sel.min && it.to == sel.max }
        if (index < 0 && moveSelection && ranges.isNotEmpty()) {
            val target = FindReplace.nextMatch(ranges, sel.min - 1, 1)
            index = ranges.indexOf(target)
        }
        _state.update { it.copy(find = f.copy(ranges = ranges, currentIndex = index, invalidRegex = false)) }
        if (moveSelection && index >= 0) selectMatch(ranges[index])
    }

    fun findNext() = step(1)
    fun findPrevious() = step(-1)

    private fun step(direction: Int) {
        val s = _state.value
        val ranges = s.find.ranges
        if (ranges.isEmpty()) return
        val target = FindReplace.nextMatch(ranges, s.body.selection.min, direction) ?: return
        _state.update { it.copy(find = it.find.copy(currentIndex = ranges.indexOf(target))) }
        selectMatch(target)
    }

    /** 高亮并滚动到命中；不抢焦点，输入框里的光标还在查找框里。 */
    private fun selectMatch(range: MatchRange) {
        _state.update {
            it.copy(
                body = it.body.copy(selection = TextRange(range.from, range.to)),
                reveal = RevealRequest(range.from, focusBody = false, nonce = ++revealNonce),
            )
        }
    }

    fun replaceCurrent() {
        val s = _state.value
        val f = s.find
        val ranges = f.ranges
        if (ranges.isEmpty()) return
        val sel = s.body.selection
        val current = ranges.firstOrNull { it.from == sel.min && it.to == sel.max }
        if (current == null) {
            step(1) // 还没定位到某一处：先定位，再按一次才替换
            return
        }
        val text = s.body.text
        val replacement = FindReplace.expandReplacement(text, current, f.query, f.replacement, options(f))
        val newText = FindReplace.replaceRange(text, current.from, current.to, replacement)
        val caret = current.from + replacement.length
        applyBody(TextFieldValue(newText, TextRange(caret))) // 内部会重算命中
        // 光标正好落在下一处命中的起点时也要选中它，所以用 caret - 1 作为「严格大于」的界线
        val after = _state.value.find.ranges
        val target = FindReplace.nextMatch(after, caret - 1, 1) ?: return
        _state.update { it.copy(find = it.find.copy(currentIndex = after.indexOf(target))) }
        selectMatch(target)
    }

    fun replaceAll() {
        val s = _state.value
        val f = s.find
        if (f.query.isEmpty()) return
        val result = FindReplace.replaceAll(s.body.text, f.query, f.replacement, options(f))
        if (result.count == 0) return
        applyBody(TextFieldValue(result.text, TextRange(0)))
        _state.update { it.copy(notice = "已替换 ${result.count} 处。") }
    }

    private companion object {
        const val SAVE_DEBOUNCE_MS = 700L
        const val LINT_DEBOUNCE_MS = 400L
    }
}
