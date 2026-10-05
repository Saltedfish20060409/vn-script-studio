package com.vnss.core.network

import com.vnss.core.common.AppError
import com.vnss.core.model.LocalLlmCredentials
import com.vnss.core.model.LocalLlmCredentialsProvider
import com.vnss.core.model.ServerUrlProvider
import com.vnss.core.model.TokenStore
import com.vnss.core.network.api.RefreshApi
import com.vnss.core.network.interceptor.AuthInterceptor
import com.vnss.core.network.interceptor.BaseUrlInterceptor
import com.vnss.core.network.interceptor.TimeoutInterceptor
import com.vnss.core.network.interceptor.TokenAuthenticator
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

/** 用 MockWebServer 钉住：host 改写、令牌附加与刷新重放、SSE 解析与错误翻译。 */
class HttpStackTest {

    private lateinit var server: MockWebServer

    private class MemoryTokens(var access: String? = null, var refresh: String? = null) : TokenStore {
        override fun accessToken() = access
        override fun refreshToken() = refresh
        override fun save(accessToken: String, refreshToken: String?) {
            access = accessToken
            refresh = refreshToken
        }

        override fun clear() {
            access = null
            refresh = null
        }
    }

    @Before
    fun setUp() {
        server = MockWebServer().apply { start() }
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    private fun origin() = object : ServerUrlProvider {
        override fun origin(): String = server.url("/").toString().trimEnd('/')
    }

    private fun noLlm() = object : LocalLlmCredentialsProvider {
        override fun current(): LocalLlmCredentials? = null
    }

    private fun refreshApi(): RefreshApi {
        val bare = OkHttpClient.Builder()
            .addInterceptor(BaseUrlInterceptor(origin()))
            .addInterceptor(TimeoutInterceptor())
            .build()
        return Retrofit.Builder()
            .baseUrl(ApiEndpoints.PLACEHOLDER_BASE)
            .client(bare)
            .addConverterFactory(VnssJson.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(RefreshApi::class.java)
    }

    private fun apiClient(tokens: TokenStore, events: SessionEvents = SessionEvents()): OkHttpClient =
        OkHttpClient.Builder()
            .addInterceptor(BaseUrlInterceptor(origin()))
            .addInterceptor(AuthInterceptor(tokens, noLlm()))
            .addInterceptor(TimeoutInterceptor())
            .authenticator(TokenAuthenticator(tokens, lazy { refreshApi() }, events))
            .build()

    @Test
    fun rewritesHostAndAddsAuthAndClientHeaders() {
        val tokens = MemoryTokens(access = "tok")
        server.enqueue(MockResponse().setBody("{}"))
        apiClient(tokens).newCall(Request.Builder().url(ApiEndpoints.url("projects")).build()).execute().close()

        val recorded = server.takeRequest()
        assertEquals("/api/v1/projects", recorded.path)
        assertEquals("Bearer tok", recorded.getHeader("Authorization"))
        assertEquals("android", recorded.getHeader("X-Client"))
        assertTrue(recorded.getHeader("X-TZ-Offset") != null)
        // 预算头只在客户端内部使用，不能泄漏给服务端
        assertNull(recorded.getHeader(Timeouts.HEADER))
    }

    @Test
    fun refreshesOnceOn401AndReplays() {
        val tokens = MemoryTokens(access = "old", refresh = "r1")
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"expired"}"""))
        server.enqueue(MockResponse().setBody("""{"access_token":"new","refresh_token":"r2"}"""))
        server.enqueue(MockResponse().setBody("{}"))

        val res = apiClient(tokens).newCall(Request.Builder().url(ApiEndpoints.url("projects")).build()).execute()
        assertEquals(200, res.code)
        res.close()

        assertEquals("/api/v1/projects", server.takeRequest().path)
        val refreshReq = server.takeRequest()
        assertEquals("/api/v1/auth/refresh", refreshReq.path)
        assertTrue(refreshReq.body.readUtf8().contains("r1"))
        val replay = server.takeRequest()
        assertEquals("Bearer new", replay.getHeader("Authorization"))
        assertEquals("new", tokens.access)
        assertEquals("r2", tokens.refresh)
    }

    @Test
    fun refreshRejectionSignsOut() {
        val tokens = MemoryTokens(access = "old", refresh = "bad")
        val events = SessionEvents()
        server.enqueue(MockResponse().setResponseCode(401))
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"detail":"刷新令牌已失效"}"""))

        val res = apiClient(tokens, events).newCall(Request.Builder().url(ApiEndpoints.url("projects")).build()).execute()
        assertEquals(401, res.code)
        res.close()
        assertNull(tokens.access)
        assertNull(tokens.refresh)
    }

    @Test
    fun refreshServerErrorKeepsSession() {
        val tokens = MemoryTokens(access = "old", refresh = "r1")
        server.enqueue(MockResponse().setResponseCode(401))
        server.enqueue(MockResponse().setResponseCode(503))

        val failure = runCatching {
            apiClient(tokens).newCall(Request.Builder().url(ApiEndpoints.url("projects")).build()).execute().close()
        }.exceptionOrNull()
        assertTrue("刷新接口 5xx 应以 IOException 抛出", failure is java.io.IOException)
        // 会话不能因为服务端暂时故障被清掉
        assertEquals("r1", tokens.refresh)
    }

    @Test
    fun sseParsesDataEventsAndIgnoresKeepalive() = runBlocking {
        val body = ": keepalive\n\n" +
            "data: {\"type\":\"task\",\"text\":\"开始\"}\n\n" +
            ": keepalive\n\n" +
            "data: {\"type\":\"final\"}\n\n"
        server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream").setBody(body))

        val sse = SseClient(apiClient(MemoryTokens(access = "t")))
        val events = sse.post(ApiEndpoints.agentStream("p1"), """{"messages":[]}""").toList()

        assertEquals(2, events.size)
        assertTrue(events[0].data.contains("\"task\""))
        assertTrue(events[1].data.contains("\"final\""))
        val recorded = server.takeRequest()
        assertEquals("POST", recorded.method)
        assertEquals("/api/v1/projects/p1/agent/stream", recorded.path)
    }

    @Test
    fun sseHttpErrorBecomesTypedAppError() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"detail":"服务端未配置 DEEPSEEK_API_KEY"}"""))
        val sse = SseClient(apiClient(MemoryTokens(access = "t")))
        val error = runCatching { sse.post(ApiEndpoints.agentStream("p1"), "{}").toList() }.exceptionOrNull()
        assertTrue(error is AppError.Http)
        assertTrue(error!!.message!!.contains("DEEPSEEK_API_KEY"))
    }
}
