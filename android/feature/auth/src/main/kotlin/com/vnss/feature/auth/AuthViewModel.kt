package com.vnss.feature.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vnss.core.common.Outcome
import com.vnss.core.model.AuthRepository
import com.vnss.core.model.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

enum class AuthMode { LOGIN, REGISTER, FORGOT, RESEND }

data class AuthUiState(
    val mode: AuthMode = AuthMode.LOGIN,
    val identifier: String = "",
    val email: String = "",
    val password: String = "",
    val serverUrl: String = "",
    val busy: Boolean = false,
    val error: String? = null,
    val info: String? = null,
)

@HiltViewModel
class AuthViewModel @Inject constructor(
    private val auth: AuthRepository,
    private val settings: SettingsRepository,
) : ViewModel() {

    private val _state = MutableStateFlow(AuthUiState())
    val state: StateFlow<AuthUiState> = _state.asStateFlow()

    init {
        viewModelScope.launch {
            val url = settings.local.first().serverUrlOverride
            _state.update { it.copy(serverUrl = url) }
        }
    }

    fun setMode(mode: AuthMode) = _state.update { it.copy(mode = mode, error = null, info = null) }
    fun onIdentifier(v: String) = _state.update { it.copy(identifier = v, error = null) }
    fun onEmail(v: String) = _state.update { it.copy(email = v, error = null) }
    fun onPassword(v: String) = _state.update { it.copy(password = v, error = null) }
    fun onServerUrl(v: String) = _state.update { it.copy(serverUrl = v, error = null) }
    fun dismissError() = _state.update { it.copy(error = null) }

    fun submit() {
        val s = _state.value
        if (s.busy) return
        validate(s)?.let { msg ->
            _state.update { it.copy(error = msg) }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(busy = true, error = null, info = null) }
            saveServerUrl(s.serverUrl)
            val result: Outcome<String?> = when (s.mode) {
                // 登录成功后会话状态变化，由上层导航切走；这里不需要返回信息
                AuthMode.LOGIN -> mapUnit(auth.login(s.identifier, s.password))
                AuthMode.REGISTER -> auth.register(s.identifier, s.email, s.password)
                AuthMode.FORGOT -> auth.forgotPassword(s.email)
                AuthMode.RESEND -> auth.resendVerification(s.email)
            }
            when (result) {
                is Outcome.Success -> _state.update {
                    it.copy(
                        busy = false,
                        info = result.value,
                        // 注册成功后回登录页，方便验证完直接登录
                        mode = if (s.mode == AuthMode.REGISTER) AuthMode.LOGIN else it.mode,
                        password = if (s.mode == AuthMode.LOGIN) "" else it.password,
                    )
                }
                is Outcome.Failure -> _state.update { it.copy(busy = false, error = result.error.message) }
            }
        }
    }

    private fun mapUnit(o: Outcome<Unit>): Outcome<String?> = when (o) {
        is Outcome.Success -> Outcome.Success(null)
        is Outcome.Failure -> o
    }

    private suspend fun saveServerUrl(raw: String) {
        val cleaned = normalizeServerUrl(raw)
        if (cleaned != settings.local.first().serverUrlOverride) {
            settings.updateLocal { it.copy(serverUrlOverride = cleaned) }
        }
    }

    private fun validate(s: AuthUiState): String? = when (s.mode) {
        AuthMode.LOGIN -> when {
            s.identifier.isBlank() -> "请输入用户名或邮箱"
            s.password.isEmpty() -> "请输入密码"
            else -> null
        }
        AuthMode.REGISTER -> when {
            s.identifier.trim().length < 2 -> "用户名至少 2 个字符"
            !looksLikeEmail(s.email) -> "请输入有效的邮箱地址"
            s.password.length < MIN_PASSWORD -> "密码至少 $MIN_PASSWORD 位"
            s.password.length > MAX_PASSWORD -> "密码不能超过 $MAX_PASSWORD 位"
            else -> null
        }
        AuthMode.FORGOT, AuthMode.RESEND ->
            if (!looksLikeEmail(s.email)) "请输入有效的邮箱地址" else null
    }

    companion object {
        const val MIN_PASSWORD = 8
        const val MAX_PASSWORD = 72 // 后端 bcrypt 输入上限

        fun looksLikeEmail(v: String): Boolean {
            val t = v.trim()
            val at = t.indexOf('@')
            return at > 0 && at < t.length - 3 && t.indexOf('.', at) > at + 1 && !t.contains(' ')
        }

        /** 空串 = 用默认地址；否则补全 https://、去掉末尾 / 与误填的 /api/v1。 */
        fun normalizeServerUrl(raw: String): String {
            var t = raw.trim()
            if (t.isEmpty()) return ""
            if (!t.contains("://")) t = "https://$t"
            t = t.trimEnd('/')
            t = t.removeSuffix("/api/v1").trimEnd('/')
            return t
        }
    }
}
