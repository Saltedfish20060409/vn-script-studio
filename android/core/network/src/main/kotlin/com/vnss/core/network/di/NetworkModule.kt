package com.vnss.core.network.di

import android.content.Context
import android.content.pm.ApplicationInfo
import com.vnss.core.model.LocalLlmCredentialsProvider
import com.vnss.core.model.ServerUrlProvider
import com.vnss.core.model.TokenStore
import com.vnss.core.network.ApiEndpoints
import com.vnss.core.network.SessionEvents
import com.vnss.core.network.SseClient
import com.vnss.core.network.VnssJson
import com.vnss.core.network.api.AuthApi
import com.vnss.core.network.api.RefreshApi
import com.vnss.core.network.api.VnssApi
import com.vnss.core.network.interceptor.AuthInterceptor
import com.vnss.core.network.interceptor.BaseUrlInterceptor
import com.vnss.core.network.interceptor.ClientHeaderInterceptor
import com.vnss.core.network.interceptor.RefreshCookieInterceptor
import com.vnss.core.network.interceptor.TimeoutInterceptor
import com.vnss.core.network.interceptor.TokenAuthenticator
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import javax.inject.Named
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    private const val ROOT = "root"
    private const val BARE = "bare"
    private const val API = "api"

    @Provides
    @Singleton
    fun provideJson(): Json = VnssJson

    /** 无拦截器的根客户端：两个业务客户端共享它的连接池与线程池。 */
    @Provides
    @Singleton
    @Named(ROOT)
    fun provideRootClient(): OkHttpClient = OkHttpClient.Builder().build()

    /**
     * 不带令牌 / Authenticator 的基础客户端：登录、刷新令牌用它。
     * 刷新请求如果也带 Authenticator，刷新失败的 401 会再触发刷新，形成递归。
     */
    @Provides
    @Singleton
    @Named(BARE)
    fun provideBareClient(
        @Named(ROOT) root: OkHttpClient,
        serverUrl: ServerUrlProvider,
        tokens: TokenStore,
        @ApplicationContext context: Context,
    ): OkHttpClient = root.newBuilder()
        .addInterceptor(BaseUrlInterceptor(serverUrl))
        .addInterceptor(ClientHeaderInterceptor())
        .addInterceptor(RefreshCookieInterceptor(tokens))
        .addInterceptor(TimeoutInterceptor())
        .addInterceptor(loggingInterceptor(context))
        .build()

    @Provides
    @Singleton
    @Named(API)
    fun provideApiClient(
        @Named(ROOT) root: OkHttpClient,
        serverUrl: ServerUrlProvider,
        tokens: TokenStore,
        llm: LocalLlmCredentialsProvider,
        refreshApi: dagger.Lazy<RefreshApi>,
        events: SessionEvents,
        @ApplicationContext context: Context,
    ): OkHttpClient = root.newBuilder()
        // 顺序：改写 host → 附加令牌/通用头 → 应用超时预算 → 日志（最后，能看到最终的头，敏感头已 redact）
        .addInterceptor(BaseUrlInterceptor(serverUrl))
        .addInterceptor(AuthInterceptor(tokens, llm))
        .addInterceptor(TimeoutInterceptor())
        .addInterceptor(loggingInterceptor(context))
        .authenticator(TokenAuthenticator(tokens, lazy { refreshApi.get() }, events))
        .build()

    @Provides
    @Singleton
    @Named(BARE)
    fun provideBareRetrofit(@Named(BARE) client: OkHttpClient, json: Json): Retrofit = retrofit(client, json)

    @Provides
    @Singleton
    @Named(API)
    fun provideApiRetrofit(@Named(API) client: OkHttpClient, json: Json): Retrofit = retrofit(client, json)

    @Provides
    @Singleton
    fun provideVnssApi(@Named(API) retrofit: Retrofit): VnssApi = retrofit.create(VnssApi::class.java)

    @Provides
    @Singleton
    fun provideAuthApi(@Named(BARE) retrofit: Retrofit): AuthApi = retrofit.create(AuthApi::class.java)

    @Provides
    @Singleton
    fun provideRefreshApi(@Named(BARE) retrofit: Retrofit): RefreshApi = retrofit.create(RefreshApi::class.java)

    @Provides
    @Singleton
    fun provideSseClient(@Named(API) client: OkHttpClient): SseClient = SseClient(client)

    private fun retrofit(client: OkHttpClient, json: Json): Retrofit =
        Retrofit.Builder()
            .baseUrl(ApiEndpoints.PLACEHOLDER_BASE)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()

    /** debug 构建才打印请求日志；Authorization 与 LLM Key 永远脱敏。 */
    private fun loggingInterceptor(context: Context): HttpLoggingInterceptor {
        val debuggable = (context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
        return HttpLoggingInterceptor().apply {
            level = if (debuggable) HttpLoggingInterceptor.Level.BASIC else HttpLoggingInterceptor.Level.NONE
            redactHeader("Authorization")
            redactHeader("X-LLM-Api-Key")
            redactHeader("X-LLM-Critic-Api-Key")
        }
    }
}
