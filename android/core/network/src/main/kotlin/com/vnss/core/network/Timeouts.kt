package com.vnss.core.network

/**
 * 请求超时预算——镜像 `frontend/src/api/timeouts.ts`（后端真源是 `backend/app/core/llm_budget.py`）。
 *
 * 规则与 Web 端一致：
 * 1. 凡是会在请求内调用模型的端点，必须显式选一档预算，不许吃 [FAST] 默认值；
 * 2. 预算 ≥ 后端最坏耗时 + 余量——否则客户端抢先掐断，用户会被误导成「后端挂了」；
 * 3. 数字只写在这里，Retrofit 接口通过 [HEADER] 引用，不许出现裸数字。
 *
 * ## 与 Web 的一个差别
 * OkHttp 没有「整次请求总超时」的逐请求开关（callTimeout 在 Chain 上不可调），
 * 这里用的是 **read timeout**：非流式请求里，服务端在生成完成之前不会回任何字节，
 * 所以 read timeout 在效果上就是「等模型的总时长」，与 Web 的 AbortController 等价。
 *
 * 数值与 `timeouts.ts` 的一致性由 `TimeoutsTest` 直接解析前端源码校验，任何一边改数而不改另一边会红。
 */
object Timeouts {
    /** Retrofit 方法用 `@Headers("X-Vnss-Timeout-Ms: …")` 声明预算，[TimeoutInterceptor] 取走并移除。 */
    const val HEADER = "X-Vnss-Timeout-Ms"

    const val AUTH_MS = 10_000L
    const val FAST_MS = 30_000L
    const val PROBE_MS = 120_000L
    const val UPLOAD_MS = 180_000L
    const val QUICK_MS = 350_000L
    const val CHAT_MS = 420_000L
    const val WRITE_MS = 670_000L
    const val LONG_MS = 780_000L
    const val BATCH_MS = 1_140_000L

    /** 后端异步作业轮询预算，必须 ≥ [BATCH_MS]。 */
    const val JOB_POLL_MS = 21 * 60_000L

    /**
     * 流式（SSE）读超时：服务端每 15–20s 发一次 keepalive，
     * 连续 3 次没有任何字节才判死——靠「多久没有新字节」判活，而不是总时长。
     */
    const val STREAM_IDLE_MS = 60_000L

    const val CONNECT_MS = 15_000L

    /** 把毫秒说成人话，用于超时提示。 */
    fun humanize(ms: Long): String {
        val sec = Math.round(ms / 1000.0)
        if (sec < 60) return "$sec 秒"
        val min = sec / 60.0
        return if (min == Math.floor(min)) "${min.toInt()} 分钟" else "${"%.1f".format(java.util.Locale.ROOT, min)} 分钟"
    }

    fun llmTimeoutMessage(ms: Long): String =
        "等待 ${humanize(ms)} 仍未返回，已停止等待。" +
            "常见原因：所选模型较慢（思考档尤其慢）、本次范围偏大或上游波动。" +
            "服务端会随即停止这次生成；也可以换非思考档、缩小范围后重试。"

    fun neutralTimeoutMessage(ms: Long): String =
        "服务端未在 ${humanize(ms)} 内响应，已停止等待。请确认服务仍在运行后重试。"
}
