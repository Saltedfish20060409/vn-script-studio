package com.vnss.core.database

import androidx.room.Database
import androidx.room.RoomDatabase

/**
 * 版本管理约定：**不使用** `fallbackToDestructiveMigration`。
 * `chapters` 里可能躺着还没上传的草稿，破坏性迁移 = 用户丢稿。每次升级必须写显式 Migration，
 * schema JSON 导出到 `schemas/` 并入库，便于 review。
 */
@Database(
    entities = [ProjectEntity::class, ChapterEntity::class],
    version = 1,
    exportSchema = true,
)
abstract class VnssDatabase : RoomDatabase() {
    abstract fun projectDao(): ProjectDao
    abstract fun chapterDao(): ChapterDao

    companion object {
        const val NAME = "vnss.db"
    }
}
