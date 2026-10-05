package com.vnss.feature.editor.check

/**
 * 与 JavaScript 字符串语义对齐的小工具。
 *
 * Kotlin 的 `trim()` / Java 正则的 `\s` 与 JS 的空白集合不完全相同（JS 把 NBSP、BOM 算空白，
 * Kotlin 的 `isWhitespace` 不算 NBSP）。这里的规则要和 Web 端逐字符一致，所以统一用 JS 的集合。
 */
internal object JsText {

    /** ECMAScript WhiteSpace + LineTerminator。 */
    private const val WS_CHARS =
        "\u0009\u000A\u000B\u000C\u000D\u0020\u00A0\u1680\u2000\u2001\u2002\u2003\u2004\u2005" +
            "\u2006\u2007\u2008\u2009\u200A\u2028\u2029\u202F\u205F\u3000\uFEFF"

    fun isWhitespace(c: Char): Boolean = WS_CHARS.indexOf(c) >= 0

    fun trim(s: String): String {
        var start = 0
        var end = s.length
        while (start < end && isWhitespace(s[start])) start++
        while (end > start && isWhitespace(s[end - 1])) end--
        return s.substring(start, end)
    }

    /** 正则里替代 `\s` / `\S` 的字符类（Java 的 `\s` 默认只认 ASCII 空白）。 */
    const val WS_CLASS =
        "[\\t\\n\\u000B\\f\\r \\u00A0\\u1680\\u2000-\\u200A\\u2028\\u2029\\u202F\\u205F\\u3000\\uFEFF]"
    const val NON_WS_CLASS =
        "[^\\t\\n\\u000B\\f\\r \\u00A0\\u1680\\u2000-\\u200A\\u2028\\u2029\\u202F\\u205F\\u3000\\uFEFF]"
}
