package com.vnss.feature.editor.check

data class PairEdit(
    val text: String,
    /** 处理完之后光标（或选区终点）应该在哪。 */
    val caret: Int,
    /** 有选区被包住时给出新的选区，方便继续输入。 */
    val selection: MatchRange? = null,
)

/**
 * 括号 / 引号自动配对——`editorAssist.ts` 中 `applyPairOnKey` 的移植。
 *
 * 三种情况：敲左半边且有选区 → 把选区包起来；敲左半边且无选区 → 插入一对、光标留在中间；
 * 敲右半边且右边正好是它 → 只把光标移过去（跳过）。其余返回 null，走输入框自己的路径。
 */
object PairInput {

    val PAIR_MAP: Map<String, String> = linkedMapOf(
        "「" to "」",
        "『" to "』",
        "“" to "”",
        "‘" to "’",
        "（" to "）",
        "【" to "】",
        "《" to "》",
        "〔" to "〕",
        "(" to ")",
        "[" to "]",
        "{" to "}",
        "\"" to "\"",
        "'" to "'",
    )

    /**
     * 手机端实际启用的左半边：只对中文成对标点自动配对。
     * ASCII 的 `'` `"` 在英文单词里（don't）会被误配对，手机键盘上也没有 Web 端那种「敲错能立刻看见」的反馈，所以不启用。
     */
    val MOBILE_OPENERS: Set<String> = setOf("「", "『", "“", "‘", "（", "【", "《", "〔")

    private val CLOSERS: Set<String> = PAIR_MAP.values.toSet()
    private val MOBILE_CLOSERS: Set<String> = MOBILE_OPENERS.mapNotNull { PAIR_MAP[it] }.toSet()

    /**
     * 手机输入框没有「按键事件」，只能比较前后文本：若 [newText] 恰好等于 [oldText] 把选区 `[start,end)`
     * 替换成单个字符的结果，返回这个字符，否则返回 null（粘贴、删除、多字输入都不算）。
     */
    fun detectTypedChar(oldText: String, start: Int, end: Int, newText: String): String? {
        if (start < 0 || end < start || end > oldText.length) return null
        if (newText.length != oldText.length - (end - start) + 1) return null
        if (!newText.startsWith(oldText.substring(0, start))) return null
        if (!newText.endsWith(oldText.substring(end))) return null
        return newText[start].toString()
    }

    /** 手机端入口：只处理中文成对标点（见 [MOBILE_OPENERS]）及其右半边的「跳过」。 */
    fun applyMobile(text: String, start: Int, end: Int, key: String): PairEdit? {
        if (key !in MOBILE_OPENERS && key !in MOBILE_CLOSERS) return null
        return applyPairOnKey(text, start, end, key)
    }

    fun applyPairOnKey(text: String, start: Int, end: Int, key: String): PairEdit? {
        if (key.length != 1) return null
        val close = PAIR_MAP[key]
        if (close != null) {
            if (end > start) {
                val wrapped = text.substring(0, start) + key + text.substring(start, end) + close + text.substring(end)
                return PairEdit(wrapped, caret = end + 2, selection = MatchRange(start + 1, end + 1))
            }
            return PairEdit(text.substring(0, start) + key + close + text.substring(start), caret = start + 1)
        }
        if (key in CLOSERS && end == start && text.getOrNull(start)?.toString() == key) {
            return PairEdit(text, caret = start + 1)
        }
        return null
    }
}
