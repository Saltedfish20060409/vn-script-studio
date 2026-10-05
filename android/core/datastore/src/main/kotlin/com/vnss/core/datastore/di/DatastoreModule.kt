package com.vnss.core.datastore.di

import com.vnss.core.datastore.LocalSettingsStore
import com.vnss.core.datastore.SecureStorage
import com.vnss.core.model.LocalLlmCredentials
import com.vnss.core.model.LocalLlmCredentialsProvider
import com.vnss.core.model.ServerUrlProvider
import com.vnss.core.model.TokenStore
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Named
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class DatastoreBindingsModule {
    @Binds
    abstract fun bindTokenStore(impl: SecureStorage): TokenStore
}

@Module
@InstallIn(SingletonComponent::class)
object DatastoreProvidersModule {

    /**
     * 服务器地址 = 设置里的覆盖值（若有）否则构建默认值。
     * 默认值由 app 模块以 `@Named("defaultServerUrl")` 提供（BuildConfig，debug/release 不同）。
     */
    @Provides
    @Singleton
    fun provideServerUrlProvider(
        settings: LocalSettingsStore,
        @Named("defaultServerUrl") defaultUrl: String,
    ): ServerUrlProvider = object : ServerUrlProvider {
        override fun origin(): String {
            val override = settings.snapshot().serverUrlOverride.trim().trimEnd('/')
            return override.ifEmpty { defaultUrl.trimEnd('/') }
        }
    }

    /** 仅在「本机 Key」模式开启且 Key 非空时才随请求附带 X-LLM-* 头。 */
    @Provides
    @Singleton
    fun provideLocalLlmCredentialsProvider(
        settings: LocalSettingsStore,
        secure: SecureStorage,
    ): LocalLlmCredentialsProvider = object : LocalLlmCredentialsProvider {
        override fun current(): LocalLlmCredentials? {
            val s = settings.snapshot()
            if (!s.localLlmEnabled) return null
            val key = secure.localLlmKey()
            if (key.isBlank()) return null
            return LocalLlmCredentials(apiKey = key, baseUrl = s.localLlmBaseUrl.trim(), model = s.localLlmModel.trim())
        }
    }
}
