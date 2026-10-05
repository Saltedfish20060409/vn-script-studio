package com.vnss.feature.editor.check

/**
 * 笔误 / 标点体检——`frontend/src/lib/editorAssist.ts` 中 `lintProse` 的逐条移植。
 *
 * 规则刻意保守（宁可漏报也不误报）；每条结果都带原文片段、位置与依据。偏移量按 UTF-16 码元计，
 * 与 JS 的字符串索引一致，所以同一份夹具两端都能用同样的数字断言。
 * 改规则的流程：先改 Web 端 → 重新生成夹具 → 再改这里，直到 `WritingLocalCasesTest` 变绿。
 */
enum class IssueLevel { ERROR, WARN, INFO }

data class TextIssue(
    val code: String,
    val level: IssueLevel,
    val message: String,
    val offset: Int,
    val length: Int,
    /** 1 起算 */
    val line: Int,
    val snippet: String,
    val basis: String,
)

object ProseLinter {

    val RULE_BASIS: Map<String, String> = linkedMapOf(
        "quote_unbalanced" to "GB/T 15834-2011《标点符号用法》（引号、括号成对使用）",
        "quote_nested_level" to "GB/T 15834-2011《标点符号用法》（引号里面还要用引号时，外面用双引号、里面用单引号）",
        "title_mark_nested" to "GB/T 15834-2011《标点符号用法》（书名号里面还要用书名号时用单书名号）；W3C《中文排版需求》(clreq)",
        "punct_half_full_adjacent" to "GB/T 15834-2011《标点符号用法》（标点符号的写法）；W3C《中文排版需求》(clreq)（标点的比例与位置）",
        "punct_halfwidth_near_cjk" to "GB/T 15834-2011《标点符号用法》；CY/T 154-2017《中文出版物夹用英文的编辑规范》",
        "dash_ascii_double" to "GB/T 15834-2011《标点符号用法》（破折号）",
        "dash_single_em" to "GB/T 15834-2011《标点符号用法》（破折号占两个字的位置）",
        "dash_ascii_range" to "GB/T 15834-2011《标点符号用法》（连接号）；GB/T 15835-2011《出版物上数字用法》（数值范围）",
        "cjk_year_digits" to "GB/T 15835-2011《出版物上数字用法》（公历年份用阿拉伯数字）",
        "arabic_with_ji" to "GB/T 15835-2011《出版物上数字用法》（「几」表示约数时用汉字数字）",
        "arabic_dunhao_range" to "GB/T 15835-2011《出版物上数字用法》（相邻数字并列连用表示概数时用汉字、不用顿号）",
        "ellipsis_ascii_dots" to "GB/T 15834-2011《标点符号用法》（省略号）",
        "ellipsis_fullwidth_period" to "GB/T 15834-2011《标点符号用法》（省略号）",
        "ellipsis_with_deng" to "编辑规范补充规则（省略号与「等」不宜并用）——不是国标正文，故只报 info",
        "space_between_cjk" to "W3C《中文排版需求》(clreq)（中文正文的间距）；也可能是导入稿子带进来的",
        "trailing_space" to "无规范依据（纯清洁度）：行尾空格不影响阅读，只影响 diff 与导出",
        "typo_confusion" to "成语/固定搭配的通用写法（零歧义词表，见 lib/typoRules.ts）",
    )

    fun basisOf(code: String): String = RULE_BASIS[code].orEmpty()

    private const val CJK = "\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff\\u3040-\\u30ff\\uac00-\\ud7af"
    private val CJK_RE = Regex("[$CJK]")
    private const val SNIPPET_MAX = 24

    // ---- 小工具 -----------------------------------------------------------

    private fun lineOf(text: String, offset: Int): Int {
        var line = 1
        val end = minOf(offset, text.length)
        for (i in 0 until end) if (text[i] == '\n') line++
        return line
    }

    private fun snippetOf(text: String, offset: Int, length: Int): String {
        val from = offset.coerceIn(0, text.length)
        val to = (offset + maxOf(length, 1)).coerceIn(from, text.length)
        val raw = text.substring(from, to).replace("\n", "⏎")
        return if (raw.length > SNIPPET_MAX) raw.take(SNIPPET_MAX) + "…" else raw
    }

    private fun hasCjkNear(text: String, offset: Int, length: Int, radius: Int = 2): Boolean {
        val from = maxOf(0, offset - radius)
        val to = minOf(text.length, offset + length + radius)
        return from < to && CJK_RE.containsMatchIn(text.substring(from, to))
    }

    private fun issue(
        text: String,
        code: String,
        level: IssueLevel,
        message: String,
        offset: Int,
        length: Int,
    ) = TextIssue(
        code = code,
        level = level,
        message = message,
        offset = offset,
        length = length,
        line = lineOf(text, offset),
        snippet = snippetOf(text, offset, length),
        basis = basisOf(code),
    )

    private fun scan(
        text: String,
        re: Regex,
        level: IssueLevel,
        code: String,
        message: (MatchResult) -> String,
        accept: (MatchResult) -> Boolean = { true },
    ): List<TextIssue> = re.findAll(text)
        .filter { it.value.isNotEmpty() && accept(it) }
        .map { issue(text, code, level, message(it), it.range.first, it.value.length) }
        .toList()

    // ---- 引号配对 ---------------------------------------------------------

    private data class Para(val from: Int, val to: Int)

    /** 连续非空行算一段，空行分段。 */
    private fun paragraphs(text: String): List<Para> {
        val out = ArrayList<Para>()
        var from = -1
        var offset = 0
        for (line in text.split("\n")) {
            val empty = JsText.trim(line).isEmpty()
            if (!empty && from < 0) from = offset
            if (empty && from >= 0) {
                out += Para(from, offset)
                from = -1
            }
            offset += line.length + 1
        }
        if (from >= 0) out += Para(from, text.length)
        return out
    }

    private val QUOTE_PAIRS = listOf('「' to '」', '『' to '』', '“' to '”', '‘' to '’', '（' to '）')

    private fun count(s: String, ch: Char): Int {
        var n = 0
        for (c in s) if (c == ch) n++
        return n
    }

    private fun checkQuotes(text: String): List<TextIssue> {
        val issues = ArrayList<TextIssue>()
        for (para in paragraphs(text)) {
            val body = text.substring(para.from, para.to)
            for ((open, close) in QUOTE_PAIRS) {
                val opens = count(body, open)
                val closes = count(body, close)
                if (opens == closes) continue
                val first = body.indexOf(if (opens > closes) open else close)
                val offset = para.from + (if (first < 0) 0 else first)
                issues += issue(
                    text,
                    "quote_unbalanced",
                    IssueLevel.ERROR,
                    "引号不配对：这一段有 $opens 个「$open」、$closes 个「$close」，请检查漏写或多写",
                    offset,
                    1,
                )
            }
        }
        return issues
    }

    // ---- 嵌套层次 ---------------------------------------------------------

    private fun nestingPositions(line: String, open: Char, close: Char): List<Int> {
        var depth = 0
        val out = ArrayList<Int>()
        for (i in line.indices) {
            val ch = line[i]
            if (ch == open) {
                if (depth >= 1) out += i
                depth++
            } else if (ch == close && depth > 0) {
                depth--
            }
        }
        return out
    }

    private fun checkNesting(text: String): List<TextIssue> {
        val out = ArrayList<TextIssue>()
        var lineStart = 0
        for ((index, line) in text.split("\n").withIndex()) {
            fun push(code: String, at: Int, message: String) {
                val offset = lineStart + at
                out += TextIssue(
                    code = code,
                    level = IssueLevel.WARN,
                    message = message,
                    offset = offset,
                    length = 1,
                    line = index + 1,
                    snippet = snippetOf(text, offset, 1),
                    basis = basisOf(code),
                )
            }
            for (at in nestingPositions(line, '《', '》')) {
                push("title_mark_nested", at, "书名号里再用书名号时应改为单书名号「〈〉」")
            }
            for ((open, close) in listOf('“' to '”', '「' to '」')) {
                // 只在这一行里至少有两个开号时才判嵌套：只出现一个的是跨行对白，由配平规则管
                if (count(line, open) < 2) continue
                for (at in nestingPositions(line, open, close)) {
                    push("quote_nested_level", at, "引号里再用引号时应降一级（$open$close 里用单引号）")
                }
            }
            lineStart += line.length + 1
        }
        return out
    }

    // ---- 别字 -------------------------------------------------------------

    fun lintTypos(text: String): List<TextIssue> = TypoRules.findTypos(text).map { hit ->
        issue(text, "typo_confusion", IssueLevel.WARN, TypoRules.message(hit), hit.offset, hit.length)
    }

    // ---- 规则正则 ---------------------------------------------------------

    private val RE_HALF_FULL = Regex("[,.;:!?][，。；：！？]|[，。；：！？][,.;:!?]")
    private val RE_HALF_NEAR_CJK = Regex("[$CJK][,;:!?()]|[,;:!?()][$CJK]")
    private val RE_DASH_DOUBLE = Regex("(?<!-)--(?!-)")
    private val RE_EM_DASH = Regex("—+")
    private val RE_ASCII_ELLIPSIS = Regex("\\.{3,}")
    private val RE_FULLWIDTH_ELLIPSIS = Regex("。{3,}")
    private val RE_CJK_SPACE = Regex("[$CJK][ \\t]+[$CJK]")

    // JS 的 `$`（无 m 标志）只匹配输入末尾；Java 的 `$` 还会匹配末尾换行之前，所以用 \z
    private val RE_TRAILING_SPACE = Regex("[ \\t]+(?=\\n|\\z)")
    private val RE_DIGIT_RANGE = Regex("(?<=[0-9])-(?=[0-9])")
    private val RE_ELLIPSIS_DENG = Regex("…{2,}[ \\t]*等")
    private val RE_CJK_YEAR = Regex("[〇零一二三四五六七八九]{4}年")
    private val RE_ARABIC_JI = Regex("[0-9]+几")
    private val RE_DUNHAO_RANGE = Regex("(?<!第)[0-9]+、[0-9]+(?=[年月日天周人个次元米斤吨页条句])")

    /**
     * 确定性笔误 / 标点体检。结果按位置、规则名排序。
     */
    fun lintProse(text: String): List<TextIssue> {
        if (text.isEmpty()) return emptyList()
        val issues = ArrayList<TextIssue>()
        issues += checkQuotes(text)
        issues += scan(text, RE_HALF_FULL, IssueLevel.WARN, "punct_half_full_adjacent", {
            "同一个标点位置混用了半角与全角「${it.value}」，只留一种宽度（中文一般用全角）"
        })
        issues += scan(text, RE_HALF_NEAR_CJK, IssueLevel.WARN, "punct_halfwidth_near_cjk", {
            "中文里混用了半角标点「${it.value}」，中文标点通常写作 ，；：！？（）"
        })
        issues += scan(text, RE_DASH_DOUBLE, IssueLevel.WARN, "dash_ascii_double", {
            "用两个半角连字符 `--` 代替破折号了，中文破折号是 `——`"
        })
        issues += scan(
            text, RE_EM_DASH, IssueLevel.WARN, "dash_single_em",
            { "这个破折号只有一个 `—`，中文破折号通常成双写 `——`" },
            { it.value.length == 1 && hasCjkNear(text, it.range.first, 1) },
        )
        issues += scan(
            text, RE_ASCII_ELLIPSIS, IssueLevel.WARN, "ellipsis_ascii_dots",
            { "用半角句点写省略号了，中文省略号是 `……`（两个）" },
            { hasCjkNear(text, it.range.first, it.value.length) },
        )
        issues += scan(text, RE_FULLWIDTH_ELLIPSIS, IssueLevel.WARN, "ellipsis_fullwidth_period", {
            "用句号 `。。。` 代替省略号了，中文省略号是 `……`"
        })
        issues += scan(text, RE_CJK_SPACE, IssueLevel.INFO, "space_between_cjk", {
            "汉字之间多了空格（导入的稿子常见），确认是无意的就删掉"
        })
        issues += scan(text, RE_TRAILING_SPACE, IssueLevel.INFO, "trailing_space", { "行尾有多余空格" })
        issues += checkNesting(text)
        issues += scan(text, RE_DIGIT_RANGE, IssueLevel.INFO, "dash_ascii_range", {
            "起止数字之间按规范用一字线「—」或浪纹线「～」，不要用半角 -"
        })
        issues += scan(text, RE_ELLIPSIS_DENG, IssueLevel.INFO, "ellipsis_with_deng", {
            "省略号与「等」都表示列举未尽，通常留一个即可"
        })
        issues += scan(text, RE_CJK_YEAR, IssueLevel.INFO, "cjk_year_digits", {
            "公历年份按规范用阿拉伯数字（「2019 年」），汉字年份多见于书法/仿古文体"
        })
        issues += scan(text, RE_ARABIC_JI, IssueLevel.INFO, "arabic_with_ji", {
            "「几」表示约数时用汉字数字（「十几个人」），或用「多」（「10 多个人」）"
        })
        issues += scan(text, RE_DUNHAO_RANGE, IssueLevel.INFO, "arabic_dunhao_range", {
            "概数按规范用汉字且不用顿号（「三四年」）；若是并列编号，请在前面加「第」"
        })
        issues += lintTypos(text)
        return issues.sortedWith(compareBy<TextIssue> { it.offset }.thenBy { it.code })
    }

    fun countIssues(issues: List<TextIssue>): Map<IssueLevel, Int> =
        IssueLevel.entries.associateWith { level -> issues.count { it.level == level } }
}
