package com.vnss.core.database.di

import android.content.Context
import androidx.room.Room
import com.vnss.core.database.ChapterDao
import com.vnss.core.database.ProjectDao
import com.vnss.core.database.VnssDatabase
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): VnssDatabase =
        Room.databaseBuilder(context, VnssDatabase::class.java, VnssDatabase.NAME).build()

    @Provides
    fun provideProjectDao(db: VnssDatabase): ProjectDao = db.projectDao()

    @Provides
    fun provideChapterDao(db: VnssDatabase): ChapterDao = db.chapterDao()
}
