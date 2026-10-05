package com.vnss.feature.projects

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SyncNoteTest {
    @Test
    fun nothingToReportIsSilent() {
        assertNull(ProjectsViewModel.syncNote(0, 0, 0))
    }

    @Test
    fun conflictsTakePriority() {
        assertTrue(ProjectsViewModel.syncNote(3, 1, 2)!!.contains("冲突"))
    }

    @Test
    fun mergedMentionsWebEdits() {
        assertTrue(ProjectsViewModel.syncNote(2, 1, 0)!!.contains("自动合并"))
    }

    @Test
    fun plainPush() {
        assertEquals("已同步 2 章。", ProjectsViewModel.syncNote(2, 0, 0))
    }
}
