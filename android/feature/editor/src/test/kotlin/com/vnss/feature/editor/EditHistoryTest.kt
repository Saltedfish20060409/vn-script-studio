package com.vnss.feature.editor

import com.vnss.feature.editor.EditHistory.Snapshot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class EditHistoryTest {

    private fun s(t: String) = Snapshot(t, t.length, t.length)

    @Test
    fun rapidTypingIsOneUndoStep() {
        val h = EditHistory(coalesceMs = 800)
        h.record(s(""), 0)
        h.record(s("a"), 100)
        h.record(s("ab"), 200)
        assertEquals(s(""), h.undo(s("abc")))
        assertFalse(h.canUndo)
    }

    @Test
    fun pauseStartsNewStep() {
        val h = EditHistory(coalesceMs = 800)
        h.record(s(""), 0)
        h.record(s("a"), 100)
        h.record(s("ab"), 2_000)
        assertEquals(s("ab"), h.undo(s("abc")))
        assertEquals(s(""), h.undo(s("ab")))
        assertNull(h.undo(s("")))
    }

    @Test
    fun redoReplaysAndNewEditClearsRedo() {
        val h = EditHistory()
        h.record(s("a"), 0)
        val back = h.undo(s("ab"))!!
        assertEquals(s("a"), back)
        assertTrue(h.canRedo)
        assertEquals(s("ab"), h.redo(back))
        h.undo(s("ab"))
        h.record(s("a"), 10_000)
        assertFalse(h.canRedo)
    }

    @Test
    fun editAfterUndoAlwaysStartsNewStep() {
        val h = EditHistory(coalesceMs = 800)
        h.record(s(""), 0)
        h.undo(s("a"))
        h.record(s(""), 50) // 距上一次编辑只有 50ms，但撤销之后必须是新的一步
        assertTrue(h.canUndo)
    }

    @Test
    fun limitDropsOldestSteps() {
        val h = EditHistory(limit = 3, coalesceMs = 0)
        for (i in 0..9) h.record(s("t$i"), i * 10_000L)
        var n = 0
        while (h.undo(s("x")) != null) n++
        assertEquals(3, n)
    }
}
