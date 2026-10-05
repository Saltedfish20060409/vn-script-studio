package com.vnss.core.network

import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 会话失效广播：Authenticator 刷新失败（刷新令牌也过期 / 被吊销）时发出，
 * AuthRepository 订阅后把会话置为 SignedOut，UI 自动回到登录页。
 */
@Singleton
class SessionEvents @Inject constructor() {
    private val _signedOut = MutableSharedFlow<Unit>(extraBufferCapacity = 1, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val signedOut: SharedFlow<Unit> = _signedOut.asSharedFlow()

    fun notifySignedOut() {
        _signedOut.tryEmit(Unit)
    }
}
