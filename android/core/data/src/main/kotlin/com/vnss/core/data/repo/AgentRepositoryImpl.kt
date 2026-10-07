package com.vnss.core.data.repo

import com.vnss.core.common.AppError
import com.vnss.core.common.DispatcherProvider
import com.vnss.core.common.Outcome
import com.vnss.core.common.outcomeOf
import com.vnss.core.model.AgentConversation
import com.vnss.core.model.AgentConversationSummary
import com.vnss.core.model.AgentEvent
import com.vnss.core.model.AgentMessage
import com.vnss.core.model.AgentRepository
import com.vnss.core.model.AgentRole
import com.vnss.core.model.AgentRunRequest
import com.vnss.core.model.AgentRunResult
import com.vnss.core.model.AgentToolStep
import com.vnss.core.model.AuthorLens
import com.vnss.core.model.ProjectLenses
import com.vnss.core.model.ProjectRepository
import com.vnss.core.model.SyncRepository
import com.vnss.core.network.ApiEndpoints
import com.vnss.core.network.SseClient
import com.vnss.core.network.VnssJson
import com.vnss.core.network.api.VnssApi
import com.vnss.core.network.apiCall
import com.vnss.core.network.dto.AgentRunRequestDto
import com.vnss.core.network.dto.CreateConversationRequest
import com.vnss.core.network.dto.LensPackDto
import com.vnss.core.network.dto.ProjectLensesPutRequest
import com.vnss.core.network.dto.PutConversationRequest
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class AgentRepositoryImpl @Inject constructor(
    private val api: VnssApi,
    private val sse: SseClient,
    private val sync: SyncRepository,
    private val projects: ProjectRepository,
    private val dispatchers: DispatcherProvider,
) : AgentRepository {

    override suspend fun listConversations(projectId: String): Outcome<List<AgentConversationSummary>> =
        withContext(dispatchers.io) {
            outcomeOf {
                apiCall { api.listConversations(projectId) }.map {
                    AgentConversationSummary(it.id, it.title, it.messageCount, it.updatedAt)
                }
            }
        }

    override suspend fun createConversation(projectId: String, title: String?): Outcome<AgentConversation> =
        withContext(dispatchers.io) {
            outcomeOf {
                val dto = apiCall { api.createConversation(projectId, CreateConversationRequest(title)) }
                dto.toDomain()
            }
        }

    override suspend fun loadConversation(projectId: String, conversationId: String): Outcome<AgentConversation> =
        withContext(dispatchers.io) {
            outcomeOf { apiCall { api.getConversation(projectId, conversationId) }.toDomain() }
        }

    override suspend fun saveConversation(
        projectId: String,
        conversationId: String,
        messages: List<AgentMessage>,
    ): Outcome<Unit> = withContext(dispatchers.io) {
        outcomeOf {
            apiCall {
                api.putConversation(
                    projectId,
                    conversationId,
                    PutConversationRequest(messages.map { it.toJson() }),
                )
            }
            Unit
        }
    }

    override suspend fun loadLenses(projectId: String): Outcome<ProjectLenses> =
        withContext(dispatchers.io) {
            outcomeOf {
                val project = apiCall { api.getProjectLenses(projectId) }
                val catalog = apiCall { api.listLenses() }
                val byId = linkedMapOf<String, AuthorLens>()
                for (p in catalog.packs + project.builtin + project.customPacks + project.active) {
                    val id = p.id.trim()
                    if (id.isEmpty() || id in byId) continue
                    byId[id] = p.toDomain()
                }
                ProjectLenses(
                    activeIds = project.activeIds.map { it.trim() }.filter { it.isNotEmpty() }.distinct().take(catalog.maxActive.coerceAtLeast(1)),
                    catalog = byId.values.toList(),
                    maxActive = catalog.maxActive.coerceIn(1, 3),
                )
            }
        }

    override suspend fun setActiveLenses(projectId: String, activeIds: List<String>): Outcome<List<String>> =
        withContext(dispatchers.io) {
            outcomeOf {
                val ids = activeIds.map { it.trim() }.filter { it.isNotEmpty() }.distinct().take(3)
                apiCall { api.putProjectLenses(projectId, ProjectLensesPutRequest(ids)) }.activeIds
            }
        }

    override fun run(request: AgentRunRequest): Flow<AgentEvent> = flow {
        val report = sync.syncProject(request.projectId)
        if (report.conflicts > 0) {
            emit(AgentEvent.Error("有 ${report.conflicts} 章尚未处理冲突，无法运行 Agent。请先在章节列表处理。"))
            return@flow
        }
        if (report.failed > 0) {
            emit(AgentEvent.Error(report.message ?: "稿子还没同步成功，Agent 拒绝在旧稿上改写。请联网后重试。"))
            return@flow
        }
        val body = AgentRunRequestDto(
            messages = request.messages.map { it.toJson() },
            chapterId = request.chapterId,
            selection = request.selection,
            conversationId = request.conversationId,
            applyActions = request.applyActions,
            resume = request.resume,
            writingSurface = "prose",
            lensIds = request.lensIds.takeIf { it.isNotEmpty() },
        )
        val json = VnssJson.encodeToString(AgentRunRequestDto.serializer(), body)
        sse.post(ApiEndpoints.agentStream(request.projectId), json).map { msg ->
            parseEvent(msg.type, msg.data)
        }.collect { event ->
            if (event != null) emit(event)
            if (event is AgentEvent.Final && event.result.applied) {
                projects.refreshProject(request.projectId)
            }
        }
    }.catch { e ->
        emit(AgentEvent.Error((e as? AppError)?.message ?: e.message ?: "Agent 连接中断"))
    }

    private fun parseEvent(type: String?, data: String): AgentEvent? {
        val obj = runCatching { VnssJson.parseToJsonElement(data).jsonObject }.getOrNull()
        val kind = type ?: obj?.string("type") ?: return null
        return when (kind) {
            "task" -> AgentEvent.Task(obj.string("task") ?: obj.string("text") ?: "")
            "thought" -> AgentEvent.Thought(obj.string("text").orEmpty())
            "tool_call" -> AgentEvent.ToolCall(
                AgentToolStep(obj.string("name").orEmpty(), obj.string("preview") ?: summarizeArgs(obj)),
            )
            "tool_result" -> AgentEvent.ToolResult(
                AgentToolStep(obj.string("name").orEmpty(), obj.string("preview").orEmpty()),
            )
            "actions" -> AgentEvent.Actions(obj?.get("actions")?.let { el ->
                (el as? kotlinx.serialization.json.JsonArray)?.size
            } ?: obj?.int("count") ?: 0)
            "review" -> AgentEvent.Review(obj.string("note") ?: obj.string("text").orEmpty())
            "error" -> AgentEvent.Error(obj.string("message") ?: "Agent 运行失败")
            "done", "final" -> {
                val result = obj?.get("result")?.jsonObject ?: obj
                AgentEvent.Final(parseResult(result))
            }
            else -> null
        }
    }

    private fun parseResult(obj: JsonObject?): AgentRunResult {
        if (obj == null) {
            return AgentRunResult("", false, emptyList(), null, null, 0)
        }
        val actions = obj["actions"] as? kotlinx.serialization.json.JsonArray
        val warnings = (obj["warnings"] as? kotlinx.serialization.json.JsonArray)
            ?.mapNotNull { (it as? JsonPrimitive)?.contentOrNull }
            .orEmpty()
        return AgentRunResult(
            message = obj.string("message").orEmpty(),
            applied = (obj["applied"] as? JsonPrimitive)?.booleanOrNull == true,
            warnings = warnings,
            conversationId = obj.string("conversation_id") ?: obj.string("conversationId"),
            model = obj.string("model"),
            actionCount = actions?.size ?: obj.int("actionCount") ?: 0,
        )
    }

    private fun summarizeArgs(obj: JsonObject?): String {
        val args = obj?.get("arguments") ?: return ""
        return args.toString().take(80)
    }

    private fun JsonObject?.string(key: String): String? =
        (this?.get(key) as? JsonPrimitive)?.contentOrNull

    private fun JsonObject?.int(key: String): Int? =
        (this?.get(key) as? JsonPrimitive)?.intOrNull

    private fun com.vnss.core.network.dto.AgentConversationDto.toDomain() = AgentConversation(
        id = id,
        title = title,
        messages = messages.mapNotNull { it.toMessage() },
        resumable = runState != null,
    )

    private fun JsonObject.toMessage(): AgentMessage? {
        val role = string("role") ?: return null
        val content = string("content") ?: return null
        val mapped = when (role) {
            "user" -> AgentRole.USER
            "assistant" -> AgentRole.ASSISTANT
            else -> return null
        }
        return AgentMessage(mapped, content)
    }

    private fun AgentMessage.toJson(): JsonObject = buildJsonObject {
        put("role", if (role == AgentRole.USER) "user" else "assistant")
        put("content", content)
    }

    private fun LensPackDto.toDomain() = AuthorLens(
        id = id,
        name = name.ifBlank { id },
        tags = tags,
    )
}
