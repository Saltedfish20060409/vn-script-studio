package com.vnss.studio

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vnss.core.model.AuthRepository
import com.vnss.core.model.LocalSettings
import com.vnss.core.model.SessionState
import com.vnss.core.model.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Activity 级：会话状态决定显示登录页还是主界面；本机设置决定主题。 */
@HiltViewModel
class AppViewModel @Inject constructor(
    private val auth: AuthRepository,
    settings: SettingsRepository,
) : ViewModel() {

    val session: StateFlow<SessionState> = auth.session

    val settings: StateFlow<LocalSettings> = settings.local
        .stateIn(viewModelScope, SharingStarted.Eagerly, LocalSettings())

    init {
        viewModelScope.launch { auth.restoreSession() }
    }
}
