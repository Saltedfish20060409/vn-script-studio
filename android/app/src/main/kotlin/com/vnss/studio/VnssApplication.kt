package com.vnss.studio

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import com.vnss.core.model.ReminderScheduler
import com.vnss.core.model.SettingsRepository
import com.vnss.core.model.SyncScheduler
import dagger.hilt.android.HiltAndroidApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import javax.inject.Inject
import javax.inject.Named

@HiltAndroidApp
class VnssApplication : Application(), Configuration.Provider {

    @Inject lateinit var workerFactory: HiltWorkerFactory
    @Inject lateinit var syncScheduler: SyncScheduler
    @Inject lateinit var reminders: ReminderScheduler
    @Inject lateinit var settings: SettingsRepository
    // 字段注入带限定符必须写 @field:，否则 Kotlin 会把 @Named 挂到属性上，Dagger 就看不到
    @Inject @field:Named("appScope") lateinit var appScope: CoroutineScope

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder().setWorkerFactory(workerFactory).build()

    override fun onCreate() {
        super.onCreate()
        // 周期性兜底同步：即使用户没再打开编辑器，积压的草稿也会在联网时上传
        syncScheduler.ensurePeriodicSync()
        // 每次进程启动按当前设置重排一次每日提醒（改过系统时区 / 被省电策略清掉任务时自愈）
        appScope.launch { reminders.apply(settings.local.first()) }
    }
}
