package com.vnss.feature.editor.check

import com.vnss.core.common.WordCount
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 跨端一致性：对 `shared/test-fixtures/writing_local_cases.json` 逐条断言。
 *
 * 夹具由 Web 端实现现算生成（`frontend/scripts/gen_writing_local_cases.ts`），所以这里测的是
 * 「Kotlin 移植版与 Web 端实现行为一致」，而不是「与某个人手写的期望一致」。
 * 这个测试红了，说明两端已经分叉：要么 Web 端改了规则没同步到这里，要么移植有 bug。
 */
class WritingLocalCasesTest {

    private val fixture: JsonObject = run {
        val stream = checkNotNull(javaClass.classLoader?.getResourceAsStream("writing_local_cases.json")) {
            "找不到夹具 writing_local_cases.json（feature/editor 的 test resources 应指向 shared/test-fixtures）"
        }
        Json.parseToJsonElement(stream.bufferedReader(Charsets.UTF_8).readText()).jsonObject
    }

    private fun list(key: String): List<JsonObject> = fixture.getValue(key).jsonArray.map { it.jsonObject }
    private fun JsonObject.s(key: String) = getValue(key).jsonPrimitive.content
    private fun JsonObject.i(key: String) = getValue(key).jsonPrimitive.int
    private fun JsonObject.o(key: String) = getValue(key).jsonObject

    private fun options(o: JsonObject): FindOptions {
        val opts = o.o("options")
        return FindOptions(
            caseSensitive = opts["caseSensitive"]?.jsonPrimitive?.boolean ?: false,
            regex = opts["regex"]?.jsonPrimitive?.boolean ?: false,
        )
    }

    private fun range(o: JsonObject) = MatchRange(o.i("from"), o.i("to"))

    private fun ranges(e: JsonElement): List<MatchRange>? =
        if (e is JsonNull) null else e.jsonArray.map { range(it.jsonObject) }

    // ------------------------------------------------------------------ 常量

    @Test
    fun sceneSeparatorMatches() {
        assertEquals(fixture.s("sceneSeparator"), SCENE_SEPARATOR)
    }

    @Test
    fun ruleBasisMatchesWebExactly() {
        val expected = fixture.o("ruleBasis").mapValues { it.value.jsonPrimitive.content }
        assertEquals(expected, ProseLinter.RULE_BASIS)
    }

    @Test
    fun pairMapMatchesWeb() {
        val expected = fixture.o("pairMap").mapValues { it.value.jsonPrimitive.content }
        assertEquals(expected, PairInput.PAIR_MAP)
    }

    @Test
    fun typoRulesMatchWebInOrder() {
        val expected = list("typoRules").map { Triple(it.s("wrong"), it.s("right"), it.s("kind")) }
        val actual = TypoRules.RULES.map { Triple(it.wrong, it.right, it.kind.label) }
        assertEquals(expected, actual)
    }

    // ------------------------------------------------------------------ 字数

    @Test
    fun wordCount() {
        for (c in list("wordCount")) {
            assertEquals("字数：「${c.s("text")}」", c.i("count"), WordCount.count(c.s("text")))
        }
    }

    @Test
    fun formatWords() {
        for (c in list("formatWords")) {
            assertEquals("${c.i("words")}", c.s("text"), WordCount.format(c.i("words")))
        }
    }

    // ------------------------------------------------------------------ 体检

    @Test
    fun lintProse() {
        for (c in list("lintProse")) {
            val text = c.s("text")
            val expected = c.getValue("issues").jsonArray.map { it.jsonObject }
            val actual = ProseLinter.lintProse(text)
            assertEquals(
                "「$text」的命中条数；实际：${actual.map { it.code + "@" + it.offset }}",
                expected.size,
                actual.size,
            )
            expected.zip(actual).forEach { (e, a) ->
                val ctx = "「$text」/${e.s("code")}"
                assertEquals(ctx, e.s("code"), a.code)
                assertEquals(ctx, e.s("level").uppercase(), a.level.name)
                assertEquals("$ctx message", e.s("message"), a.message)
                assertEquals("$ctx offset", e.i("offset"), a.offset)
                assertEquals("$ctx length", e.i("length"), a.length)
                assertEquals("$ctx line", e.i("line"), a.line)
                assertEquals("$ctx snippet", e.s("snippet"), a.snippet)
                assertEquals("$ctx basis", e.s("basis"), a.basis)
            }
        }
    }

    // ------------------------------------------------------------------ 查找替换

    @Test
    fun findMatches() {
        for (c in list("findMatches")) {
            val actual = FindReplace.findMatches(c.s("text"), c.s("query"), options(c))
            val expected = ranges(c.getValue("ranges"))
            assertEquals("查找 ${c.s("query")} in ${c.s("text")}", expected, actual)
        }
    }

    @Test
    fun replaceAll() {
        for (c in list("replaceAll")) {
            val r = FindReplace.replaceAll(c.s("text"), c.s("query"), c.s("replacement"), options(c))
            val expected = c.o("result")
            val ctx = "替换 ${c.s("query")} → ${c.s("replacement")} in ${c.s("text")}"
            assertEquals(ctx, expected.s("text"), r.text)
            assertEquals(ctx, expected.i("count"), r.count)
        }
    }

    @Test
    fun expandReplacement() {
        for (c in list("expandReplacement")) {
            val actual = FindReplace.expandReplacement(
                c.s("text"),
                range(c.o("range")),
                c.s("query"),
                c.s("replacement"),
                options(c),
            )
            assertEquals("展开 ${c.s("replacement")}", c.s("result"), actual)
        }
    }

    @Test
    fun nextMatch() {
        for (c in list("nextMatch")) {
            val rs = ranges(c.getValue("ranges")).orEmpty()
            val actual = FindReplace.nextMatch(rs, c.i("caret"), c.i("direction"))
            val expected = c.getValue("result").let { if (it is JsonNull) null else range(it.jsonObject) }
            assertEquals("next $rs caret=${c.i("caret")} dir=${c.i("direction")}", expected, actual)
        }
    }

    @Test
    fun replaceRange() {
        for (c in list("replaceRange")) {
            assertEquals(
                "replaceRange ${c.s("text")}",
                c.s("result"),
                FindReplace.replaceRange(c.s("text"), c.i("from"), c.i("to"), c.s("replacement")),
            )
        }
    }

    // ------------------------------------------------------------------ 配对

    @Test
    fun applyPairOnKey() {
        for (c in list("applyPairOnKey")) {
            val actual = PairInput.applyPairOnKey(c.s("text"), c.i("start"), c.i("end"), c.s("key"))
            val ctx = "pair ${c.s("key")} in ${c.s("text")}"
            val expected = c.getValue("result")
            if (expected is JsonNull) {
                assertNull(ctx, actual)
                continue
            }
            val e = expected.jsonObject
            assertTrue(ctx, actual != null)
            assertEquals(ctx, e.s("text"), actual!!.text)
            assertEquals(ctx, e.i("caret"), actual.caret)
            val sel = e["selection"]?.takeIf { it !is JsonNull }?.jsonObject?.let { range(it) }
            assertEquals(ctx, sel, actual.selection)
        }
    }

    // ------------------------------------------------------------------ 分场 / 目标

    @Test
    fun parseScenes() {
        for (c in list("parseScenes")) {
            val text = c.s("text")
            val expected = c.getValue("scenes").jsonArray.map { it.jsonObject }
            val actual = SceneParser.parseScenes(text)
            assertEquals("分场数：「$text」", expected.size, actual.size)
            expected.zip(actual).forEach { (e, a) ->
                val ctx = "「$text」第 ${e.i("index")} 场"
                assertEquals(ctx, e.i("index"), a.index)
                assertEquals("$ctx title", e.s("title"), a.title)
                assertEquals("$ctx from", e.i("from"), a.from)
                assertEquals("$ctx to", e.i("to"), a.to)
                assertEquals("$ctx words", e.i("words"), a.words)
                assertEquals("$ctx explicit", e.getValue("explicit").jsonPrimitive.boolean, a.explicit)
            }
        }
    }

    @Test
    fun goalProgress() {
        for (c in list("goalProgress")) {
            val target = c.getValue("target").jsonPrimitive.double
            val actual = goalProgress(c.i("words"), target)
            val e = c.o("result")
            val ctx = "goal ${c.i("words")}/$target"
            assertEquals(ctx, e.i("target"), actual.target)
            assertEquals(ctx, e.getValue("ratio").jsonPrimitive.double, actual.ratio, 1e-9)
            assertEquals(ctx, e.i("remaining"), actual.remaining)
            assertEquals(ctx, e.getValue("done").jsonPrimitive.boolean, actual.done)
        }
    }
}
