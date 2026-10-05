package com.vnss.studio

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Named
import javax.inject.Singleton

/** 把构建期的默认服务器地址交给 core:datastore（它不能依赖 app 的 BuildConfig）。 */
@Module
@InstallIn(SingletonComponent::class)
object AppModule {
    @Provides
    @Singleton
    @Named("defaultServerUrl")
    fun defaultServerUrl(): String = BuildConfig.DEFAULT_SERVER_URL
}
