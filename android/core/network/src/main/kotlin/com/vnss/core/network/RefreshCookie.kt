package com.vnss.core.network

import okhttp3.Headers

/**
 * 兼容「只把 refresh 放在 HttpOnly Cookie」的旧部署 / Web 路径。
 *
 * 理想路径：原生客户端带 `X-Client: android`，服务端在 JSON 里返回 `refresh_token`。
 * 若线上还没部署这段逻辑，登录仍会 `Set-Cookie: vnss_refresh=…`——朋友打的 APK
 * 若用了 CookieJar 就能登；我们这里显式读出来存进 Keystore，行为对齐。
 */
object RefreshCookie {
    const val NAME = "vnss_refresh"

    fun fromHeaders(headers: Headers): String? {
        // 可能有多条 Set-Cookie；只认 vnss_refresh
        val values = headers.values("Set-Cookie") + headers.values("set-cookie")
        for (raw in values) {
            val token = parse(raw) ?: continue
            if (token.isNotBlank()) return token
        }
        return null
    }

    fun cookieHeader(value: String): String = "$NAME=$value"

    internal fun parse(setCookie: String): String? {
        // 形如：vnss_refresh=xxx; Path=/api/v1/auth/refresh; HttpOnly; SameSite=Strict
        val first = setCookie.substringBefore(';').trim()
        val eq = first.indexOf('=')
        if (eq <= 0) return null
        val name = first.substring(0, eq).trim()
        if (!name.equals(NAME, ignoreCase = true)) return null
        return first.substring(eq + 1).trim().takeIf { it.isNotEmpty() }
    }
}
