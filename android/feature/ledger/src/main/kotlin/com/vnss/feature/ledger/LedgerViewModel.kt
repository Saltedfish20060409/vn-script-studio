package com.vnss.feature.ledger

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.vnss.core.common.Outcome
import com.vnss.core.model.Ledger
import com.vnss.core.model.LedgerRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

const val ARG_PROJECT_ID = "projectId"

data class LedgerUiState(
    val refreshing: Boolean = false,
    val error: String? = null,
)

/** 伏笔筛选。 */
enum class ForeshadowFilter(val label: String) {
    ALL("全部"),
    OPEN("未回收"),
    PAID("已回收"),
}

@HiltViewModel
class LedgerViewModel @Inject constructor(
    savedState: SavedStateHandle,
    private val ledger: LedgerRepository,
) : ViewModel() {

    val projectId: String = checkNotNull(savedState[ARG_PROJECT_ID]) { "缺少 projectId 参数" }

    /** 来自本地缓存：离线也能看上次拉到的版本。 */
    val data: StateFlow<Ledger?> = ledger.observeLedger(projectId)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    private val _state = MutableStateFlow(LedgerUiState())
    val state: StateFlow<LedgerUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        if (_state.value.refreshing) return
        viewModelScope.launch {
            _state.update { it.copy(refreshing = true, error = null) }
            val r = ledger.refresh(projectId)
            _state.update { it.copy(refreshing = false, error = (r as? Outcome.Failure)?.error?.message) }
        }
    }

    fun dismissError() = _state.update { it.copy(error = null) }
}
