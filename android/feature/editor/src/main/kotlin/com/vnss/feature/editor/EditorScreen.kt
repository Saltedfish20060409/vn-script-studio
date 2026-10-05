package com.vnss.feature.editor

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.speech.RecognizerIntent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.AssistChip
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.OffsetMapping
import androidx.compose.ui.text.input.TransformedText
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.vnss.core.designsystem.EmptyState
import com.vnss.core.designsystem.InfoBanner
import com.vnss.core.designsystem.LoadingBox
import com.vnss.core.designsystem.ProseTextStyle
import com.vnss.core.designsystem.SyncBadge
import com.vnss.core.model.SyncState
import com.vnss.feature.editor.check.IssueLevel
import com.vnss.feature.editor.check.MatchRange
import com.vnss.feature.editor.check.ProseLinter
import com.vnss.feature.editor.check.SCENE_SEPARATOR
import com.vnss.feature.editor.check.goalProgress

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EditorRoute(
    onBack: () -> Unit,
    onResolveConflict: (chapterId: String) -> Unit,
    viewModel: EditorViewModel = hiltViewModel(),
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    // 离开页面 / 进后台立刻落库：不能只靠 700ms 去抖，否则最后几个字会丢
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) viewModel.flushNow()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            viewModel.flushNow()
        }
    }

    var showIssues by remember { mutableStateOf(false) }
    var showScenes by remember { mutableStateOf(false) }
    var voiceError by remember { mutableStateOf<String?>(null) }

    val speech = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) {
            result.data?.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS)?.firstOrNull()?.let(viewModel::insert)
        }
    }
    val startVoice = {
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN")
            .putExtra(RecognizerIntent.EXTRA_PROMPT, "请说话")
        try {
            speech.launch(intent)
        } catch (e: ActivityNotFoundException) {
            voiceError = "这台设备没有可用的语音输入服务。"
        }
    }

    Scaffold(
        modifier = Modifier.imePadding(),
        topBar = {
            TopAppBar(
                title = {
                    BasicTextField(
                        value = state.title,
                        onValueChange = viewModel::onTitleChange,
                        singleLine = true,
                        textStyle = MaterialTheme.typography.titleMedium.copy(color = MaterialTheme.colorScheme.onSurface),
                        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                        decorationBox = { inner ->
                            Box {
                                if (state.title.isEmpty()) {
                                    Text("章节标题", color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.titleMedium)
                                }
                                inner()
                            }
                        },
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
            )
        },
        bottomBar = {
            // 边到边显示下底栏不会自动避开导航条；键盘弹出时导航条 inset 已被 imePadding 吃掉，不会叠加
            Column(Modifier.navigationBarsPadding()) {
                if (state.find.visible) FindBar(state.find, viewModel)
                StatusRow(state)
                ToolRow(
                    state = state,
                    onUndo = viewModel::undo,
                    onRedo = viewModel::redo,
                    onPair = viewModel::insertPair,
                    onInsert = viewModel::insert,
                    onSeparator = viewModel::insertSceneSeparator,
                    onFind = viewModel::toggleFind,
                    onIssues = { showIssues = true },
                    onScenes = { showScenes = true },
                    onVoice = startVoice,
                )
            }
        },
    ) { padding ->
        Column(Modifier.padding(padding).fillMaxSize()) {
            when {
                state.loading -> LoadingBox()
                state.missing -> EmptyState("章节不存在", hint = "它可能已在别处被删除。")
                else -> {
                    state.notice?.let {
                        InfoBanner(it, Modifier.padding(horizontal = 12.dp, vertical = 4.dp), onDismiss = viewModel::dismissNotice)
                    }
                    voiceError?.let {
                        InfoBanner(it, Modifier.padding(horizontal = 12.dp, vertical = 4.dp), onDismiss = { voiceError = null })
                    }
                    if (state.syncState == SyncState.CONFLICT) {
                        ConflictBanner(onClick = { onResolveConflict(viewModel.chapterId) })
                    }
                    state.syncError?.let {
                        Text(
                            it,
                            Modifier.padding(horizontal = 16.dp, vertical = 2.dp),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.error,
                        )
                    }
                    if (state.scriptOnly && state.body.text.isEmpty()) {
                        Text(
                            "这一章在网页端只有脚本、没有正文。在这里写的文字会成为这一章的正文主稿。",
                            Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    BodyField(state, viewModel)
                }
            }
        }
    }

    if (showIssues) {
        IssuesSheet(
            lint = state.lint,
            bodyText = state.body.text,
            onDismiss = { showIssues = false },
            onJump = { offset, length ->
                showIssues = false
                viewModel.jumpTo(offset, length)
            },
        )
    }
    if (showScenes) {
        ScenesSheet(
            lint = state.lint,
            bodyText = state.body.text,
            onDismiss = { showScenes = false },
            onJump = { offset ->
                showScenes = false
                viewModel.jumpTo(offset, 0)
            },
        )
    }
}

@Composable
private fun ConflictBanner(onClick: () -> Unit) {
    Surface(
        color = MaterialTheme.colorScheme.errorContainer,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
        shape = MaterialTheme.shapes.medium,
    ) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(
                "此章与服务器版本冲突，处理之前不会上传。",
                Modifier.weight(1f),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onErrorContainer,
            )
            TextButton(onClick = onClick) { Text("去处理") }
        }
    }
}

// ---------------------------------------------------------------------------- 正文输入框

@Composable
private fun BodyField(state: EditorUiState, viewModel: EditorViewModel) {
    val scroll = rememberScrollState()
    val focus = remember { FocusRequester() }
    var layout by remember { mutableStateOf<TextLayoutResult?>(null) }

    val scheme = MaterialTheme.colorScheme
    val highlight = remember(state.lint, state.find.ranges, state.find.currentIndex, scheme) {
        ProseHighlighter(
            lint = state.lint,
            findRanges = state.find.ranges,
            currentFind = state.find.currentIndex,
            errorColor = scheme.error,
            warnColor = scheme.tertiary,
            infoColor = scheme.outline,
            markerColor = scheme.primary,
            findColor = scheme.secondaryContainer,
            currentFindColor = scheme.tertiaryContainer,
        )
    }

    // 外部要求滚动到某个偏移（跳转到问题 / 场景 / 查找命中）
    val reveal = state.reveal
    LaunchedEffect(reveal?.nonce) {
        if (reveal == null) return@LaunchedEffect
        layout?.let { l ->
            val line = l.getLineForOffset(reveal.offset.coerceIn(0, l.layoutInput.text.length))
            scroll.animateScrollTo((l.getLineTop(line) - 120f).toInt().coerceAtLeast(0))
        }
        if (reveal.focusBody) focus.requestFocus()
    }

    Box(Modifier.fillMaxSize().verticalScroll(scroll)) {
        BasicTextField(
            value = state.body,
            onValueChange = viewModel::onBodyChange,
            textStyle = ProseTextStyle.copy(color = MaterialTheme.colorScheme.onSurface),
            cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
            visualTransformation = highlight,
            onTextLayout = { layout = it },
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 12.dp)
                .focusRequester(focus),
            decorationBox = { inner ->
                Box(Modifier.fillMaxWidth().padding(bottom = 240.dp)) {
                    if (state.body.text.isEmpty()) {
                        Text("开始写作…", style = ProseTextStyle, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    inner()
                }
            },
        )
    }
}

/**
 * 在输入框里叠加高亮：问题下划线、场景标记、查找命中。只在体检结果对应当前文本时才画问题和标记，
 * 否则偏移已经错位（体检有 400ms 去抖），宁可暂时不画也不要画在错的位置上。
 */
private class ProseHighlighter(
    private val lint: LintResult,
    private val findRanges: List<MatchRange>,
    private val currentFind: Int,
    private val errorColor: Color,
    private val warnColor: Color,
    private val infoColor: Color,
    private val markerColor: Color,
    private val findColor: Color,
    private val currentFindColor: Color,
) : VisualTransformation {

    override fun filter(text: AnnotatedString): TransformedText {
        val src = text.text
        val b = AnnotatedString.Builder(text)
        fun span(style: SpanStyle, from: Int, to: Int) {
            val s = from.coerceIn(0, src.length)
            val e = to.coerceIn(s, src.length)
            if (e > s) b.addStyle(style, s, e)
        }
        if (src == lint.text) {
            for (m in lint.markers) span(SpanStyle(color = markerColor, fontWeight = FontWeight.Medium), m.from, m.to)
            for (i in lint.issues) {
                val color = when (i.level) {
                    IssueLevel.ERROR -> errorColor
                    IssueLevel.WARN -> warnColor
                    IssueLevel.INFO -> infoColor
                }
                span(SpanStyle(textDecoration = TextDecoration.Underline, background = color.copy(alpha = 0.14f)), i.offset, i.offset + maxOf(i.length, 1))
            }
        }
        findRanges.forEachIndexed { idx, r ->
            val c = if (idx == currentFind) currentFindColor else findColor
            span(SpanStyle(background = c), r.from, r.to)
        }
        return TransformedText(b.toAnnotatedString(), OffsetMapping.Identity)
    }
}

// ---------------------------------------------------------------------------- 底部栏

@Composable
private fun StatusRow(state: EditorUiState) {
    Surface(color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.5f)) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Text("${state.words} 字", style = MaterialTheme.typography.labelMedium)
                val delta = state.sessionDelta
                if (delta != 0) {
                    Text(
                        "本次 ${if (delta > 0) "+" else ""}$delta",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                val counts = ProseLinter.countIssues(state.lint.issues)
                val err = counts[IssueLevel.ERROR] ?: 0
                val warn = counts[IssueLevel.WARN] ?: 0
                if (err + warn > 0) {
                    Text(
                        buildString {
                            if (err > 0) append("$err 处错误 ")
                            if (warn > 0) append("$warn 处提示")
                        },
                        style = MaterialTheme.typography.labelSmall,
                        color = if (err > 0) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.tertiary,
                    )
                }
                Box(Modifier.weight(1f))
                SyncBadge(state.syncState)
            }
            if (state.dailyGoal > 0) {
                // 这里只统计「本次写作」相对目标的进度，跨次累计的日更统计在网页端的写作统计里
                val g = goalProgress(state.sessionDelta.coerceAtLeast(0), state.dailyGoal.toDouble())
                LinearProgressIndicator(
                    progress = { g.ratio.toFloat() },
                    modifier = Modifier.fillMaxWidth().padding(top = 2.dp),
                )
                Text(
                    if (g.done) "已达到 ${g.target} 字目标" else "本次写作距目标还差 ${g.remaining} 字",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

@Composable
private fun ToolRow(
    state: EditorUiState,
    onUndo: () -> Unit,
    onRedo: () -> Unit,
    onPair: (String) -> Unit,
    onInsert: (String) -> Unit,
    onSeparator: () -> Unit,
    onFind: () -> Unit,
    onIssues: () -> Unit,
    onScenes: () -> Unit,
    onVoice: () -> Unit,
) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp) {
        Row(
            Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 8.dp, vertical = 6.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            AssistChip(onClick = onUndo, enabled = state.canUndo, label = { Text("撤销") })
            AssistChip(onClick = onRedo, enabled = state.canRedo, label = { Text("重做") })
            SuggestionChip(onClick = { onPair("「") }, label = { Text("「」") })
            SuggestionChip(onClick = { onPair("“") }, label = { Text("“”") })
            SuggestionChip(onClick = { onPair("（") }, label = { Text("（）") })
            SuggestionChip(onClick = { onInsert("……") }, label = { Text("……") })
            SuggestionChip(onClick = { onInsert("——") }, label = { Text("——") })
            SuggestionChip(onClick = onSeparator, label = { Text(SCENE_SEPARATOR) })
            AssistChip(onClick = onFind, label = { Text(if (state.find.visible) "关闭查找" else "查找替换") })
            AssistChip(
                onClick = onIssues,
                label = { Text(if (state.lint.issues.isEmpty()) "笔误检查" else "笔误检查 ${state.lint.issues.size}") },
            )
            AssistChip(onClick = onScenes, label = { Text("分场 ${state.lint.scenes.size}") })
            AssistChip(onClick = onVoice, label = { Text("语音输入") })
        }
    }
}

@Composable
private fun FindBar(find: FindUiState, vm: EditorViewModel) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 6.dp) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                SmallField(find.query, vm::onFindQuery, "查找", Modifier.weight(1f))
                Text(
                    when {
                        find.invalidRegex -> "正则有误"
                        find.query.isEmpty() -> ""
                        find.ranges.isEmpty() -> "无结果"
                        else -> "${find.currentIndex + 1}/${find.ranges.size}"
                    },
                    style = MaterialTheme.typography.labelSmall,
                    color = if (find.invalidRegex) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                )
                TextButton(onClick = vm::findPrevious) { Text("上一个") }
                TextButton(onClick = vm::findNext) { Text("下一个") }
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                SmallField(find.replacement, vm::onReplacement, "替换为", Modifier.weight(1f))
                TextButton(onClick = vm::replaceCurrent) { Text("替换") }
                TextButton(onClick = vm::replaceAll) { Text("全部") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                AssistChip(onClick = vm::toggleCaseSensitive, label = { Text(if (find.caseSensitive) "区分大小写 ✓" else "区分大小写") })
                AssistChip(onClick = vm::toggleRegex, label = { Text(if (find.regex) "正则 ✓" else "正则") })
            }
        }
    }
}

@Composable
private fun SmallField(value: String, onChange: (String) -> Unit, hint: String, modifier: Modifier = Modifier) {
    Box(
        modifier
            .background(MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.shapes.small)
            .padding(horizontal = 10.dp, vertical = 8.dp),
    ) {
        BasicTextField(
            value = value,
            onValueChange = onChange,
            singleLine = true,
            textStyle = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onSurface),
            cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
            modifier = Modifier.fillMaxWidth(),
            decorationBox = { inner ->
                if (value.isEmpty()) Text(hint, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                inner()
            },
        )
    }
}
