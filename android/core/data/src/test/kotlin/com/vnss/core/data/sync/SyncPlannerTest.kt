package com.vnss.core.data.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SyncPlannerTest {
    @Test
    fun newChapterUploadsLocal() {
        val d = SyncPlanner.decide("a", "t", "a plus", "t", remoteProse = null, remoteTitle = null)
        assertEquals(SyncPlanner.Decision.UploadLocal, d)
    }

    @Test
    fun remoteUnchangedUploadsLocal() {
        val d = SyncPlanner.decide("base", "t", "mine", "t", "base", "t")
        assertEquals(SyncPlanner.Decision.UploadLocal, d)
    }

    @Test
    fun equalIsAlreadySynced() {
        val d = SyncPlanner.decide("b", "t", "x", "t", "x", "t")
        assertEquals(SyncPlanner.Decision.AlreadyEqual, d)
    }

    @Test
    fun nonOverlappingParagraphsMerge() {
        val base = "A\n\nB\n\nC"
        val local = "A'\n\nB\n\nC"
        val remote = "A\n\nB\n\nC'"
        val d = SyncPlanner.decide(base, "t", local, "t", remote, "t")
        assertTrue(d is SyncPlanner.Decision.UploadMerged)
        assertEquals("A'\n\nB\n\nC'", (d as SyncPlanner.Decision.UploadMerged).prose)
    }

    @Test
    fun overlappingParagraphsConflict() {
        val d = SyncPlanner.decide("hello", "t", "local", "t", "remote", "t")
        assertEquals(SyncPlanner.Decision.Conflict, d)
    }

    @Test
    fun keepBothJoinsBothVersions() {
        val text = SyncPlanner.keepBoth("手机稿", "网页稿")
        assertTrue(text.contains("手机稿"))
        assertTrue(text.contains("网页稿"))
        assertTrue(text.contains("网页端版本"))
    }
}
