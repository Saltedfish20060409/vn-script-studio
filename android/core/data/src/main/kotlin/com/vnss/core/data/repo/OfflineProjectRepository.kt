package com.vnss.core.data.repo

import com.vnss.core.common.AppError
import com.vnss.core.common.DispatcherProvider
import com.vnss.core.common.Outcome
import com.vnss.core.common.WordCount
import com.vnss.core.common.outcomeOf
import com.vnss.core.database.ChapterDao
import com.vnss.core.database.ChapterEntity
import com.vnss.core.database.ProjectDao
import com.vnss.core.database.SyncStates
import com.vnss.core.database.VnssDatabase
import com.vnss.core.data.json.ProjectJson
import com.vnss.core.data.json.str
import com.vnss.core.data.sync.SyncPlanner
import com.vnss.core.datastore.LocalSettingsStore
import com.vnss.core.model.Chapter
import com.vnss.core.model.ChapterConflict
import com.vnss.core.model.ChapterSummary
import com.vnss.core.model.ConflictResolution
import com.vnss.core.model.Project
import com.vnss.core.model.ProjectRepository
import com.vnss.core.model.ProjectSummary
import com.vnss.core.model.SyncReport
import com.vnss.core.model.SyncRepository
import com.vnss.core.model.SyncScheduler
import com.vnss.core.network.api.VnssApi
import com.vnss.core.network.apiCall
import com.vnss.core.network.dto.CreateProjectRequest
import com.vnss.core.network.dto.ProjectPutRequest
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class OfflineProjectRepository @Inject constructor(
    private val api: VnssApi,
    private val projects: ProjectDao,
    private val chapters: ChapterDao,
    private val db: VnssDatabase,
    private val settings: LocalSettingsStore,
    private val scheduler: SyncScheduler,
    private val dispatchers: DispatcherProvider,
) : ProjectRepository, SyncRepository {

    private val mutex = Mutex()

    override fun observeProjects(): Flow<List<ProjectSummary>> = projects.observeRows().map { rows ->
        rows.map {
            ProjectSummary(
                id = it.id,
                title = it.title,
                logline = it.logline,
                genre = it.genre,
                chaptersCount = it.chaptersCount,
                updatedAt = it.updatedAt,
                dirtyChapters = it.dirtyChapters,
                conflictChapters = it.conflictChapters,
            )
        }
    }

    override fun observeProject(projectId: String): Flow<Project?> =
        projects.observe(projectId).map { it?.let(ProjectJson::toDomain) }

    override fun observeChapters(projectId: String): Flow<List<ChapterSummary>> =
        chapters.observeRows(projectId).map { rows ->
            rows.map {
                ChapterSummary(
                    id = it.id,
                    projectId = it.projectId,
                    title = it.title,
                    synopsis = it.synopsis,
                    volumeId = it.volumeId,
                    words = it.words,
                    syncState = ProjectJson.syncState(it.syncState),
                    syncError = it.syncError,
                    published = it.published,
                )
            }
        }

    override fun observeChapter(chapterId: String): Flow<Chapter?> =
        chapters.observe(chapterId).map { it?.let(ProjectJson::toDomain) }

    override suspend fun refreshProjects(): Outcome<Unit> = withContext(dispatchers.io) {
        outcomeOf {
            val list = apiCall { api.listProjects() }
            val existing = projects.allIds().toSet()
            val keep = HashSet<String>()
            list.forEachIndexed { index, dto ->
                keep += dto.id
                val prev = projects.get(dto.id)
                projects.upsert(
                    ProjectJson.listEntity(
                        id = dto.id,
                        title = dto.title,
                        logline = dto.logline,
                        genre = dto.genre,
                        updatedAt = dto.updatedAt,
                        chaptersCount = dto.chaptersCount,
                        listOrder = index,
                        existing = prev,
                    ),
                )
            }
            val gone = existing - keep
            if (gone.isNotEmpty()) {
                val drop = gone.filter { id ->
                    chapters.listByProject(id).none { it.syncState != SyncStates.SYNCED }
                }
                if (drop.isNotEmpty()) projects.delete(drop)
            }
        }
    }

    override suspend fun refreshProject(projectId: String): Outcome<Unit> = withContext(dispatchers.io) {
        outcomeOf {
            val root = apiCall { api.getProject(projectId) }
            applyServerSnapshot(root, preserveLocalEdits = true)
        }
    }

    override suspend fun createProject(title: String): Outcome<String> = withContext(dispatchers.io) {
        outcomeOf {
            val root = apiCall { api.createProject(CreateProjectRequest(title = title.trim().ifBlank { null })) }
            applyServerSnapshot(root, preserveLocalEdits = false)
            ProjectJson.parse(root).id
        }
    }

    override suspend fun createChapter(projectId: String, title: String): String = withContext(dispatchers.io) {
        val id = "ch-${UUID.randomUUID()}"
        val order = chapters.maxOrder(projectId) + 1
        val now = System.currentTimeMillis()
        chapters.upsert(ProjectJson.newLocalChapter(id, projectId, title.trim(), order, now))
        scheduler.scheduleSync()
        id
    }

    override suspend fun saveDraft(chapterId: String, title: String, prose: String) {
        withContext(dispatchers.io) {
            val words = WordCount.count(prose)
            val now = System.currentTimeMillis()
            val n = chapters.writeDraft(chapterId, title, prose, words, now)
            if (n == 0) return@withContext
            settings.update { it.copy(lastWriteAt = now) }
            scheduler.scheduleSync()
        }
    }

    override fun observePendingCount(): Flow<Int> = chapters.observePendingCount()

    override suspend fun syncProject(projectId: String): SyncReport = withContext(dispatchers.io) {
        mutex.withLock { pushProject(projectId) }
    }

    override suspend fun syncAll(): SyncReport = withContext(dispatchers.io) {
        mutex.withLock {
            val ids = (chapters.projectIdsWithDirty() + projects.allIds()).distinct()
            ids.fold(SyncReport()) { acc, id -> acc + pushProject(id) }
        }
    }

    override suspend fun loadConflict(chapterId: String): ChapterConflict? = withContext(dispatchers.io) {
        val ch = chapters.get(chapterId) ?: return@withContext null
        if (ch.syncState != SyncStates.CONFLICT) return@withContext null
        ChapterConflict(
            chapterId = ch.id,
            title = ch.title,
            base = ch.baseProse,
            local = ch.prose,
            remote = ch.remoteProse ?: "",
            remoteTitle = ch.remoteTitle ?: ch.title,
        )
    }

    override suspend fun resolveConflict(chapterId: String, resolution: ConflictResolution): Outcome<Unit> =
        withContext(dispatchers.io) {
            outcomeOf {
                val ch = chapters.get(chapterId) ?: throw AppError.Local("找不到这一章")
                if (ch.syncState != SyncStates.CONFLICT) return@outcomeOf
                val remoteProse = ch.remoteProse.orEmpty()
                val remoteTitle = ch.remoteTitle ?: ch.title
                val next = when (resolution) {
                    ConflictResolution.KEEP_MINE -> ch.copy(
                        syncState = SyncStates.DIRTY,
                        syncError = null,
                        remoteProse = null,
                        remoteTitle = null,
                    )
                    ConflictResolution.USE_SERVER -> ch.copy(
                        title = remoteTitle,
                        prose = remoteProse,
                        words = WordCount.count(remoteProse),
                        baseProse = remoteProse,
                        baseTitle = remoteTitle,
                        syncState = SyncStates.SYNCED,
                        syncError = null,
                        remoteProse = null,
                        remoteTitle = null,
                    )
                    ConflictResolution.KEEP_BOTH -> {
                        val prose = SyncPlanner.keepBoth(ch.prose, remoteProse)
                        val title = SyncPlanner.keepBothTitle(ch.title, remoteTitle)
                        ch.copy(
                            title = title,
                            prose = prose,
                            words = WordCount.count(prose),
                            syncState = SyncStates.DIRTY,
                            syncError = null,
                            remoteProse = null,
                            remoteTitle = null,
                        )
                    }
                }
                chapters.upsert(next)
                if (next.syncState == SyncStates.DIRTY) scheduler.scheduleSync(delaySeconds = 1)
            }
        }

    private suspend fun pushProject(projectId: String): SyncReport {
        val dirty = chapters.dirty(projectId)
        val conflictsBefore = chapters.listByProject(projectId).count { it.syncState == SyncStates.CONFLICT }
        if (dirty.isEmpty()) {
            return SyncReport(conflicts = conflictsBefore)
        }
        val root = try {
            apiCall { api.getProject(projectId) }
        } catch (e: AppError) {
            markErrors(dirty, e.message)
            return SyncReport(failed = dirty.size, retryable = e.isRetryable, message = e.message, conflicts = conflictsBefore)
        }
        applyServerSnapshot(root, preserveLocalEdits = true)

        val remoteById = ProjectJson.parse(root).chapters.associateBy { it.str("id").orEmpty() }
        val toUpload = ArrayList<ChapterEntity>()
        var merged = 0
        var conflicts = 0
        for (local in dirty) {
            val remote = remoteById[local.id]
            val decision = SyncPlanner.decide(
                baseProse = local.baseProse,
                baseTitle = local.baseTitle,
                localProse = local.prose,
                localTitle = local.title,
                remoteProse = remote?.let { it.str("prose").orEmpty() },
                remoteTitle = remote?.str("title"),
            )
            when (decision) {
                SyncPlanner.Decision.AlreadyEqual -> {
                    chapters.upsert(
                        local.copy(
                            syncState = SyncStates.SYNCED,
                            isNew = false,
                            syncError = null,
                            baseProse = local.prose,
                            baseTitle = local.title,
                            remoteProse = null,
                            remoteTitle = null,
                        ),
                    )
                }
                SyncPlanner.Decision.UploadLocal -> toUpload += local
                is SyncPlanner.Decision.UploadMerged -> {
                    merged++
                    val updated = local.copy(
                        prose = decision.prose,
                        title = decision.title,
                        words = WordCount.count(decision.prose),
                    )
                    chapters.upsert(updated)
                    toUpload += updated
                }
                SyncPlanner.Decision.Conflict -> {
                    conflicts++
                    val rProse = remote?.str("prose").orEmpty()
                    val rTitle = remote?.str("title").orEmpty()
                    chapters.upsert(
                        local.copy(
                            syncState = SyncStates.CONFLICT,
                            remoteProse = rProse,
                            remoteTitle = rTitle,
                            syncError = null,
                        ),
                    )
                }
            }
        }
        if (toUpload.isEmpty()) {
            return SyncReport(merged = merged, conflicts = conflicts + conflictsBefore)
        }

        val overlay = toUpload.associate { it.id to ProjectJson.overlayForUpload(it) }
        val payload = ProjectJson.replaceChapters(root, overlay)
        return try {
            val saved = apiCall {
                api.putProject(
                    projectId,
                    ProjectPutRequest(
                        data = payload,
                        updatedAt = ProjectJson.parse(root).updatedAt,
                        force = false,
                        chapterIds = toUpload.map { it.id },
                    ),
                )
            }
            val uploaded = toUpload.associate { it.id to (it.title to it.prose) }
            applyServerSnapshot(saved, preserveLocalEdits = true, overwriteIfUnchanged = uploaded)
            SyncReport(pushed = toUpload.size, merged = merged, conflicts = conflicts)
        } catch (e: AppError) {
            when (e) {
                is AppError.Conflict -> {
                    runCatching { refreshProject(projectId) }
                    SyncReport(failed = toUpload.size, retryable = true, message = e.message, merged = merged, conflicts = conflicts)
                }
                is AppError.Locked -> {
                    markErrors(toUpload, e.message)
                    SyncReport(failed = toUpload.size, retryable = true, message = e.message, merged = merged, conflicts = conflicts)
                }
                else -> {
                    markErrors(toUpload, e.message)
                    SyncReport(failed = toUpload.size, retryable = e.isRetryable, message = e.message, merged = merged, conflicts = conflicts)
                }
            }
        }
    }

    private suspend fun markErrors(items: List<ChapterEntity>, message: String) {
        for (ch in items) chapters.setSyncError(ch.id, message)
    }

    private suspend fun applyServerSnapshot(
        root: JsonObject,
        preserveLocalEdits: Boolean,
        overwriteIfUnchanged: Map<String, Pair<String, String>> = emptyMap(),
    ) {
        val parsed = ProjectJson.parse(root)
        val now = System.currentTimeMillis()
        val existingProject = projects.get(parsed.id)
        val order = existingProject?.listOrder ?: (projects.minOrder() - 1)
        projects.upsert(
            ProjectJson.projectEntity(parsed, listOrder = order, listUpdatedAt = existingProject?.listUpdatedAt, now = now)
                .copy(listUpdatedAt = existingProject?.listUpdatedAt ?: parsed.updatedAt),
        )
        val locals = chapters.listByProject(parsed.id).associateBy { it.id }
        val keep = HashSet<String>()
        parsed.chapters.forEachIndexed { index, json ->
            val id = json.str("id") ?: return@forEachIndexed
            keep += id
            val local = locals[id]
            val uploaded = overwriteIfUnchanged[id]
            val keepLocal = preserveLocalEdits && local != null && local.syncState != SyncStates.SYNCED &&
                (uploaded == null || local.title != uploaded.first || local.prose != uploaded.second)
            if (keepLocal && local != null) {
                chapters.upsert(local.copy(orderIndex = index, synopsis = json.str("synopsis") ?: local.synopsis))
            } else {
                chapters.upsert(ProjectJson.chapterFromServer(parsed.id, index, json, now))
            }
        }
        val drop = locals.keys - keep
        if (drop.isNotEmpty()) {
            val removable = drop.filter { id ->
                val local = locals[id] ?: return@filter true
                local.syncState == SyncStates.SYNCED && !local.isNew
            }
            if (removable.isNotEmpty()) chapters.delete(removable)
        }
    }

    suspend fun clearLocalLibrary() {
        db.clearAllTables()
    }
}


