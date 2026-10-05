package com.vnss.core.network.api

import com.vnss.core.network.Timeouts
import com.vnss.core.network.dto.RefreshRequest
import com.vnss.core.network.dto.TokenDto
import retrofit2.Call
import retrofit2.http.Body
import retrofit2.http.Headers
import retrofit2.http.POST

/**
 * 刷新令牌。**同步 Call**：它只会在 OkHttp 的 [okhttp3.Authenticator]（已经在 OkHttp 线程上）里被调用，
 * 用 suspend 反而要 runBlocking。
 *
 * 原生端不使用 Cookie：带 `X-Client: android` 时后端在响应体里返回 refresh_token，
 * 并接受请求体里的 refresh_token（见 backend `auth.py` 的 native 模式）。
 */
interface RefreshApi {
    @POST("auth/refresh")
    @Headers("${Timeouts.HEADER}: ${Timeouts.AUTH_MS}")
    fun refresh(@Body body: RefreshRequest): Call<TokenDto>
}
