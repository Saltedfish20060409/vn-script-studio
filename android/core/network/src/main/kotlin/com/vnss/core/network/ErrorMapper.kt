package com.vnss.core.network

import com.vnss.core.common.AppError
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import retrofit2.HttpException
import java.io.IOException
import java.net.SocketTimeoutException

/** 请求超时（OkHttp 层抛出，保证是 IOException，避免在 OkHttp 调度线程上崩溃）。 */
class RequestTimeoutException(message: String, cause: Throwable? = null) : IOException(message, cause)

/**
 * 把底层异常翻译成 [AppError]。
 *
 * FastAPI 的错误体有三种形态，都要能读出「人话」：
 * - `{"detail": "用户名或密码错误"}`
 * - `{"detail": {"code": "project_conflict", "message": "…", "serverUpdatedAt": "…"}}`
 * - 422 校验错误：`{"detail": [{"loc": [...], "msg": "…"}]}`
 */
object ErrorMapper {

    private val json = Json { ignoreUnknownKeys = true }

    fun fromThrowable(t: Throwable): AppError = when (t) {
        is AppError -> t
        is HttpException -> fromHttp(t.code(), runCatching { t.response()?.errorBody()?.string() }.getOrNull())
        is RequestTimeoutException -> AppError.Timeout(t.message ?: Timeouts.neutralTimeoutMessage(Timeouts.FAST_MS), t)
        is SocketTimeoutException -> AppError.Timeout(
            "等待服务端响应超时。若是长时间生成，服务端可能仍在处理，稍后刷新再看。",
            t,
        )
        is IOException -> AppError.Network(cause = t)
        is SerializationException -> AppError.Local("服务端返回的数据格式无法解析（App 可能需要更新）。", t)
        is CancellationException -> throw t
        else -> AppError.Local(t.message ?: "未知错误", t)
    }

    fun fromHttp(code: Int, body: String?): AppError {
        val detail = parseDetail(body)
        val message = detail.message
        return when (code) {
            401 -> AppError.Unauthorized(message ?: "未登录或登录已过期")
            403 -> AppError.Forbidden(message ?: "没有权限执行这个操作")
            404 -> AppError.NotFound(message ?: "项目不存在或已被删除")
            409 -> AppError.Conflict(
                message ?: "该项目已在其他位置被修改。",
                serverUpdatedAt = detail.serverUpdatedAt,
            )
            423 -> AppError.Locked(message ?: "该章正被其他成员编辑")
            429 -> AppError.RateLimited(message ?: "操作过于频繁，请稍后再试")
            else -> AppError.Http(code, message ?: "服务端错误（$code）")
        }
    }

    private data class Detail(val message: String?, val code: String?, val serverUpdatedAt: String?)

    private fun parseDetail(body: String?): Detail {
        if (body.isNullOrBlank()) return Detail(null, null, null)
        val root = runCatching { json.parseToJsonElement(body) }.getOrNull()
            ?: return Detail(body.take(200), null, null)
        val detail = (root as? JsonObject)?.get("detail") ?: root
        return when (detail) {
            is JsonPrimitive -> Detail(detail.contentOrNull, null, null)
            is JsonObject -> Detail(
                message = detail.str("message") ?: detail.str("detail"),
                code = detail.str("code"),
                serverUpdatedAt = detail.str("serverUpdatedAt"),
            )
            is JsonArray -> Detail(validationMessage(detail), null, null)
            else -> Detail(null, null, null)
        }
    }

    private fun validationMessage(arr: JsonArray): String? =
        arr.mapNotNull { (it as? JsonObject)?.str("msg") }.distinct().takeIf { it.isNotEmpty() }?.joinToString("；")

    private fun JsonObject.str(key: String): String? =
        (this[key] as? JsonPrimitive)?.contentOrNull
}

/**
 * 调用 API 并把所有异常统一翻译成 [AppError]。协程取消会原样向上抛。
 */
suspend inline fun <T> apiCall(crossinline block: suspend () -> T): T = try {
    block()
} catch (e: CancellationException) {
    throw e
} catch (e: Throwable) {
    throw ErrorMapper.fromThrowable(e)
}
