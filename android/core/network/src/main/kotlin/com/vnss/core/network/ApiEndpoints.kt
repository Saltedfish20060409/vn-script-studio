package com.vnss.core.network

import kotlinx.serialization.json.Json

/** 网络层共享常量与 Json 配置。 */
object ApiEndpoints {
    /**
     * Retrofit 需要一个固定 baseUrl；真正的 host 在每次请求时由 `BaseUrlInterceptor` 改写。
     * `.invalid` 是保留 TLD（RFC 2606），万一拦截器漏了也只会 DNS 失败，不会打到别人的服务器。
     */
    const val PLACEHOLDER_BASE = "https://placeholder.invalid/api/v1/"

    fun url(path: String): String = PLACEHOLDER_BASE + path.trimStart('/')

    fun agentStream(projectId: String) = url("projects/$projectId/agent/stream")
    fun projectEvents(projectId: String) = url("projects/$projectId/events")
}

/**
 * 全局 Json 配置：
 * - `ignoreUnknownKeys`：后端加字段不能让旧版 App 崩；
 * - `explicitNulls = false` + `encodeDefaults`：null 字段不发（后端对缺省与 null 的处理不同），有默认值的字段照常发；
 * - `coerceInputValues`：服务端偶发 null 落到非空字段时取默认值，而不是整个响应解析失败。
 */
val VnssJson: Json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    encodeDefaults = true
    coerceInputValues = true
}
