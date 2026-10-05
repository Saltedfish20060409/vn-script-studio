package com.vnss.feature.editor.check

import com.vnss.core.common.WordCount
import com.vnss.feature.editor.check.JsText.NON_WS_CLASS
import com.vnss.feature.editor.check.JsText.WS_CLASS

/** 场景分隔符：一键插入（后端 / 导出把它当分场标记）。 */
const val SCENE_SEPARATOR = "◇◇◇"

data class SceneBlock(
    val index: Int,
    val title: String,
    val from: Int,
    val to: Int,
    val words: Int,
    val explicit: Boolean,
)

/**
 * 场景大纲解析——`editorAssist.ts` 中 `parseScenes` 的移植。
 * 没有分隔符时整章是「一个场景」，不返回空列表（界面据此区分「没分场」和「空章节」）。
 */
object SceneParser {

    private const val NUM = "[零一二三四五六七八九十百千0-9]"

    private val SEPARATOR_RE = Regex("[◇◆※*\\-—_=·]{3,}")
    private val BRACKET_RE = Regex("【(.+)】")
    private val SCENE_PREFIX_RE = Regex("场景[：:]$WS_CLASS*(.+)")
    private val HASH_RE = Regex("#{2,}$WS_CLASS*(.+)")
    private val ORDINAL_RE = Regex("第$WS_CLASS*($NUM+)$WS_CLASS*场$WS_CLASS*")
    private val LABELED_RE = Regex("第$WS_CLASS*$NUM+$WS_CLASS*场$WS_CLASS*[：:·—-]$WS_CLASS*(.+)")
    private val SPACED_RE = Regex("第$WS_CLASS*$NUM+$WS_CLASS*场$WS_CLASS+($NON_WS_CLASS.*)")
    private val SENTENCE_END = Regex("[。！？…；]$")

    /**
     * 显式场景标题。刻意用几条严格形式而不是一条宽松正则：`第一场的内容。` 不能被当成标题，
     * 否则整章的第一个场景会被切掉。
     */
    private fun headingOf(trimmed: String): String? {
        BRACKET_RE.matchEntire(trimmed)?.let { return JsText.trim(it.groupValues[1]) }
        SCENE_PREFIX_RE.matchEntire(trimmed)?.let { return JsText.trim(it.groupValues[1]) }
        HASH_RE.matchEntire(trimmed)?.let { return JsText.trim(it.groupValues[1]) }
        if (ORDINAL_RE.matchEntire(trimmed) != null) return trimmed
        LABELED_RE.matchEntire(trimmed)?.let { return JsText.trim(it.groupValues[1]) }
        SPACED_RE.matchEntire(trimmed)?.let {
            val tail = it.groupValues[1]
            if (tail.length <= 20 && !SENTENCE_END.containsMatchIn(tail)) return JsText.trim(tail)
        }
        return null
    }

    /** 分隔线 / 显式场景标题所在的行区间（用于编辑器里把它们高亮成「场景标记」）。 */
    fun markerLines(text: String): List<MatchRange> {
        val out = ArrayList<MatchRange>()
        var offset = 0
        for (raw in text.split("\n")) {
            val start = offset
            offset += raw.length + 1
            val trimmed = JsText.trim(raw)
            if (trimmed.isEmpty()) continue
            if (SEPARATOR_RE.matchEntire(trimmed) != null || headingOf(trimmed) != null) {
                out += MatchRange(start, start + raw.length)
            }
        }
        return out
    }

    private class Builder(var title: String, val explicit: Boolean, val from: Int, var to: Int)

    fun parseScenes(text: String): List<SceneBlock> {
        val blocks = ArrayList<Builder>()
        var current: Builder? = null
        var offset = 0
        for (raw in text.split("\n")) {
            val lineStart = offset
            val lineEnd = offset + raw.length
            val trimmed = JsText.trim(raw)
            offset = lineEnd + 1
            if (trimmed.isEmpty()) {
                current?.to = lineEnd
                continue
            }
            if (SEPARATOR_RE.matchEntire(trimmed) != null) {
                current?.let {
                    it.to = lineStart
                    blocks += it
                    current = null
                }
                continue
            }
            val heading = headingOf(trimmed)
            if (heading != null) {
                current?.let {
                    it.to = lineStart
                    blocks += it
                }
                current = Builder(
                    title = heading.ifEmpty { "第 ${blocks.size + 1} 场" },
                    explicit = true,
                    from = offset,
                    to = offset,
                )
                continue
            }
            val cur = current
            if (cur == null) {
                current = Builder(trimmed.take(18), explicit = false, from = lineStart, to = lineEnd)
            } else {
                cur.to = lineEnd
            }
        }
        current?.let { blocks += it }
        return blocks.mapIndexed { index, b ->
            val to = maxOf(b.to, b.from)
            SceneBlock(
                index = index,
                title = if (b.title.isEmpty()) "第 ${index + 1} 场" else b.title,
                from = b.from,
                to = to,
                words = WordCount.count(text.safeSlice(b.from, to)),
                explicit = b.explicit,
            )
        }
    }

    private fun String.safeSlice(from: Int, to: Int): String {
        val a = from.coerceIn(0, length)
        val b = to.coerceIn(a, length)
        return substring(a, b)
    }
}

data class GoalProgress(
    val words: Int,
    val target: Int,
    /** 0..1（target 为 0 时按 1 处理，界面不会显示空进度条）。 */
    val ratio: Double,
    val remaining: Int,
    val done: Boolean,
)

/** 目标进度：目标 <= 0 视为「没设目标」。 */
fun goalProgress(words: Int, target: Double): GoalProgress {
    val t = if (target.isFinite() && target > 0) kotlin.math.floor(target).toInt() else 0
    if (t == 0) return GoalProgress(words, 0, 1.0, 0, true)
    return GoalProgress(
        words = words,
        target = t,
        ratio = (words.toDouble() / t).coerceIn(0.0, 1.0),
        remaining = maxOf(0, t - words),
        done = words >= t,
    )
}
