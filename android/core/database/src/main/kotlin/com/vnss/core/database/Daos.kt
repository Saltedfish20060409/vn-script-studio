package com.vnss.core.database

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Dao
interface ProjectDao {

    @Query(
        """
        SELECT p.id AS id, p.title AS title, p.logline AS logline, p.genre AS genre,
               COALESCE(p.listUpdatedAt, p.serverUpdatedAt) AS updatedAt,
               MAX(p.chaptersCount, (SELECT COUNT(*) FROM chapters c WHERE c.projectId = p.id)) AS chaptersCount,
               (SELECT COUNT(*) FROM chapters c WHERE c.projectId = p.id AND c.syncState = 'DIRTY') AS dirtyChapters,
               (SELECT COUNT(*) FROM chapters c WHERE c.projectId = p.id AND c.syncState = 'CONFLICT') AS conflictChapters
        FROM projects p
        ORDER BY p.listOrder ASC
        """,
    )
    fun observeRows(): Flow<List<ProjectRow>>

    @Query("SELECT * FROM projects WHERE id = :id")
    fun observe(id: String): Flow<ProjectEntity?>

    @Query("SELECT * FROM projects WHERE id = :id")
    suspend fun get(id: String): ProjectEntity?

    @Query("SELECT id FROM projects")
    suspend fun allIds(): List<String>

    @Query("SELECT COALESCE(MIN(listOrder), 0) FROM projects")
    suspend fun minOrder(): Int

    @Upsert
    suspend fun upsert(entity: ProjectEntity)

    @Query("DELETE FROM projects WHERE id IN (:ids)")
    suspend fun delete(ids: List<String>)

    @Query("UPDATE projects SET serverUpdatedAt = :updatedAt WHERE id = :id")
    suspend fun updateServerVersion(id: String, updatedAt: String?)

    @Query("DELETE FROM projects")
    suspend fun clear()
}

@Dao
interface ChapterDao {

    @Query(
        """
        SELECT id, projectId, title, synopsis, volumeId, words, syncState, syncError, published
        FROM chapters WHERE projectId = :projectId ORDER BY orderIndex ASC
        """,
    )
    fun observeRows(projectId: String): Flow<List<ChapterRow>>

    @Query("SELECT * FROM chapters WHERE id = :id")
    fun observe(id: String): Flow<ChapterEntity?>

    @Query("SELECT * FROM chapters WHERE id = :id")
    suspend fun get(id: String): ChapterEntity?

    @Query("SELECT * FROM chapters WHERE projectId = :projectId ORDER BY orderIndex ASC")
    suspend fun listByProject(projectId: String): List<ChapterEntity>

    @Query("SELECT * FROM chapters WHERE projectId = :projectId AND syncState = 'DIRTY' ORDER BY orderIndex ASC")
    suspend fun dirty(projectId: String): List<ChapterEntity>

    @Query("SELECT DISTINCT projectId FROM chapters WHERE syncState = 'DIRTY'")
    suspend fun projectIdsWithDirty(): List<String>

    /** 待同步 + 冲突，顶栏角标用。 */
    @Query("SELECT COUNT(*) FROM chapters WHERE syncState != 'SYNCED'")
    fun observePendingCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM chapters WHERE syncState != 'SYNCED'")
    suspend fun pendingCount(): Int

    @Query("SELECT COALESCE(MAX(orderIndex), -1) FROM chapters WHERE projectId = :projectId")
    suspend fun maxOrder(projectId: String): Int
    @Upsert
    suspend fun upsert(entity: ChapterEntity)

    @Upsert
    suspend fun upsertAll(entities: List<ChapterEntity>)

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertIgnore(entity: ChapterEntity): Long

    /**
     * 写草稿：只动 title / prose / words / 状态。
     * 冲突中的章节保持 CONFLICT（用户裁决前不能把冲突标记洗掉），其它一律置 DIRTY。
     */
    @Query(
        """
        UPDATE chapters
        SET title = :title, prose = :prose, words = :words, localUpdatedAt = :now, syncError = NULL,
            syncState = CASE WHEN syncState = 'CONFLICT' THEN 'CONFLICT' ELSE 'DIRTY' END
        WHERE id = :id
        """,
    )
    suspend fun writeDraft(id: String, title: String, prose: String, words: Int, now: Long): Int

    @Query("UPDATE chapters SET syncError = :error WHERE id = :id")
    suspend fun setSyncError(id: String, error: String?)

    @Query("DELETE FROM chapters WHERE id IN (:ids)")
    suspend fun delete(ids: List<String>)

    @Query("DELETE FROM chapters WHERE projectId = :projectId")
    suspend fun deleteByProject(projectId: String)

    @Query("DELETE FROM chapters")
    suspend fun clear()
}
