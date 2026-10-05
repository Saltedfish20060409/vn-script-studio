package com.vnss.core.common

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ThreeWayMergeTest {

    private fun lines(vararg s: String) = s.joinToString("\n")

    private fun clean(base: String, local: String, remote: String): String {
        val r = ThreeWayMerge.merge(base, local, remote)
        assertTrue("应当能自动合并，实际：$r", r is ThreeWayMerge.Result.Clean)
        return (r as ThreeWayMerge.Result.Clean).text
    }

    @Test
    fun identicalSidesNeedNoMerge() {
        assertEquals("a", clean("x", "a", "a"))
    }

    @Test
    fun onlyLocalChanged() {
        val base = lines("一", "二", "三")
        assertEquals(lines("一", "二改", "三"), clean(base, lines("一", "二改", "三"), base))
    }

    @Test
    fun onlyRemoteChanged() {
        val base = lines("一", "二", "三")
        assertEquals(lines("一", "二", "三改"), clean(base, base, lines("一", "二", "三改")))
    }

    @Test
    fun disjointEditsAreCombined() {
        val base = lines("第一段", "第二段", "第三段", "第四段")
        val local = lines("第一段（手机改）", "第二段", "第三段", "第四段")
        val remote = lines("第一段", "第二段", "第三段", "第四段（网页改）")
        assertEquals(
            lines("第一段（手机改）", "第二段", "第三段", "第四段（网页改）"),
            clean(base, local, remote),
        )
    }

    @Test
    fun insertionsInDifferentPlacesAreCombined() {
        val base = lines("A", "B", "C")
        val local = lines("A", "手机新增", "B", "C")
        val remote = lines("A", "B", "C", "网页新增")
        assertEquals(lines("A", "手机新增", "B", "C", "网页新增"), clean(base, local, remote))
    }

    @Test
    fun bothSidesMakeSameEditPlusDisjointEdits() {
        // 中间一处两边改得一样，其余各改各的；用不变的 x/y 行隔开，保证三处互不相邻
        val base = lines("A", "x", "B", "y", "C")
        val local = lines("A1", "x", "B2", "y", "C")
        val remote = lines("A", "x", "B2", "y", "C3")
        assertEquals(lines("A1", "x", "B2", "y", "C3"), clean(base, local, remote))
    }

    @Test
    fun adjacentEditsAreTreatedAsConflict() {
        // 与 git 一致：相邻（中间没有稳定锚点）的改动不自动拼接，宁可让用户看一眼
        val base = lines("A", "B", "C")
        val local = lines("A1", "B2", "C")
        val remote = lines("A", "B2", "C3")
        assertTrue(ThreeWayMerge.merge(base, local, remote) is ThreeWayMerge.Result.Conflict)
    }

    @Test
    fun overlappingEditsConflict() {
        val base = lines("A", "B", "C")
        val local = lines("A", "手机的B", "C")
        val remote = lines("A", "网页的B", "C")
        val r = ThreeWayMerge.merge(base, local, remote)
        assertTrue(r is ThreeWayMerge.Result.Conflict)
        assertEquals(1, (r as ThreeWayMerge.Result.Conflict).hunks)
    }

    @Test
    fun deleteVersusEditConflicts() {
        val base = lines("A", "B", "C")
        val local = lines("A", "C") // 手机删掉了 B
        val remote = lines("A", "B改", "C") // 网页改了 B
        assertTrue(ThreeWayMerge.merge(base, local, remote) is ThreeWayMerge.Result.Conflict)
    }

    @Test
    fun bothInsertDifferentTextAtSamePlaceConflicts() {
        val base = lines("A", "C")
        val local = lines("A", "手机插入", "C")
        val remote = lines("A", "网页插入", "C")
        assertTrue(ThreeWayMerge.merge(base, local, remote) is ThreeWayMerge.Result.Conflict)
    }

    @Test
    fun emptyBaseWithDifferentSidesConflicts() {
        // 本地新建章节与服务端同 id 章节同时有内容：不应静默拼接
        assertTrue(ThreeWayMerge.merge("", "手机", "网页") is ThreeWayMerge.Result.Conflict)
    }

    @Test
    fun largeDocumentWithFarApartEditsMergesQuickly() {
        val base = (1..3000).joinToString("\n") { "第${it}段正文内容。" }
        val local = base.replaceFirst("第10段正文内容。", "第10段（手机改）。")
        val remote = base.replaceFirst("第2990段正文内容。", "第2990段（网页改）。")
        val merged = clean(base, local, remote)
        assertTrue(merged.contains("第10段（手机改）。"))
        assertTrue(merged.contains("第2990段（网页改）。"))
        assertEquals(base.split("\n").size, merged.split("\n").size)
    }

    @Test
    fun oversizedDiffFallsBackToConflictInsteadOfExhaustingMemory() {
        // 两边把全部行都改了且行数很大：LCS 矩阵超限，应降级为冲突而不是 OOM
        val base = (1..3000).joinToString("\n") { "base$it" }
        val local = (1..3000).joinToString("\n") { "local$it" }
        val remote = (1..3000).joinToString("\n") { "remote$it" }
        assertTrue(ThreeWayMerge.merge(base, local, remote) is ThreeWayMerge.Result.Conflict)
    }
}
