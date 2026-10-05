package com.vnss.core.datastore

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.vnss.core.model.TokenStore
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 令牌与本机 LLM Key 的加密存储（Android Keystore 主密钥 + AES256 的 EncryptedSharedPreferences）。
 *
 * - 令牌在内存里缓存一份：`AuthInterceptor` 每个请求都要读，不能每次都过一遍解密；
 * - Keystore 偶发损坏（系统恢复 / 指纹库变更）会让 EncryptedSharedPreferences 初始化抛异常，
 *   此时清掉损坏的文件重建——代价是用户需要重新登录，好过 App 启动即崩溃；
 * - **任何情况下都不写日志**。
 */
@Singleton
class SecureStorage @Inject constructor(
    @ApplicationContext private val context: Context,
) : TokenStore {

    private val prefs: SharedPreferences by lazy { openPrefs() }

    @Volatile private var accessCache: String? = null
    @Volatile private var refreshCache: String? = null
    @Volatile private var loaded = false

    private fun openPrefs(): SharedPreferences {
        return try {
            create()
        } catch (e: Exception) {
            context.deleteSharedPreferences(FILE)
            create()
        }
    }

    private fun create(): SharedPreferences {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            context,
            FILE,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    private fun ensureLoaded() {
        if (loaded) return
        synchronized(this) {
            if (loaded) return
            accessCache = prefs.getString(KEY_ACCESS, null)
            refreshCache = prefs.getString(KEY_REFRESH, null)
            loaded = true
        }
    }

    override fun accessToken(): String? {
        ensureLoaded()
        return accessCache
    }

    override fun refreshToken(): String? {
        ensureLoaded()
        return refreshCache
    }

    @Synchronized
    override fun save(accessToken: String, refreshToken: String?) {
        ensureLoaded()
        accessCache = accessToken
        if (refreshToken != null) refreshCache = refreshToken
        val editor = prefs.edit()
        editor.putString(KEY_ACCESS, accessToken)
        if (refreshToken != null) editor.putString(KEY_REFRESH, refreshToken)
        editor.apply()
    }

    @Synchronized
    override fun clear() {
        accessCache = null
        refreshCache = null
        loaded = true
        prefs.edit().remove(KEY_ACCESS).remove(KEY_REFRESH).apply()
    }

    // ------------------------------------------------------------ 本机 LLM Key

    fun localLlmKey(): String = prefs.getString(KEY_LOCAL_LLM, "").orEmpty()

    fun setLocalLlmKey(key: String) {
        prefs.edit().apply {
            if (key.isBlank()) remove(KEY_LOCAL_LLM) else putString(KEY_LOCAL_LLM, key.trim())
        }.apply()
    }

    private companion object {
        const val FILE = "vnss_secure"
        const val KEY_ACCESS = "access_token"
        const val KEY_REFRESH = "refresh_token"
        const val KEY_LOCAL_LLM = "local_llm_key"
    }
}
