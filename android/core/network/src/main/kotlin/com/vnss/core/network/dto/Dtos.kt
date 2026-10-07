package com.vnss.core.network.dto

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/** 线上契约 DTO。字段名严格对应后端 `app/schemas/__init__.py`。 */

// ------------------------------------------------------------------ auth

@Serializable
data class LoginRequest(val username: String, val password: String)

@Serializable
data class RegisterRequest(val username: String, val password: String, val email: String)

@Serializable
data class RegisterResponse(val ok: Boolean = true, val message: String = "", val email: String = "")

@Serializable
data class IdentifierRequest(val email: String)

@Serializable
data class OkMessageDto(val ok: Boolean = true, val message: String = "")

@Serializable
data class RefreshRequest(@SerialName("refresh_token") val refreshToken: String)

@Serializable
data class TokenDto(
    @SerialName("access_token") val accessToken: String,
    @SerialName("refresh_token") val refreshToken: String? = null,
    @SerialName("token_type") val tokenType: String = "bearer",
    @SerialName("expires_in") val expiresIn: Long? = null,
)

@Serializable
data class UserDto(
    val id: String,
    val username: String,
    val email: String? = null,
    @SerialName("email_verified") val emailVerified: Boolean = true,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("is_admin") val isAdmin: Boolean = false,
)

// ------------------------------------------------------------------ projects

@Serializable
data class ProjectSummaryDto(
    val id: String,
    val title: String,
    val logline: String? = null,
    val genre: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("chapters_count") val chaptersCount: Int = 0,
)

@Serializable
data class CreateProjectRequest(
    val title: String? = null,
    @SerialName("from_demo") val fromDemo: Boolean = false,
    @SerialName("template_id") val templateId: String? = null,
)

/**
 * 保存请求。移动端只用「章级保存」：`chapter_ids` 声明改过哪几章，服务端只合并这些章，
 * 其余章节与顶层字段保留服务端版本——这是移动端不会冲掉 Web 端设定/RPY 的关键。
 */
@Serializable
data class ProjectPutRequest(
    val data: JsonObject,
    @SerialName("updated_at") val updatedAt: String? = null,
    val force: Boolean = false,
    @SerialName("chapter_ids") val chapterIds: List<String>? = null,
    val sections: List<String>? = null,
)

// ------------------------------------------------------------------ agent

@Serializable
data class AgentRunRequestDto(
    val messages: List<JsonObject>,
    @SerialName("chapter_id") val chapterId: String? = null,
    val selection: String? = null,
    @SerialName("conversation_id") val conversationId: String? = null,
    @SerialName("apply_actions") val applyActions: Boolean = true,
    val resume: Boolean = false,
    @SerialName("writing_surface") val writingSurface: String? = "prose",
    @SerialName("lens_ids") val lensIds: List<String>? = null,
)

@Serializable
data class LensPackDto(
    val id: String = "",
    val name: String = "",
    val tags: List<String> = emptyList(),
)

@Serializable
data class LensesCatalogDto(
    val packs: List<LensPackDto> = emptyList(),
    val maxActive: Int = 3,
)

@Serializable
data class ProjectLensesDto(
    val activeIds: List<String> = emptyList(),
    val builtin: List<LensPackDto> = emptyList(),
    val customPacks: List<LensPackDto> = emptyList(),
    val active: List<LensPackDto> = emptyList(),
)

@Serializable
data class ProjectLensesPutRequest(
    val activeIds: List<String> = emptyList(),
)

@Serializable
data class ProjectLensesPutResponse(
    val activeIds: List<String> = emptyList(),
    val active: List<LensPackDto> = emptyList(),
)

@Serializable
data class AgentConversationSummaryDto(
    val id: String,
    val title: String = "新对话",
    @SerialName("message_count") val messageCount: Int = 0,
    @SerialName("updated_at") val updatedAt: String = "",
)

@Serializable
data class AgentConversationDto(
    val id: String,
    val title: String = "新对话",
    val messages: List<JsonObject> = emptyList(),
    @SerialName("chat_memory") val chatMemory: String = "",
    @SerialName("run_state") val runState: JsonObject? = null,
)

@Serializable
data class CreateConversationRequest(val title: String? = null)

@Serializable
data class PutConversationRequest(val messages: List<JsonObject>)

// ------------------------------------------------------------------ collab

@Serializable
data class CommentCreateRequest(
    @SerialName("chapter_id") val chapterId: String,
    val text: String,
    val anchor: String = "",
    @SerialName("parent_id") val parentId: String? = null,
)

@Serializable
data class CommentUpdateRequest(val text: String? = null, val resolved: Boolean? = null)

@Serializable
data class CommentDto(
    val id: String,
    val chapterId: String = "",
    val anchor: String = "",
    val parentId: String = "",
    val userId: String = "",
    val username: String = "",
    val text: String = "",
    val resolved: Boolean = false,
    val createdAt: String = "",
)

@Serializable
data class CommentsEnvelope(val comments: List<CommentDto> = emptyList())

@Serializable
data class LockDto(
    val chapterId: String,
    val userId: String = "",
    val username: String = "",
    val expiresAt: String = "",
)

@Serializable
data class LocksEnvelope(val locks: List<LockDto> = emptyList())

@Serializable
data class MemberDto(val userId: String = "", val username: String = "", val role: String = "")

@Serializable
data class MembersEnvelope(val owner: MemberDto = MemberDto(), val members: List<MemberDto> = emptyList())

// ------------------------------------------------------------------ settings / usage

@Serializable
data class SettingsDto(
    @SerialName("has_api_key") val hasApiKey: Boolean = false,
    @SerialName("api_key_masked") val apiKeyMasked: String = "",
    @SerialName("api_base_url") val apiBaseUrl: String = "",
    @SerialName("api_model") val apiModel: String = "",
    @SerialName("active_model") val activeModel: String = "",
    @SerialName("active_base_url") val activeBaseUrl: String = "",
    @SerialName("credential_source") val credentialSource: String = "server",
)

@Serializable
data class SettingsPutRequest(
    @SerialName("api_key") val apiKey: String? = null,
    @SerialName("api_base_url") val apiBaseUrl: String? = null,
    @SerialName("api_model") val apiModel: String? = null,
)

@Serializable
data class TestLlmRequest(
    @SerialName("api_key") val apiKey: String? = null,
    @SerialName("base_url") val baseUrl: String? = null,
    val model: String? = null,
)

@Serializable
data class TestLlmResponse(
    val ok: Boolean = false,
    @SerialName("latency_ms") val latencyMs: Long = 0,
    val model: String? = null,
    val error: String? = null,
)

@Serializable
data class UsageTotalsDto(
    val promptTokens: Long = 0,
    val completionTokens: Long = 0,
    val totalTokens: Long = 0,
    val calls: Long = 0,
)

@Serializable
data class UsageDto(val today: UsageTotalsDto = UsageTotalsDto(), val total: UsageTotalsDto = UsageTotalsDto())
