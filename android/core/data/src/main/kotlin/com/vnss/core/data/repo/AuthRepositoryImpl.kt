package com.vnss.core.data.repo

import com.vnss.core.common.AppError
import com.vnss.core.common.DispatcherProvider
import com.vnss.core.common.Outcome
import com.vnss.core.common.outcomeOf
import com.vnss.core.database.ChapterDao
import com.vnss.core.datastore.LocalSettingsStore
import com.vnss.core.datastore.SecureStorage
import com.vnss.core.model.AuthRepository
import com.vnss.core.model.SessionState
import com.vnss.core.model.SyncRepository
import com.vnss.core.model.User
import com.vnss.core.network.ErrorMapper
import com.vnss.core.network.RefreshCookie
import com.vnss.core.network.SessionEvents
import com.vnss.core.network.api.AuthApi
import com.vnss.core.network.api.RefreshApi
import com.vnss.core.network.api.VnssApi
import com.vnss.core.network.apiCall
import com.vnss.core.network.dto.IdentifierRequest
import com.vnss.core.network.dto.LoginRequest
import com.vnss.core.network.dto.RefreshRequest
import com.vnss.core.network.dto.RegisterRequest
import com.vnss.core.network.dto.UserDto
import okhttp3.Headers
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Named
import javax.inject.Singleton

@Singleton
class AuthRepositoryImpl @Inject constructor(
    private val authApi: AuthApi,
    private val refreshApi: RefreshApi,
    private val api: VnssApi,
    private val tokens: SecureStorage,
    private val settings: LocalSettingsStore,
    private val projects: OfflineProjectRepository,
    private val chapters: ChapterDao,
    private val sync: SyncRepository,
    private val events: SessionEvents,
    private val dispatchers: DispatcherProvider,
    @Named("appScope") appScope: CoroutineScope,
) : AuthRepository {

    private val _session = MutableStateFlow<SessionState>(SessionState.Loading)
    override val session: StateFlow<SessionState> = _session.asStateFlow()

    init {
        appScope.launch {
            events.signedOut.collect {
                _session.value = SessionState.SignedOut
            }
        }
    }

    override suspend fun restoreSession() {
        withContext(dispatchers.io) {
            val refresh = tokens.refreshToken()
            if (refresh.isNullOrBlank()) {
                _session.value = SessionState.SignedOut
                return@withContext
            }
            val refreshed = runCatching {
                val res = refreshApi.refresh(RefreshRequest(refresh)).execute()
                if (!res.isSuccessful) throw AppError.Unauthorized()
                val body = res.body() ?: throw AppError.Unauthorized()
                val nextRefresh = pickRefresh(body.refreshToken, res.headers()) ?: refresh
                tokens.save(body.accessToken, nextRefresh)
            }
            if (refreshed.isFailure) {
                val err = refreshed.exceptionOrNull()
                if (err is AppError.Unauthorized || tokens.refreshToken().isNullOrBlank()) {
                    _session.value = SessionState.SignedOut
                } else {
                    // 有令牌但暂时连不上：先进应用，离线写作
                    _session.value = SessionState.SignedIn(null)
                }
                return@withContext
            }
            val me = runCatching { apiCall { api.me() } }.getOrNull()
            if (me != null) {
                onSignedIn(me)
            } else {
                _session.value = SessionState.SignedIn(null)
            }
        }
    }

    override suspend fun login(identifier: String, password: String): Outcome<Unit> = withContext(dispatchers.io) {
        outcomeOf {
            val response = apiCall { authApi.login(LoginRequest(identifier.trim(), password)) }
            if (!response.isSuccessful) {
                throw ErrorMapper.fromHttp(response.code(), response.errorBody()?.string())
            }
            val token = response.body() ?: throw AppError.Local("登录成功但响应为空，请重试。")
            val refresh = pickRefresh(token.refreshToken, response.headers())
                ?: throw AppError.Local(
                    "服务端没有返回刷新令牌（响应体与 Cookie 都没有）。" +
                        "请确认连的是已支持 Android 的后端，或把当前仓库的 backend 部署到该服务器。",
                )
            tokens.save(token.accessToken, refresh)
            val me = apiCall { api.me() }
            onSignedIn(me)
        }
    }

    private fun pickRefresh(bodyToken: String?, headers: Headers): String? =
        bodyToken?.takeIf { it.isNotBlank() } ?: RefreshCookie.fromHeaders(headers)

    override suspend fun register(username: String, email: String, password: String): Outcome<String> =
        withContext(dispatchers.io) {
            outcomeOf {
                val r = apiCall { authApi.register(RegisterRequest(username.trim(), password, email.trim())) }
                r.message.ifBlank { "注册成功。请查收验证邮件后再登录。" }
            }
        }

    override suspend fun resendVerification(identifier: String): Outcome<String> = withContext(dispatchers.io) {
        outcomeOf {
            val r = apiCall { authApi.resendVerification(IdentifierRequest(identifier.trim())) }
            r.message.ifBlank { "验证邮件已发送。" }
        }
    }

    override suspend fun forgotPassword(identifier: String): Outcome<String> = withContext(dispatchers.io) {
        outcomeOf {
            val r = apiCall { authApi.forgotPassword(IdentifierRequest(identifier.trim())) }
            r.message.ifBlank { "如果该邮箱已注册，重置邮件已经发出。" }
        }
    }

    override suspend fun logout() {
        withContext(dispatchers.io) {
            runCatching { sync.syncAll() }
            tokens.clear()
            val leftover = chapters.pendingCount()
            if (leftover == 0) {
                projects.clearLocalLibrary()
            }
            _session.value = SessionState.SignedOut
        }
    }

    private suspend fun onSignedIn(dto: UserDto) {
        val user = User(
            id = dto.id,
            username = dto.username,
            email = dto.email,
            emailVerified = dto.emailVerified,
            isAdmin = dto.isAdmin,
        )
        val last = settings.snapshot().lastUserId
        if (last != null && last != user.id) {
            projects.clearLocalLibrary()
        }
        settings.update { it.copy(lastUserId = user.id) }
        _session.value = SessionState.SignedIn(user)
    }
}
