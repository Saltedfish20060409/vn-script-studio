package com.vnss.feature.editor.check

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PairInputTest {

    @Test
    fun detectsSingleCharInsertAtCaret() {
        assertEquals("「", PairInput.detectTypedChar("他说", 2, 2, "他说「"))
        assertEquals("「", PairInput.detectTypedChar("他说", 1, 1, "他「说"))
    }

    @Test
    fun detectsSingleCharReplacingSelection() {
        assertEquals("“", PairInput.detectTypedChar("他说", 0, 2, "“"))
    }

    @Test
    fun pasteOrDeleteOrMultiCharIsNotATypedChar() {
        assertNull(PairInput.detectTypedChar("他说", 2, 2, "他说你好"))
        assertNull(PairInput.detectTypedChar("他说", 2, 2, "他"))
        assertNull(PairInput.detectTypedChar("他说", 2, 2, "他说"))
        // 光标处之外的内容变了（例如输入法改写了前文）
        assertNull(PairInput.detectTypedChar("他说", 2, 2, "她说「"))
    }

    @Test
    fun mobilePairsOnlyChinesePunctuation() {
        val edit = PairInput.applyMobile("他说", 2, 2, "「")!!
        assertEquals("他说「」", edit.text)
        assertEquals(3, edit.caret)
        // ASCII 引号 / 括号不自动配对，避免 don't 这类英文被误配
        assertNull(PairInput.applyMobile("don", 3, 3, "'"))
        assertNull(PairInput.applyMobile("f", 1, 1, "("))
    }

    @Test
    fun mobileSkipsOverExistingCloser() {
        val edit = PairInput.applyMobile("他说「你好」", 5, 5, "」")!!
        assertEquals("他说「你好」", edit.text)
        assertEquals(6, edit.caret)
    }

    @Test
    fun wrapsSelection() {
        val edit = PairInput.applyMobile("你好", 0, 2, "「")!!
        assertEquals("「你好」", edit.text)
        assertEquals(MatchRange(1, 3), edit.selection)
    }
}
