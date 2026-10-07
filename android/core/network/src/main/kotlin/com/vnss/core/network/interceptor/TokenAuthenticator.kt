package com.vnss.core.network.interceptor

import com.vnss.core.model.TokenStore
import com.vnss.core.network.RefreshCookie
import com.vnss.core.network.SessionEvents
import com.vnss.core.network.api.RefreshApi
import com.vnss.core.network.dto.RefreshRequest
import okhttp3.Authenticator
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route
import java.io.IOException

/**
 * 401 → 刷新令牌 → 重放一次。
 *
 * 要点（都是 Web 端 `http.ts` 里已经踩过的坑）：
 * 1. **并发去重**：多个请求同时 401 时只刷新一次——用锁串行化，后到的请求发现令牌已经被换过，
 *    直接用新令牌重放，不再二次刷新（refresh token 轮换后旧值作废，二次刷新会把会话踢掉）。
 * 2. **最多重放一次**：重放后仍 401 就放弃，避免死循环。
 * 3. **区分「登录失效」与「暂时连不上」**：只有刷新接口明确返回 401/403 才清会话；
 *    网络错误、5xx 以 IOException 抛出，会话保留，用户恢复网络后可继续。
 */
class TokenAuthenticator(
    private val tokens: TokenStore,
    private val refreshApi: Lazy<RefreshApi>,
    private val events: SessionEvents,
) : Authenticator {

    private val lock = Any()

    @Throws(IOException::class)
    override fun authenticate(route: Route?, response: Response): Request? {
        val sentAuth = response.request.header("Authorization") ?: return null // 本来就没带令牌的请求，刷新无意义
        if (responseCount(response) >= 2) return null

        synchronized(lock) {
            val sentToken = sentAuth.removePrefix("Bearer ").trim()
            val current = tokens.accessToken()
            // 别的请求已经刷新过了：直接用新令牌重放
            if (current != null && current != sentToken) {
                return response.request.newBuilder().header("Authorization", "Bearer $current").build()
            }

            val refreshToken = tokens.refreshToken()
            if (refreshToken.isNullOrBlank()) {
                invalidate()
                return null
            }

            val result = refreshApi.value.refresh(RefreshRequest(refreshToken)).execute()
            when {
                result.isSuccessful -> {
                    val body = result.body() ?: throw IOException("刷新登录态失败：响应为空")
                    // 后端轮换 refresh token：优先 JSON，其次 Set-Cookie，都没有则沿用旧的
                    val nextRefresh = body.refreshToken?.takeIf { it.isNotBlank() }
                        ?: RefreshCookie.fromHeaders(result.headers())
                        ?: refreshToken
                    tokens.save(body.accessToken, nextRefresh)
                    return response.request.newBuilder()
                        .header("Authorization", "Bearer ${body.accessToken}")
                        .build()
                }
                result.code() == 401 || result.code() == 403 -> {
                    invalidate()
                    return null
                }
                else -> throw IOException("刷新登录态失败（HTTP ${result.code()}），请稍后重试")
            }
        }
    }

    private fun invalidate() {
        tokens.clear()
        events.notifySignedOut()
    }

    private fun responseCount(response: Response): Int {
        var count = 1
        var prior = response.priorResponse
        while (prior != null) {
            count++
            prior = prior.priorResponse
        }
        return count
    }
}
