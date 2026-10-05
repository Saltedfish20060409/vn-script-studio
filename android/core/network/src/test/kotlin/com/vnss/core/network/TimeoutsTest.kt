package com.vnss.core.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import java.io.File

/**
 * 守卫：Kotlin 侧的超时预算必须与 Web 前端 `timeouts.ts` 逐项一致。
 * 任何一边改数而不改另一边会红——与前端 `timeouts.test.ts` 直接读后端源码是同一思路。
 */
class TimeoutsTest {

    private val tsFile = File("../../../frontend/src/api/timeouts.ts")

    private fun parseTsBudgets(): Map<String, Long> {
        val src = tsFile.readText()
        val start = src.indexOf("export const TIMEOUTS = {")
        val end = src.indexOf("} as const;", start)
        require(start >= 0 && end > start) { "找不到 TIMEOUTS 定义，timeouts.ts 结构变了？" }
        val block = src.substring(start, end)
        return Regex("""^\s{2}(\w+):\s*([\d_]+),""", RegexOption.MULTILINE)
            .findAll(block)
            .associate { it.groupValues[1] to it.groupValues[2].replace("_", "").toLong() }
    }

    @Test
    fun budgetsMatchWebFrontend() {
        assumeTrue("前端源码不在工作区（稀疏检出），跳过", tsFile.exists())
        val ts = parseTsBudgets()
        val expected = mapOf(
            "auth" to Timeouts.AUTH_MS,
            "fast" to Timeouts.FAST_MS,
            "probe" to Timeouts.PROBE_MS,
            "upload" to Timeouts.UPLOAD_MS,
            "quick" to Timeouts.QUICK_MS,
            "chat" to Timeouts.CHAT_MS,
            "write" to Timeouts.WRITE_MS,
            "long" to Timeouts.LONG_MS,
            "batch" to Timeouts.BATCH_MS,
        )
        assertEquals("TIMEOUTS 档位集合应一致", expected.keys, ts.keys)
        expected.forEach { (name, ms) -> assertEquals("档位 $name", ts.getValue(name), ms) }
    }

    @Test
    fun jobPollCoversBatchBudget() {
        // 与前端注释一致：轮询预算必须 >= batch，否则「作业还在跑但结果拿不到」
        assertTrue(Timeouts.JOB_POLL_MS >= Timeouts.BATCH_MS)
    }

    @Test
    fun streamIdleCoversMissedHeartbeats() {
        // 后端心跳 15–20s；至少容忍连续 3 次丢失
        assertTrue(Timeouts.STREAM_IDLE_MS >= 3 * 20_000L)
    }

    @Test
    fun llmBudgetsGetModelWording() {
        assertTrue(com.vnss.core.network.interceptor.TimeoutInterceptor.isLlmBudget(Timeouts.QUICK_MS))
        assertTrue(com.vnss.core.network.interceptor.TimeoutInterceptor.isLlmBudget(Timeouts.PROBE_MS))
        assertTrue(!com.vnss.core.network.interceptor.TimeoutInterceptor.isLlmBudget(Timeouts.UPLOAD_MS))
        assertTrue(!com.vnss.core.network.interceptor.TimeoutInterceptor.isLlmBudget(Timeouts.AUTH_MS))
    }

    @Test
    fun humanize() {
        assertEquals("30 秒", Timeouts.humanize(30_000))
        assertEquals("5 分钟", Timeouts.humanize(300_000))
        assertEquals("5.8 分钟", Timeouts.humanize(350_000))
    }
}
