package com.vnss.feature.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vnss.core.common.Outcome
import com.vnss.core.model.AccountSettings
import com.vnss.core.model.AccountSettingsUpdate
import com.vnss.core.model.AuthRepository
import com.vnss.core.model.LocalSettings
import com.vnss.core.model.ServerUrlProvider
import com.vnss.core.model.SessionState
import com.vnss.core.model.SettingsRepository
import com.vnss.core.model.SyncRepository
import com.vnss.core.model.TestLlmResult
import com.vnss.core.model.ThemeMode
import com.vnss.core.model.UsageOverview
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SettingsUiState(
    val account: AccountSettings? = null,
    val accountError: String? = null,
    val usage: UsageOverview? = null,
    val usageError: String? = null,
    val hasLocalKey: Boolean = false,
    val savingAccount: Boolean = false,
    val testing: Boolean = false,
    val testResult: TestLlmResult? = null,
    val testError: String? = null,
    val message: String? = null,
    val loggingOut: Boolean = false,
    val pendingCount: Int = 0,
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val repo: SettingsRepository,
    private val auth: AuthRepository,
    sync: SyncRepository,
    private val serverUrl: ServerUrlProvider,
) : ViewModel() {

    val local: StateFlow<LocalSettings> = repo.local
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), LocalSettings())

    /** 登录用户名（离线冷启动时可能为 null）。 */
    val username: String? get() = (auth.session.value as? SessionState.SignedIn)?.user?.username
    val email: String? get() = (auth.session.value as? SessionState.SignedIn)?.user?.email

    /** 当前服务器地址；也是「在网页端打开」的目标。 */
    val serverOrigin: String get() = serverUrl.origin()

    private val _state = MutableStateFlow(SettingsUiState())
    val state: StateFlow<SettingsUiState> = combine(_state, sync.observePendingCount()) { s, n -> s.copy(pendingCount = n) }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), SettingsUiState())

    init {
        refreshRemote()
        viewModelScope.launch {
            val has = repo.localLlmKey().isNotBlank()
            _state.update { it.copy(hasLocalKey = has) }
        }
    }

    fun refreshRemote() {
        viewModelScope.launch {
            when (val r = repo.account()) {
                is Outcome.Success -> _state.update { it.copy(account = r.value, accountError = null) }
                is Outcome.Failure -> _state.update { it.copy(accountError = r.error.message) }
            }
        }
        viewModelScope.launch {
            when (val r = repo.usage()) {
                is Outcome.Success -> _state.update { it.copy(usage = r.value, usageError = null) }
                is Outcome.Failure -> _state.update { it.copy(usageError = r.error.message) }
            }
        }
    }

    // ------------------------------------------------------------ 本机设置

    fun setTheme(mode: ThemeMode) = update { it.copy(themeMode = mode) }
    fun setFontScale(scale: Float) = update { it.copy(fontScale = scale.coerceIn(MIN_FONT_SCALE, MAX_FONT_SCALE)) }
    fun setSecureWindow(on: Boolean) = update { it.copy(secureWindow = on) }

    /** 空串 / 非数字视为 0（不设目标）；上限防止手滑输成天文数字。 */
    fun setDailyGoal(text: String) {
        val v = text.filter { it.isDigit() }.take(6).toIntOrNull() ?: 0
        update { it.copy(dailyGoalWords = v.coerceIn(0, MAX_GOAL)) }
    }

    fun setReminderEnabled(on: Boolean) = update { it.copy(reminderEnabled = on) }
    fun setReminderTime(hour: Int, minute: Int) = update { it.copy(reminderHour = hour.coerceIn(0, 23), reminderMinute = minute.coerceIn(0, 59)) }

    private fun update(transform: (LocalSettings) -> LocalSettings) {
        viewModelScope.launch { repo.updateLocal(transform) }
    }

    // ------------------------------------------------------------ 本机 Key（仅存本机，加密）

    fun setLocalLlmEnabled(on: Boolean) = update { it.copy(localLlmEnabled = on) }
    fun setLocalLlmBaseUrl(v: String) = update { it.copy(localLlmBaseUrl = v.trim()) }
    fun setLocalLlmModel(v: String) = update { it.copy(localLlmModel = v.trim()) }

    fun saveLocalKey(key: String) {
        viewModelScope.launch {
            repo.setLocalLlmKey(key)
            val has = key.isNotBlank()
            _state.update { it.copy(hasLocalKey = has, message = if (has) "本机 Key 已加密保存在这台手机上。" else "本机 Key 已清除。") }
        }
    }

    // ------------------------------------------------------------ 账号级模型配置

    /** [apiKey] 为 null 表示不改；空串表示清除；其它为设置 / 轮换。 */
    fun saveAccount(apiKey: String?, baseUrl: String, model: String) {
        if (_state.value.savingAccount) return
        viewModelScope.launch {
            _state.update { it.copy(savingAccount = true, accountError = null) }
            val r = repo.updateAccount(AccountSettingsUpdate(apiKey = apiKey, apiBaseUrl = baseUrl.trim(), apiModel = model.trim()))
            when (r) {
                is Outcome.Success -> _state.update { it.copy(savingAccount = false, account = r.value, message = "已保存账号的模型配置。") }
                is Outcome.Failure -> _state.update { it.copy(savingAccount = false, accountError = r.error.message) }
            }
        }
    }

    fun testLlm() {
        if (_state.value.testing) return
        viewModelScope.launch {
            _state.update { it.copy(testing = true, testResult = null, testError = null) }
            when (val r = repo.testLlm()) {
                is Outcome.Success -> _state.update { it.copy(testing = false, testResult = r.value) }
                is Outcome.Failure -> _state.update { it.copy(testing = false, testError = r.error.message) }
            }
        }
    }

    // ------------------------------------------------------------ 其它

    fun logout(onDone: () -> Unit) {
        if (_state.value.loggingOut) return
        viewModelScope.launch {
            _state.update { it.copy(loggingOut = true) }
            auth.logout()
            _state.update { it.copy(loggingOut = false) }
            onDone()
        }
    }

    fun dismissMessage() = _state.update { it.copy(message = null) }

    private companion object {
        const val MIN_FONT_SCALE = 0.85f
        const val MAX_FONT_SCALE = 1.4f
        const val MAX_GOAL = 200_000
    }
}
