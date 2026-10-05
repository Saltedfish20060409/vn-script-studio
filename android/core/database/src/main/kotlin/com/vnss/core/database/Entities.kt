package com.vnss.core.database

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * 项目：列表元数据 + 账本 / 摘要的原始 JSON 缓存。
 *
 * 账本 / 章节索引存原始 JSON 而不是拆表：它们是「只读展示」数据，结构随后端演进（`writingLedger` 带
 * `extra="allow"`），拆表会把每次后端加字段都变成一次 Room 迁移。解析放在 data 层，容错处理。
 */
@Entity(tableName = "projects")
data class ProjectEntity(
    @PrimaryKey val id: String,
    val title: String,
    val logline: String?,
    val genre: String?,
    /** 最近一次拉全量时的服务端 `updatedAt`（ISO）。 */
    val serverUpdatedAt: String?,
    /** 列表接口给的 `updated_at`，仅用于展示（格式与 serverUpdatedAt 不同，不能互相比较）。 */
    val listUpdatedAt: String? = null,
    val chaptersCount: Int,
    /** 服务端列表顺序（updated_at 倒序）。 */
    val listOrder: Int,
    /** 是否已拉过全量（章节正文入库）。 */
    val detailLoaded: Boolean = false,
    val volumesJson: String? = null,
    val ledgerJson: String? = null,
    val chapterIndexJson: String? = null,
    val lastRefreshedAt: Long = 0L,
)

/**
 * 章节：本地 Room 是 Single Source of Truth，`syncState` 即「待同步队列」。
 *
 * - `prose` / `title`：用户当前看到并编辑的内容；
 * - `baseProse` / `baseTitle`：与服务端最后一次一致的版本，三方合并的「共同祖先」；
 * - `rawJson`：该章服务端原始 JSON（**不含 prose**），保存时在它上面改 `prose`/`title`，
 *   这样 blocks、nlRpyMap、volumeId 等移动端不认识的字段原样回传，不会被覆盖丢失；
 * - `remoteProse` / `remoteTitle`：冲突时暂存的服务端版本。
 */
@Entity(
    tableName = "chapters",
    foreignKeys = [
        ForeignKey(
            entity = ProjectEntity::class,
            parentColumns = ["id"],
            childColumns = ["projectId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index("projectId"), Index("syncState")],
)
data class ChapterEntity(
    @PrimaryKey val id: String,
    val projectId: String,
    val orderIndex: Int,
    val title: String,
    val synopsis: String?,
    val volumeId: String?,
    val prose: String,
    val words: Int,
    val published: Boolean,
    /** 服务端该章原本没有 prose、只有脚本 blocks。 */
    val scriptOnly: Boolean,
    val rawJson: String,
    val baseProse: String,
    val baseTitle: String,
    /** [SyncStates] 之一。 */
    val syncState: String,
    /** 本地新建、服务端还没有这章。 */
    val isNew: Boolean,
    val syncError: String?,
    val remoteProse: String?,
    val remoteTitle: String?,
    val localUpdatedAt: Long,
)

object SyncStates {
    const val SYNCED = "SYNCED"
    const val DIRTY = "DIRTY"
    const val CONFLICT = "CONFLICT"
}

/** 章节列表行（不含正文）：列表页订阅它，打字时不会触发整页重组。 */
data class ChapterRow(
    val id: String,
    val projectId: String,
    val title: String,
    val synopsis: String?,
    val volumeId: String?,
    val words: Int,
    val syncState: String,
    val syncError: String?,
    val published: Boolean,
)

data class ProjectRow(
    val id: String,
    val title: String,
    val logline: String?,
    val genre: String?,
    val updatedAt: String?,
    val chaptersCount: Int,
    val dirtyChapters: Int,
    val conflictChapters: Int,
)
