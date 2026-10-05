package com.vnss.core.common

/**
 * 字数统计——与后端 `app/services/writing_stats.py`、前端 `lib/wordCount.ts` 同一套口径：
 *
 * - 汉字（U+4E00..U+9FFF）逐字计数；
 * - 拉丁字母 / 数字按「连续一串算一个词」计数；
 * - 一章优先数 `prose`，正文为空才回落到脚本 blocks（blocks 的统计在服务端，移动端只读 prose）。
 *
 * 三端的一致性由 `shared/test-fixtures/writing_local_cases.json` 钉住。
 */
object WordCount {

    fun count(text: String?): Int {
        if (text.isNullOrEmpty()) return 0
        var cjk = 0
        var latinWords = 0
        var inLatin = false
        for (ch in text) {
            when {
                ch in '\u4e00'..'\u9fff' -> {
                    cjk++
                    inLatin = false
                }
                isLatinOrDigit(ch) -> {
                    if (!inLatin) latinWords++
                    inLatin = true
                }
                else -> inLatin = false
            }
        }
        return cjk + latinWords
    }

    /** 与正则 `[A-Za-z0-9]+` 严格一致：不能用 Char.isLetterOrDigit（会把全角字母、假名算进去）。 */
    private fun isLatinOrDigit(ch: Char): Boolean =
        ch in 'A'..'Z' || ch in 'a'..'z' || ch in '0'..'9'

    /** 人看的字数：12345 → 1.2万。 */
    fun format(words: Int): String {
        if (words < 10_000) return words.toString()
        val wan = words / 10_000.0
        if (wan >= 10) return "${Math.round(wan)}万"
        // 与 JS 的 toFixed(1) 对齐：按 double 的精确二进制值四舍五入（1.15 实际是 1.1499…，结果是 1.1 而不是 1.2）
        val rounded = java.math.BigDecimal(wan).setScale(1, java.math.RoundingMode.HALF_UP).toPlainString()
        return "${rounded}万"
    }
}
