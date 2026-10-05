package com.vnss.core.datastore

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.floatPreferencesKey
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.vnss.core.model.LocalSettings
import com.vnss.core.model.ThemeMode
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.runBlocking
import javax.inject.Inject
import javax.inject.Singleton

private val Context.settingsDataStore by preferencesDataStore(name = "vnss_settings")

/** 本机设置（DataStore Preferences）。 */
@Singleton
class LocalSettingsStore @Inject constructor(
    @param:ApplicationContext private val context: Context,
) {
    val flow: Flow<LocalSettings> = context.settingsDataStore.data.map { it.toSettings() }

    @Volatile private var cache: LocalSettings? = null

    /**
     * 同步快照：给 OkHttp 线程上的 [com.vnss.core.model.ServerUrlProvider] 用（不能挂起）。
     * 首次读取阻塞一次 DataStore（磁盘读，毫秒级），之后由 [update] 保持缓存最新。
     * 绝不能在主线程调用——网络层只会在 OkHttp 线程上调到它。
     */
    fun snapshot(): LocalSettings {
        cache?.let { return it }
        return runBlocking { context.settingsDataStore.data.first().toSettings() }.also { cache = it }
    }

    suspend fun update(transform: (LocalSettings) -> LocalSettings) {
        context.settingsDataStore.edit { prefs ->
            val next = transform(prefs.toSettings())
            prefs.write(next)
            cache = next
        }
    }

    private fun Preferences.toSettings() = LocalSettings(
        serverUrlOverride = this[SERVER_URL] ?: "",
        themeMode = this[THEME]?.let { name -> ThemeMode.entries.firstOrNull { it.name == name } } ?: ThemeMode.SYSTEM,
        fontScale = this[FONT_SCALE] ?: 1.0f,
        dailyGoalWords = this[DAILY_GOAL] ?: 0,
        reminderEnabled = this[REMINDER_ON] ?: false,
        reminderHour = this[REMINDER_HOUR] ?: 21,
        reminderMinute = this[REMINDER_MIN] ?: 0,
        lastProjectId = this[LAST_PROJECT],
        lastUserId = this[LAST_USER],
        localLlmEnabled = this[LOCAL_LLM_ON] ?: false,
        localLlmBaseUrl = this[LOCAL_LLM_URL] ?: "",
        localLlmModel = this[LOCAL_LLM_MODEL] ?: "",
        secureWindow = this[SECURE_WINDOW] ?: false,
        lastWriteAt = this[LAST_WRITE] ?: 0L,
    )

    private fun androidx.datastore.preferences.core.MutablePreferences.write(s: LocalSettings) {
        this[SERVER_URL] = s.serverUrlOverride
        this[THEME] = s.themeMode.name
        this[FONT_SCALE] = s.fontScale
        this[DAILY_GOAL] = s.dailyGoalWords
        this[REMINDER_ON] = s.reminderEnabled
        this[REMINDER_HOUR] = s.reminderHour
        this[REMINDER_MIN] = s.reminderMinute
        // LocalSettings 在另一个模块，其 public 属性不能智能转换，先取局部变量
        val projectId = s.lastProjectId
        if (projectId != null) this[LAST_PROJECT] = projectId else remove(LAST_PROJECT)
        val userId = s.lastUserId
        if (userId != null) this[LAST_USER] = userId else remove(LAST_USER)
        this[LOCAL_LLM_ON] = s.localLlmEnabled
        this[LOCAL_LLM_URL] = s.localLlmBaseUrl
        this[LOCAL_LLM_MODEL] = s.localLlmModel
        this[SECURE_WINDOW] = s.secureWindow
        this[LAST_WRITE] = s.lastWriteAt
    }

    private companion object {
        val SERVER_URL = stringPreferencesKey("server_url")
        val THEME = stringPreferencesKey("theme")
        val FONT_SCALE = floatPreferencesKey("font_scale")
        val DAILY_GOAL = intPreferencesKey("daily_goal")
        val REMINDER_ON = booleanPreferencesKey("reminder_on")
        val REMINDER_HOUR = intPreferencesKey("reminder_hour")
        val REMINDER_MIN = intPreferencesKey("reminder_min")
        val LAST_PROJECT = stringPreferencesKey("last_project")
        val LAST_USER = stringPreferencesKey("last_user")
        val LOCAL_LLM_ON = booleanPreferencesKey("local_llm_on")
        val LOCAL_LLM_URL = stringPreferencesKey("local_llm_url")
        val LOCAL_LLM_MODEL = stringPreferencesKey("local_llm_model")
        val SECURE_WINDOW = booleanPreferencesKey("secure_window")
        val LAST_WRITE = longPreferencesKey("last_write_at")
    }
}
