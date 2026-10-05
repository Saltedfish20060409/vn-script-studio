package com.vnss.core.model

/** 领域模型：与网络 DTO、Room 实体解耦，UI 与 feature 只认这一层。 */

data class User(
    val id: String,
    val username: String,
    val email: String?,
    val emailVerified: Boolean,
    val isAdmin: Boolean,
)

sealed interface SessionState {
    /** 还在读本地凭据 / 尝试刷新。 */
    data object Loading : SessionState
    data object SignedOut : SessionState
    data class SignedIn(val user: User?) : SessionState
}

/** 章节同步状态：本地 Room 是 Single Source of Truth，这个字段就是「待同步队列」。 */
enum class SyncState {
    /** 与服务端一致。 */
    SYNCED,

    /** 本地有未上传的修改。 */
    DIRTY,

    /** 本地与服务端都改过且无法自动合并，等待用户裁决。 */
    CONFLICT,
}

data class ProjectSummary(
    val id: String,
    val title: String,
    val logline: String?,
    val genre: String?,
    val chaptersCount: Int,
    val updatedAt: String?,
    val dirtyChapters: Int = 0,
    val conflictChapters: Int = 0,
)

data class Volume(val id: String, val title: String)

data class Project(
    val id: String,
    val title: String,
    val logline: String?,
    val genre: String?,
    val updatedAt: String?,
    val volumes: List<Volume> = emptyList(),
)

/** 章节列表项（不含正文，列表页订阅这个，避免每次打字都重组整页）。 */
data class ChapterSummary(
    val id: String,
    val projectId: String,
    val title: String,
    val synopsis: String?,
    val volumeId: String?,
    val words: Int,
    val syncState: SyncState,
    val syncError: String?,
    val published: Boolean,
)

data class Chapter(
    val id: String,
    val projectId: String,
    val title: String,
    val synopsis: String?,
    val prose: String,
    val volumeId: String?,
    val syncState: SyncState,
    val syncError: String?,
    /** 该章原本只有脚本 blocks、没有自然语言正文（移动端提示「在这里写的正文会成为主稿」）。 */
    val scriptOnly: Boolean,
)

/** 冲突详情：三份文本都给出来，UI 才能让用户裁决。 */
data class ChapterConflict(
    val chapterId: String,
    val title: String,
    val base: String,
    val local: String,
    val remote: String,
    val remoteTitle: String,
)

enum class ConflictResolution { KEEP_MINE, USE_SERVER, KEEP_BOTH }

data class SyncReport(
    val pushed: Int = 0,
    /** 其中经三方合并（本地与服务端都改过但互不重叠）后上传的章数。 */
    val merged: Int = 0,
    val conflicts: Int = 0,
    val failed: Int = 0,
    /** 失败是否值得稍后自动重试（断网 / 超时 / 章节被锁 / 5xx）。 */
    val retryable: Boolean = false,
    val message: String? = null,
) {
    val hasWork: Boolean get() = pushed + conflicts + failed > 0

    operator fun plus(other: SyncReport) = SyncReport(
        pushed = pushed + other.pushed,
        merged = merged + other.merged,
        conflicts = conflicts + other.conflicts,
        failed = failed + other.failed,
        retryable = retryable || other.retryable,
        message = other.message ?: message,
    )
}

// ---------------------------------------------------------------- 账本 / 摘要

data class ChapterDigest(
    val chapterId: String,
    val title: String,
    val synopsis: String,
    val speakers: List<String>,
    val openHook: String,
    val closeHook: String,
)

data class ChapterFacts(
    val chapterId: String,
    val title: String,
    val facts: List<String>,
    val keyQuotes: List<String>,
)

data class CharacterState(
    val chapterId: String,
    val chapterTitle: String,
    val characterName: String,
    val emotion: String,
    val body: String,
    val relations: String,
)

data class Foreshadow(
    val id: String,
    val hook: String,
    val plantedChapter: String,
    val status: String,
    val note: String,
    val paidInChapter: String?,
) {
    val isPaid: Boolean get() = status == "paid"
}

data class Ledger(
    val digests: List<ChapterDigest>,
    val chapterFacts: List<ChapterFacts>,
    val characterStates: List<CharacterState>,
    val foreshadows: List<Foreshadow>,
) {
    companion object {
        val EMPTY = Ledger(emptyList(), emptyList(), emptyList(), emptyList())
    }
}

// ---------------------------------------------------------------- Agent

data class AgentConversationSummary(
    val id: String,
    val title: String,
    val messageCount: Int,
    val updatedAt: String,
)

enum class AgentRole { USER, ASSISTANT }

data class AgentMessage(
    val role: AgentRole,
    val content: String,
)

data class AgentConversation(
    val id: String,
    val title: String,
    val messages: List<AgentMessage>,
    /** 上次运行是否中断（可「继续上次运行」）。 */
    val resumable: Boolean,
)

data class AgentRunRequest(
    val projectId: String,
    val conversationId: String?,
    val messages: List<AgentMessage>,
    val chapterId: String?,
    val selection: String?,
    val applyActions: Boolean = true,
    val resume: Boolean = false,
)

data class AgentRunResult(
    val message: String,
    val applied: Boolean,
    val warnings: List<String>,
    val conversationId: String?,
    val model: String?,
    val actionCount: Int,
)

/** 一步工具调用的展示信息（trace 与流式事件共用）。 */
data class AgentToolStep(val name: String, val summary: String)

sealed interface AgentEvent {
    data class Task(val text: String) : AgentEvent
    data class Thought(val text: String) : AgentEvent
    data class ToolCall(val step: AgentToolStep) : AgentEvent
    data class ToolResult(val step: AgentToolStep) : AgentEvent
    data class Actions(val count: Int) : AgentEvent
    data class Review(val text: String) : AgentEvent
    data class Final(val result: AgentRunResult) : AgentEvent
    data class Error(val message: String) : AgentEvent
}

// ---------------------------------------------------------------- 协作

data class Member(val userId: String, val username: String, val role: String)

data class ChapterLock(
    val chapterId: String,
    val userId: String,
    val username: String,
    val expiresAt: String,
)

data class Comment(
    val id: String,
    val chapterId: String,
    val anchor: String,
    val parentId: String?,
    val userId: String,
    val username: String,
    val text: String,
    val resolved: Boolean,
    val createdAt: String,
)

sealed interface CollabEvent {
    data class MemberChanged(val kind: String) : CollabEvent
    data class LockChanged(val kind: String, val chapterId: String?, val userId: String?) : CollabEvent
    data class CommentChanged(val kind: String, val chapterId: String?) : CollabEvent
    data object Other : CollabEvent
}

// ---------------------------------------------------------------- 设置 / 用量

/** 服务端账号级设置（密钥永远只回脱敏值）。 */
data class AccountSettings(
    val hasApiKey: Boolean,
    val apiKeyMasked: String,
    val apiBaseUrl: String,
    val apiModel: String,
    val activeModel: String,
    val activeBaseUrl: String,
    val credentialSource: String,
)

data class AccountSettingsUpdate(
    /** null = 不改；"" = 清除；其它 = 设置/轮换。 */
    val apiKey: String? = null,
    val apiBaseUrl: String? = null,
    val apiModel: String? = null,
)

data class UsageTotals(val promptTokens: Long, val completionTokens: Long, val totalTokens: Long, val calls: Long)

data class UsageOverview(val today: UsageTotals, val total: UsageTotals)

data class TestLlmResult(val ok: Boolean, val latencyMs: Long, val model: String?, val error: String?)

enum class ThemeMode { SYSTEM, LIGHT, DARK }

/** 仅存本机的设置（DataStore）。 */
data class LocalSettings(
    /** 空串 = 使用构建默认地址。 */
    val serverUrlOverride: String = "",
    val themeMode: ThemeMode = ThemeMode.SYSTEM,
    val fontScale: Float = 1.0f,
    val dailyGoalWords: Int = 0,
    val reminderEnabled: Boolean = false,
    val reminderHour: Int = 21,
    val reminderMinute: Int = 0,
    val lastProjectId: String? = null,
    /** 本地缓存属于哪个账号；换账号登录时据此清库，避免看到上一个人的项目。 */
    val lastUserId: String? = null,
    /** 是否启用「仅本机 Key」：启用后随请求带 X-LLM-* 头，不使用账号里存的 Key。 */
    val localLlmEnabled: Boolean = false,
    val localLlmBaseUrl: String = "",
    val localLlmModel: String = "",
    val secureWindow: Boolean = false,
    /** 最近一次在本机写作（保存草稿）的时间戳；只用于「今天已写过就不发提醒」，不要求精确。 */
    val lastWriteAt: Long = 0L,
)
