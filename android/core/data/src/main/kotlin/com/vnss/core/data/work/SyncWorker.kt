package com.vnss.core.data.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.vnss.core.model.SyncRepository
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject

@HiltWorker
class SyncWorker @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted params: WorkerParameters,
    private val sync: SyncRepository,
) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val report = runCatching { sync.syncAll() }.getOrElse { return Result.retry() }
        return if (report.failed > 0 && report.retryable) Result.retry() else Result.success()
    }

    companion object {
        const val ONESHOT = "vnss-sync-oneshot"
        const val PERIODIC = "vnss-sync-periodic"
    }
}
