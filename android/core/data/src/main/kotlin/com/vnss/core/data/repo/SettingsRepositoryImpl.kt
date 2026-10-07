package com.vnss.core.data.repo

import com.vnss.core.common.DispatcherProvider
import com.vnss.core.common.Outcome
import com.vnss.core.common.outcomeOf
import com.vnss.core.datastore.LocalSettingsStore
import com.vnss.core.datastore.SecureStorage
import com.vnss.core.model.AccountSettings
import com.vnss.core.model.AccountSettingsUpdate
import com.vnss.core.model.LocalSettings
import com.vnss.core.model.ReminderScheduler
import com.vnss.core.model.SettingsRepository
import com.vnss.core.model.TestLlmResult
import com.vnss.core.model.UsageOverview
import com.vnss.core.model.UsageTotals
import com.vnss.core.network.api.VnssApi
import com.vnss.core.network.apiCall
import com.vnss.core.network.dto.SettingsDto
import com.vnss.core.network.dto.SettingsPutRequest
import com.vnss.core.network.dto.TestLlmRequest
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SettingsRepositoryImpl @Inject constructor(
    private val api: VnssApi,
    private val localStore: LocalSettingsStore,
    private val secure: SecureStorage,
    private val reminders: ReminderScheduler,
    private val dispatchers: DispatcherProvider,
) : SettingsRepository {

    override val local: Flow<LocalSettings> = localStore.flow

    override suspend fun updateLocal(transform: (LocalSettings) -> LocalSettings) {
        localStore.update(transform)
        reminders.apply(localStore.snapshot())
    }

    override suspend fun localLlmKey(): String = secure.localLlmKey()

    override suspend fun setLocalLlmKey(key: String) {
        secure.setLocalLlmKey(key)
    }

    override suspend fun account(): Outcome<AccountSettings> = withContext(dispatchers.io) {
        outcomeOf { apiCall { api.getSettings() }.toDomain() }
    }

    override suspend fun updateAccount(update: AccountSettingsUpdate): Outcome<AccountSettings> =
        withContext(dispatchers.io) {
            outcomeOf {
                apiCall {
                    api.putSettings(
                        SettingsPutRequest(
                            apiKey = update.apiKey,
                            apiBaseUrl = update.apiBaseUrl,
                            apiModel = update.apiModel,
                        ),
                    )
                }.toDomain()
            }
        }

    override suspend fun usage(): Outcome<UsageOverview> = withContext(dispatchers.io) {
        outcomeOf {
            val dto = apiCall { api.usage() }
            UsageOverview(
                today = UsageTotals(dto.today.promptTokens, dto.today.completionTokens, dto.today.totalTokens, dto.today.calls),
                total = UsageTotals(dto.total.promptTokens, dto.total.completionTokens, dto.total.totalTokens, dto.total.calls),
            )
        }
    }

    override suspend fun testLlm(): Outcome<TestLlmResult> = withContext(dispatchers.io) {
        outcomeOf {
            val snap = localStore.snapshot()
            val req = if (snap.localLlmEnabled) {
                TestLlmRequest(
                    apiKey = secure.localLlmKey().ifBlank { null },
                    baseUrl = snap.localLlmBaseUrl.ifBlank { null },
                    model = snap.localLlmModel.ifBlank { null },
                )
            } else {
                TestLlmRequest()
            }
            val r = apiCall { api.testLlm(req) }
            TestLlmResult(r.ok, r.latencyMs, r.model, r.error)
        }
    }

    private fun SettingsDto.toDomain() = AccountSettings(
        hasApiKey = hasApiKey,
        apiKeyMasked = apiKeyMasked,
        apiBaseUrl = apiBaseUrl,
        apiModel = apiModel,
        activeModel = activeModel,
        activeBaseUrl = activeBaseUrl,
        credentialSource = credentialSource,
    )
}
