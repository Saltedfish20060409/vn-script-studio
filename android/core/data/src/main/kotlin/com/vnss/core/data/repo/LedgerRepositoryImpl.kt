package com.vnss.core.data.repo

import com.vnss.core.common.DispatcherProvider
import com.vnss.core.common.Outcome
import com.vnss.core.common.outcomeOf
import com.vnss.core.database.ChapterDao
import com.vnss.core.database.ProjectDao
import com.vnss.core.data.json.ProjectJson
import com.vnss.core.model.Ledger
import com.vnss.core.model.LedgerRepository
import com.vnss.core.model.ProjectRepository
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class LedgerRepositoryImpl @Inject constructor(
    private val projects: ProjectDao,
    private val chapters: ChapterDao,
    private val projectRepo: ProjectRepository,
    private val dispatchers: DispatcherProvider,
) : LedgerRepository {

    override fun observeLedger(projectId: String): Flow<Ledger> =
        combine(projects.observe(projectId), chapters.observeRows(projectId)) { entity, rows ->
            if (entity == null) return@combine Ledger.EMPTY
            val titles = rows.associate { it.id to it.title }
            ProjectJson.parseLedger(entity.ledgerJson, entity.chapterIndexJson, titles)
        }

    override suspend fun refresh(projectId: String): Outcome<Unit> = withContext(dispatchers.io) {
        outcomeOf { projectRepo.refreshProject(projectId).let { r ->
            if (r is Outcome.Failure) throw r.error
        } }
    }
}
