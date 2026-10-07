package com.vnss.core.data.di

import com.vnss.core.common.DefaultDispatcherProvider
import com.vnss.core.common.DispatcherProvider
import com.vnss.core.data.repo.AgentRepositoryImpl
import com.vnss.core.data.repo.AuthRepositoryImpl
import com.vnss.core.data.repo.CollabRepositoryImpl
import com.vnss.core.data.repo.LedgerRepositoryImpl
import com.vnss.core.data.repo.OfflineProjectRepository
import com.vnss.core.data.repo.SettingsRepositoryImpl
import com.vnss.core.data.work.ReminderSchedulerImpl
import com.vnss.core.data.work.SyncSchedulerImpl
import com.vnss.core.model.AgentRepository
import com.vnss.core.model.AuthRepository
import com.vnss.core.model.CollabRepository
import com.vnss.core.model.LedgerRepository
import com.vnss.core.model.ProjectRepository
import com.vnss.core.model.ReminderScheduler
import com.vnss.core.model.SettingsRepository
import com.vnss.core.model.SyncRepository
import com.vnss.core.model.SyncScheduler
import dagger.Binds
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import javax.inject.Named
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class DataBindingsModule {
    @Binds abstract fun auth(impl: AuthRepositoryImpl): AuthRepository
    @Binds abstract fun projects(impl: OfflineProjectRepository): ProjectRepository
    @Binds abstract fun sync(impl: OfflineProjectRepository): SyncRepository
    @Binds abstract fun agent(impl: AgentRepositoryImpl): AgentRepository
    @Binds abstract fun ledger(impl: LedgerRepositoryImpl): LedgerRepository
    @Binds abstract fun collab(impl: CollabRepositoryImpl): CollabRepository
    @Binds abstract fun settings(impl: SettingsRepositoryImpl): SettingsRepository
    @Binds abstract fun syncScheduler(impl: SyncSchedulerImpl): SyncScheduler
    @Binds abstract fun reminders(impl: ReminderSchedulerImpl): ReminderScheduler
}

@Module
@InstallIn(SingletonComponent::class)
object DataProvidersModule {
    @Provides
    @Singleton
    fun dispatchers(): DispatcherProvider = DefaultDispatcherProvider

    @Provides
    @Singleton
    @Named("appScope")
    fun appScope(): CoroutineScope = CoroutineScope(SupervisorJob() + DefaultDispatcherProvider.default)
}
