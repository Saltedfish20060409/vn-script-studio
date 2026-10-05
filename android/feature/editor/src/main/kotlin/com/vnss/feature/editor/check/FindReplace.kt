package com.vnss.feature.editor.check

import java.util.Locale
import java.util.regex.Pattern
import java.util.regex.PatternSyntaxException

data class MatchRange(val from: Int, val to: Int)

data class FindOptions(val caseSensitive: Boolean = false, val regex: Boolean = false)

data class ReplaceAllResult(val text: String, val count: Int)

/**
 * 查找 / 替换——`editorAssist.ts` 对应函数的移植。
 *
 * 与 Web 端的两处差异（都是正则方言导致，非正则模式完全一致）：
 * 1. 正则按 Java 语法编译，写错时同样返回 null（界面提示「正则写错了」），个别 JS 能过而 Java 不认的写法会被判为错误；
 * 2. 替换模板里的 `$<name>` 命名组引用不展开（`$1`、`$&`、`$$`、`` $` ``、`$'` 与 JS 语义一致）。
 */
object FindReplace {

    private fun compile(query: String, options: FindOptions): Regex? = try {
        val flags = if (options.caseSensitive) 0 else Pattern.CASE_INSENSITIVE or Pattern.UNICODE_CASE
        Pattern.compile(query, flags).toRegex()
    } catch (e: PatternSyntaxException) {
        null
    }

    /** 找全部命中。正则非法返回 null（调用方显示提示）；空查询返回空列表。 */
    fun findMatches(text: String, query: String, options: FindOptions = FindOptions()): List<MatchRange>? {
        if (query.isEmpty()) return emptyList()
        if (options.regex) {
            val rx = compile(query, options) ?: return null
            return rx.findAll(text).map { MatchRange(it.range.first, it.range.first + it.value.length) }.toList()
        }
        val haystack = if (options.caseSensitive) text else text.lowercase(Locale.ROOT)
        val needle = if (options.caseSensitive) query else query.lowercase(Locale.ROOT)
        val out = ArrayList<MatchRange>()
        var at = haystack.indexOf(needle)
        while (at >= 0) {
            out += MatchRange(at, at + needle.length)
            at = haystack.indexOf(needle, at + maxOf(needle.length, 1))
        }
        return out
    }

    /** 在指定区间替换；越界会被夹到文本范围内。 */
    fun replaceRange(text: String, from: Int, to: Int, replacement: String): String {
        val a = maxOf(0, minOf(from, to, text.length))
        val b = maxOf(0, minOf(maxOf(from, to), text.length))
        return text.substring(0, a) + replacement + text.substring(b)
    }

    /** 全部替换；非正则模式一律字面替换（写 `$1` 就是想写 `$1`）。 */
    fun replaceAll(
        text: String,
        query: String,
        replacement: String,
        options: FindOptions = FindOptions(),
    ): ReplaceAllResult {
        val ranges = findMatches(text, query, options)
        if (ranges.isNullOrEmpty()) return ReplaceAllResult(text, 0)
        if (options.regex) {
            val rx = compile(query, options) ?: return ReplaceAllResult(text, 0)
            val sb = StringBuilder()
            var last = 0
            for (m in rx.findAll(text)) {
                sb.append(text, last, m.range.first)
                sb.append(expandTemplate(m, replacement, text))
                last = m.range.first + m.value.length
            }
            sb.append(text, last, text.length)
            return ReplaceAllResult(sb.toString(), ranges.size)
        }
        var out = text
        for (i in ranges.indices.reversed()) {
            out = replaceRange(out, ranges[i].from, ranges[i].to, replacement)
        }
        return ReplaceAllResult(out, ranges.size)
    }

    /**
     * 「替换这一处」用的展开：只在命中区间内跑一次替换，使正则模式下的 `$1` 与「全部替换」一致。
     */
    fun expandReplacement(
        text: String,
        range: MatchRange,
        query: String,
        replacement: String,
        options: FindOptions = FindOptions(),
    ): String {
        if (!options.regex) return replacement
        val rx = compile(query, options) ?: return replacement
        val a = range.from.coerceIn(0, text.length)
        val b = range.to.coerceIn(a, text.length)
        val slice = text.substring(a, b)
        val m = rx.find(slice) ?: return slice
        return slice.substring(0, m.range.first) +
            expandTemplate(m, replacement, slice) +
            slice.substring(m.range.first + m.value.length)
    }

    /** 找下一个命中：从 caret 往后找，到末尾回绕。 */
    fun nextMatch(ranges: List<MatchRange>, caret: Int, direction: Int = 1): MatchRange? {
        if (ranges.isEmpty()) return null
        if (direction == 1) return ranges.firstOrNull { it.from > caret } ?: ranges.first()
        return ranges.lastOrNull { it.to < caret } ?: ranges.last()
    }

    /** 按 ECMAScript 的 GetSubstitution 规则展开替换模板（不含命名组）。 */
    internal fun expandTemplate(m: MatchResult, template: String, input: String): String {
        val groupCount = m.groups.size - 1
        val sb = StringBuilder()
        var i = 0
        while (i < template.length) {
            val c = template[i]
            if (c != '$' || i + 1 >= template.length) {
                sb.append(c)
                i++
                continue
            }
            val next = template[i + 1]
            when {
                next == '$' -> { sb.append('$'); i += 2 }
                next == '&' -> { sb.append(m.value); i += 2 }
                next == '`' -> { sb.append(input, 0, m.range.first); i += 2 }
                next == '\'' -> { sb.append(input, m.range.first + m.value.length, input.length); i += 2 }
                next in '0'..'9' -> {
                    val d1 = next - '0'
                    val d2 = template.getOrNull(i + 2)?.takeIf { it in '0'..'9' }?.minus('0')
                    val two = if (d2 != null) d1 * 10 + d2 else -1
                    when {
                        two in 1..groupCount -> { sb.append(m.groups[two]?.value.orEmpty()); i += 3 }
                        d1 in 1..groupCount -> { sb.append(m.groups[d1]?.value.orEmpty()); i += 2 }
                        else -> { sb.append('$'); i++ }
                    }
                }
                else -> { sb.append('$'); i++ }
            }
        }
        return sb.toString()
    }
}
