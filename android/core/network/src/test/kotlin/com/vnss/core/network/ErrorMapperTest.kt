package com.vnss.core.network

import com.vnss.core.common.AppError
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

class ErrorMapperTest {

    @Test
    fun stringDetailBecomesMessage() {
        val e = ErrorMapper.fromHttp(401, """{"detail":"用户名或密码错误"}""")
        assertTrue(e is AppError.Unauthorized)
        assertEquals("用户名或密码错误", e.message)
    }

    @Test
    fun projectConflictCarriesServerTimestamp() {
        val body = """{"detail":{"code":"project_conflict","message":"该项目已在其他位置被修改。","serverUpdatedAt":"2026-10-03T12:00:00+00:00"}}"""
        val e = ErrorMapper.fromHttp(409, body) as AppError.Conflict
        assertEquals("2026-10-03T12:00:00+00:00", e.serverUpdatedAt)
        assertEquals("该项目已在其他位置被修改。", e.message)
    }

    @Test
    fun validationErrorsAreJoined() {
        val body = """{"detail":[{"loc":["body","password"],"msg":"String should have at least 8 characters"},{"loc":["body","email"],"msg":"field required"}]}"""
        val e = ErrorMapper.fromHttp(422, body)
        assertTrue(e is AppError.Http)
        assertTrue(e.message.contains("at least 8"))
        assertTrue(e.message.contains("field required"))
    }

    @Test
    fun lockedAndRateLimited() {
        assertTrue(ErrorMapper.fromHttp(423, """{"detail":"该章正被其他成员编辑"}""") is AppError.Locked)
        assertTrue(ErrorMapper.fromHttp(429, """{"detail":"过于频繁"}""") is AppError.RateLimited)
    }

    @Test
    fun emptyBodyFallsBackToDefaultText() {
        assertEquals("项目不存在或已被删除", ErrorMapper.fromHttp(404, null).message)
        assertEquals("服务端错误（502）", ErrorMapper.fromHttp(502, "").message)
    }

    @Test
    fun nonJsonBodyIsTruncatedNotCrashing() {
        val e = ErrorMapper.fromHttp(500, "<html>Bad Gateway</html>")
        assertTrue(e.message.contains("Bad Gateway"))
    }

    @Test
    fun ioExceptionIsNetworkAndRetryable() {
        val e = ErrorMapper.fromThrowable(IOException("boom"))
        assertTrue(e is AppError.Network)
        assertTrue(e.isRetryable)
    }

    @Test
    fun requestTimeoutKeepsItsMessage() {
        val e = ErrorMapper.fromThrowable(RequestTimeoutException("等了很久"))
        assertTrue(e is AppError.Timeout)
        assertEquals("等了很久", e.message)
        assertTrue(e.isRetryable)
    }

    @Test
    fun serverErrorsRetryableButClientErrorsNot() {
        assertTrue(ErrorMapper.fromHttp(503, null).isRetryable)
        assertTrue(!ErrorMapper.fromHttp(400, null).isRetryable)
        assertTrue(!ErrorMapper.fromHttp(403, null).isRetryable)
    }
}
