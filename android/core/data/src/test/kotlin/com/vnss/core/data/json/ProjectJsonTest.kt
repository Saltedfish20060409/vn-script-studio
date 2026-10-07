package com.vnss.core.data.json

import com.vnss.core.network.VnssJson
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ProjectJsonTest {
    @Test
    fun overlayKeepsUnknownFields() {
        val raw = """{"id":"c1","title":"旧","blocks":[{"type":"dialogue"}],"nlRpyMap":{"version":1}}"""
        val entity = ProjectJson.newLocalChapter("c1", "p", "旧", 0, 0).copy(rawJson = raw, title = "新", prose = "正文")
        val out = ProjectJson.overlayForUpload(entity)
        assertEquals("新", out.str("title"))
        assertEquals("正文", out.str("prose"))
        assertTrue(out.containsKey("blocks"))
        assertTrue(out.containsKey("nlRpyMap"))
    }

    @Test
    fun scriptOnlyWhenBlocksExistWithoutProse() {
        val ch = VnssJson.parseToJsonElement(
            """{"id":"c1","title":"x","blocks":[{"type":"say"}],"prose":""}""",
        ).jsonObject
        val entity = ProjectJson.chapterFromServer("p", 0, ch, 1L)
        assertTrue(entity.scriptOnly)
        assertFalse(entity.rawJson.contains("\"prose\""))
    }

    @Test
    fun replaceChaptersAppendsNew() {
        val root = VnssJson.parseToJsonElement(
            """{"id":"p","title":"t","chapters":[{"id":"a","title":"A"}]}""",
        ).jsonObject
        val added = buildJsonObject {
            put("id", "b")
            put("title", "B")
            put("prose", "hi")
        }
        val next = ProjectJson.replaceChapters(root, mapOf("b" to added))
        assertEquals(2, next.arr("chapters")?.size)
    }

    @Test
    fun ledgerParsesForeshadowStatus() {
        val ledger = """{"foreshadows":[{"id":"1","hook":"刀","plantedChapter":"c1","status":"open"}]}"""
        val index = """[{"chapterId":"c1","title":"一","synopsis":"s"}]"""
        val parsed = ProjectJson.parseLedger(ledger, index, mapOf("c1" to "一"))
        assertEquals(1, parsed.digests.size)
        assertEquals("刀", parsed.foreshadows.single().hook)
        assertFalse(parsed.foreshadows.single().isPaid)
    }
}
