package com.vnss.core.network

import com.vnss.core.common.AppError
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.flow.callbackFlow
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import java.net.SocketTimeoutException

/** 一条 SSE 事件（`data:` 行内容；注释行如 `: keepalive` 不会出现在这里）。 */
data class SseMessage(val type: String?, val data: String)

/**
 * 把 OkHttp 的回调式 EventSource 包成冷 Flow：收集开始时发起请求，取消收集即断开连接。
 *
 * - 事件缓冲无上限：模型输出是突发的，丢一条 `final` 比多占一点内存严重得多；
 * - 判活靠 OkHttp 读超时（见 [Timeouts.STREAM_IDLE_MS]）：服务端每 15–20s 的 keepalive 注释行
 *   会让套接字持续有字节，连续 3 次没有才会触发 [SocketTimeoutException]；
 * - 失败统一翻译成 [AppError] 作为 Flow 的终止异常。
 */
class SseClient(private val client: OkHttpClient) {

    /** GET 流（协作事件）。 */
    fun get(url: String): Flow<SseMessage> = stream(
        Request.Builder().url(url)
            .header(Timeouts.HEADER, Timeouts.STREAM_IDLE_MS.toString())
            .build(),
    )

    /** POST 流（Agent）。`url` 用相对 Retrofit 占位地址构造即可，BaseUrlInterceptor 会改写 host。 */
    fun post(url: String, jsonBody: String): Flow<SseMessage> = stream(
        Request.Builder().url(url)
            .header(Timeouts.HEADER, Timeouts.STREAM_IDLE_MS.toString())
            .post(jsonBody.toRequestBody("application/json".toMediaType()))
            .build(),
    )

    fun stream(request: Request): Flow<SseMessage> = callbackFlow {
        val listener = object : EventSourceListener() {
            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                trySend(SseMessage(type, data))
            }

            override fun onClosed(eventSource: EventSource) {
                close()
            }

            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                close(translate(t, response))
            }
        }
        val source = EventSources.createFactory(client).newEventSource(request, listener)
        awaitClose { source.cancel() }
    }.buffer(Channel.UNLIMITED)

    private fun translate(t: Throwable?, response: Response?): Throwable {
        if (response != null && !response.isSuccessful) {
            val body = runCatching { response.body?.string() }.getOrNull()
            return ErrorMapper.fromHttp(response.code, body)
        }
        return when (t) {
            null -> AppError.Network("与服务端的连接意外中断，请重试。")
            is RequestTimeoutException, is SocketTimeoutException ->
                AppError.Timeout("太久没有收到服务端的数据，连接已断开。服务端可能仍在处理，稍后刷新再看。", t)
            else -> ErrorMapper.fromThrowable(t)
        }
    }
}
