package com.vnss.core.data.work

import android.content.Context
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import com.vnss.core.model.LocalSettings
import com.vnss.core.model.ReminderScheduler
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.Calendar
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ReminderSchedulerImpl @Inject constructor(
    @ApplicationContext context: Context,
) : ReminderScheduler {

    private val wm = WorkManager.getInstance(context)

    override fun apply(settings: LocalSettings) {
        if (!settings.reminderEnabled) {
            wm.cancelUniqueWork(ReminderWorker.UNIQUE)
            return
        }
        val delay = millisUntil(settings.reminderHour, settings.reminderMinute)
        val req = OneTimeWorkRequestBuilder<ReminderWorker>()
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .build()
        wm.enqueueUniqueWork(ReminderWorker.UNIQUE, ExistingWorkPolicy.REPLACE, req)
    }

    private fun millisUntil(hour: Int, minute: Int): Long {
        val now = Calendar.getInstance()
        val target = Calendar.getInstance().apply {
            set(Calendar.HOUR_OF_DAY, hour)
            set(Calendar.MINUTE, minute)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
            if (timeInMillis <= now.timeInMillis + 30_000L) {
                add(Calendar.DAY_OF_YEAR, 1)
            }
        }
        return (target.timeInMillis - now.timeInMillis).coerceAtLeast(1_000L)
    }
}
