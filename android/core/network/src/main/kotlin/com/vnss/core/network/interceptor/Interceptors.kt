package com.vnss.core.network.interceptor

import com.vnss.core.model.LocalLlmCredentialsProvider
import com.vnss.core.model.ServerUrlProvider
import com.vnss.core.model.TokenStore
import com.vnss.core.network.RequestTimeoutException
import com.vnss.core.network.Timeouts
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response
import java.net.SocketTimeoutException
import java.util.TimeZone
import java.util.concurrent.TimeUnit

/**
 * 每次请求都读取当前服务器地址，替换占位 host。
 * 因此「设置 → 服务器」切换地址后立即生效，不需要重建 OkHttp / Retrofit。
 *
 * 只替换 scheme/host/port；API 前缀 `/api/v1/` 固定在 Retrofit baseUrl 里。
 * （不支持挂在子路径下的反代，如 https://host/sub——自建场景下用独立域名即可。）
 */
class BaseUrlInterceptor(private val serverUrl: ServerUrlProvider) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val origin = serverUrl.origin().trim().toHttpUrlOrNull() ?: return chain.proceed(request)
        val rewritten = request.url.newBuilder()
            .scheme(origin.scheme)
            .host(origin.host)
            .port(origin.port)
            .build()
        return chain.proceed(request.newBuilder().url(rewritten).build())
    }
}

/**
 * 附加通用请求头：
 * - `Authorization: Bearer`（有令牌时）；
 * - `X-Client: android`：告诉后端走原生客户端模式（refresh token 走响应体而不是 Cookie）；
 * - `X-TZ-Offset`：作者当地相对 UTC 的分钟数。后端按作者当地日期记写作活动，
 *   不带的话东八区用户凌晨写的字会记到前一天（Web 端同样每个请求都带）；
 * - 本机 Key 模式下的 `X-LLM-*`（不会写入日志，见 [com.vnss.core.network.di.NetworkModule] 的 redact）。
 */
class AuthInterceptor(
    private val tokens: TokenStore,
    private val llm: LocalLlmCredentialsProvider,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val builder = chain.request().newBuilder()
            .header(CLIENT_HEADER, CLIENT_VALUE)
            .header("X-TZ-Offset", tzOffsetMinutes().toString())
        tokens.accessToken()?.let { builder.header("Authorization", "Bearer $it") }
        llm.current()?.let { c ->
            if (c.apiKey.isNotBlank()) builder.header("X-LLM-Api-Key", c.apiKey)
            if (c.baseUrl.isNotBlank()) builder.header("X-LLM-Base-Url", c.baseUrl)
            if (c.model.isNotBlank()) builder.header("X-LLM-Model", c.model)
        }
        return chain.proceed(builder.build())
    }

    companion object {
        const val CLIENT_HEADER = "X-Client"
        const val CLIENT_VALUE = "android"

        /** 东八区 = +480（与 Web 端 `-new Date().getTimezoneOffset()` 同号）。 */
        fun tzOffsetMinutes(now: Long = System.currentTimeMillis()): Int =
            TimeZone.getDefault().getOffset(now) / 60_000
    }
}

/** 给不需要登录态的请求（登录 / 刷新）补上 X-Client 头。 */
class ClientHeaderInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response =
        chain.proceed(
            chain.request().newBuilder()
                .header(AuthInterceptor.CLIENT_HEADER, AuthInterceptor.CLIENT_VALUE)
                .build(),
        )
}

/**
 * 读取 `X-Vnss-Timeout-Ms` 声明的预算并应用为该请求的读/写超时，随后把头移除（不发给服务端）。
 *
 * 超时统一翻译为 [RequestTimeoutException]（IOException 子类）：直接抛 AppError 会在
 * OkHttp 调度线程上变成未捕获异常；文案区分「模型慢」与「服务端未响应」，规则同 Web 的 `resolveTimeoutKind`。
 */
class TimeoutInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val budget = original.header(Timeouts.HEADER)?.toLongOrNull() ?: Timeouts.FAST_MS
        val request = original.newBuilder().removeHeader(Timeouts.HEADER).build()
        val timed = chain
            .withConnectTimeout(Timeouts.CONNECT_MS.toInt(), TimeUnit.MILLISECONDS)
            .withReadTimeout(budget.coerceAtMost(Int.MAX_VALUE.toLong()).toInt(), TimeUnit.MILLISECONDS)
            .withWriteTimeout(Timeouts.UPLOAD_MS.toInt(), TimeUnit.MILLISECONDS)
        try {
            return timed.proceed(request)
        } catch (e: SocketTimeoutException) {
            throw RequestTimeoutException(timeoutMessage(budget), e)
        }
    }

    companion object {
        /** 与 Web `resolveTimeoutKind` 对齐：>= quick 或 == probe 视为模型路径。 */
        fun isLlmBudget(ms: Long): Boolean = ms == Timeouts.PROBE_MS || ms >= Timeouts.QUICK_MS

        fun timeoutMessage(ms: Long): String =
            if (isLlmBudget(ms)) Timeouts.llmTimeoutMessage(ms) else Timeouts.neutralTimeoutMessage(ms)
    }
}
