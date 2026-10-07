package com.vnss.core.data.repo

import com.vnss.core.common.AppError
import com.vnss.core.common.DispatcherProvider
import com.vnss.core.common.Outcome
import com.vnss.core.common.outcomeOf
import com.vnss.core.model.ChapterLock
import com.vnss.core.model.CollabEvent
import com.vnss.core.model.CollabRepository
import com.vnss.core.model.Comment
import com.vnss.core.model.Member
import com.vnss.core.network.ApiEndpoints
import com.vnss.core.network.SseClient
import com.vnss.core.network.VnssJson
import com.vnss.core.network.api.VnssApi
import com.vnss.core.network.apiCall
import com.vnss.core.network.dto.CommentCreateRequest
import com.vnss.core.network.dto.CommentDto
import com.vnss.core.network.dto.CommentUpdateRequest
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.retryWhen
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class CollabRepositoryImpl @Inject constructor(
    private val api: VnssApi,
    private val sse: SseClient,
    private val dispatchers: DispatcherProvider,
) : CollabRepository {

    override suspend fun members(projectId: String): Outcome<List<Member>> = withContext(dispatchers.io) {
        outcomeOf {
            val env = apiCall { api.members(projectId) }
            buildList {
                if (env.owner.userId.isNotBlank()) {
                    add(Member(env.owner.userId, env.owner.username, env.owner.role.ifBlank { "owner" }))
                }
                addAll(env.members.map { Member(it.userId, it.username, it.role) })
            }.distinctBy { it.userId }
        }
    }

    override suspend fun locks(projectId: String): Outcome<List<ChapterLock>> = withContext(dispatchers.io) {
        outcomeOf {
            apiCall { api.locks(projectId) }.locks.map {
                ChapterLock(it.chapterId, it.userId, it.username, it.expiresAt)
            }
        }
    }

    override suspend fun comments(projectId: String, chapterId: String?): Outcome<List<Comment>> =
        withContext(dispatchers.io) {
            outcomeOf { apiCall { api.comments(projectId, chapterId) }.comments.map { it.toDomain() } }
        }

    override suspend fun addComment(
        projectId: String,
        chapterId: String,
        text: String,
        anchor: String,
        parentId: String?,
    ): Outcome<Comment> = withContext(dispatchers.io) {
        outcomeOf {
            apiCall {
                api.addComment(
                    projectId,
                    CommentCreateRequest(chapterId, text, anchor, parentId?.takeIf { it.isNotBlank() }),
                )
            }.toDomain()
        }
    }

    override suspend fun setResolved(projectId: String, commentId: String, resolved: Boolean): Outcome<Comment> =
        withContext(dispatchers.io) {
            outcomeOf { apiCall { api.updateComment(projectId, commentId, CommentUpdateRequest(resolved = resolved)) }.toDomain() }
        }

    override suspend fun deleteComment(projectId: String, commentId: String): Outcome<Unit> =
        withContext(dispatchers.io) {
            outcomeOf { apiCall { api.deleteComment(projectId, commentId) }; Unit }
        }

    override fun events(projectId: String): Flow<CollabEvent> = flow {
        var delayMs = 1_000L
        while (true) {
            try {
                sse.get(ApiEndpoints.projectEvents(projectId)).collect { msg ->
                    delayMs = 1_000L
                    emit(parse(msg.type, msg.data))
                }
            } catch (e: AppError) {
                if (e is AppError.Unauthorized || e is AppError.Forbidden) throw e
            }
            emit(CollabEvent.Other)
            delay(delayMs)
            delayMs = (delayMs * 2).coerceAtMost(30_000L)
        }
    }

    private fun parse(type: String?, data: String): CollabEvent {
        val obj = runCatching { VnssJson.parseToJsonElement(data).jsonObject }.getOrNull()
        val kind = type ?: obj.string("type") ?: return CollabEvent.Other
        val eventKind = obj.string("kind").orEmpty()
        return when (kind) {
            "member" -> CollabEvent.MemberChanged(eventKind)
            "lock" -> CollabEvent.LockChanged(eventKind, obj.string("chapterId"), obj.string("userId"))
            "comment" -> CollabEvent.CommentChanged(eventKind, obj.string("chapterId"))
            else -> CollabEvent.Other
        }
    }

    private fun JsonObject?.string(key: String): String? =
        (this?.get(key) as? JsonPrimitive)?.contentOrNull

    private fun CommentDto.toDomain() = Comment(
        id = id,
        chapterId = chapterId,
        anchor = anchor,
        parentId = parentId.takeIf { it.isNotBlank() },
        userId = userId,
        username = username,
        text = text,
        resolved = resolved,
        createdAt = createdAt,
    )
}
