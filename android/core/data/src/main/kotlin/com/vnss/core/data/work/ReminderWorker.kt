package com.vnss.core.data.work

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.vnss.core.data.R
import com.vnss.core.model.ReminderScheduler
import com.vnss.core.model.SettingsRepository
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.flow.first
import java.util.Calendar

@HiltWorker
class ReminderWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val settings: SettingsRepository,
    private val scheduler: ReminderScheduler,
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val local = settings.local.first()
        if (local.reminderEnabled) {
            if (!wroteToday(local.lastWriteAt)) {
                notify(applicationContext)
            }
            scheduler.apply(local)
        }
        return Result.success()
    }

    private fun wroteToday(lastWriteAt: Long): Boolean {
        if (lastWriteAt <= 0L) return false
        val now = Calendar.getInstance()
        val then = Calendar.getInstance().apply { timeInMillis = lastWriteAt }
        return now.get(Calendar.YEAR) == then.get(Calendar.YEAR) &&
            now.get(Calendar.DAY_OF_YEAR) == then.get(Calendar.DAY_OF_YEAR)
    }

    private fun notify(context: Context) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            manager.createNotificationChannel(
                NotificationChannel(
                    CHANNEL,
                    context.getString(R.string.reminder_channel_name),
                    NotificationManager.IMPORTANCE_DEFAULT,
                ).apply { description = context.getString(R.string.reminder_channel_desc) },
            )
        }
        val launch = context.packageManager.getLaunchIntentForPackage(context.packageName)
            ?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val pending = launch?.let {
            PendingIntent.getActivity(
                context,
                0,
                it,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        }
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_edit)
            .setContentTitle("今天还没动笔")
            .setContentText("打开 VN Script Studio，写一点就好。")
            .setContentIntent(pending)
            .setAutoCancel(true)
            .build()
        manager.notify(NOTIF_ID, notification)
    }

    companion object {
        const val UNIQUE = "vnss-daily-reminder"
        private const val CHANNEL = "vnss_reminder"
        private const val NOTIF_ID = 41
    }
}
