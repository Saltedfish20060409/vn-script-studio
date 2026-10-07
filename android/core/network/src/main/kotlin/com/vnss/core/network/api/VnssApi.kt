package com.vnss.core.network.api

import com.vnss.core.network.Timeouts
import com.vnss.core.network.dto.AgentConversationDto
import com.vnss.core.network.dto.AgentConversationSummaryDto
import com.vnss.core.network.dto.CommentCreateRequest
import com.vnss.core.network.dto.CommentDto
import com.vnss.core.network.dto.CommentUpdateRequest
import com.vnss.core.network.dto.CommentsEnvelope
import com.vnss.core.network.dto.CreateConversationRequest
import com.vnss.core.network.dto.CreateProjectRequest
import com.vnss.core.network.dto.IdentifierRequest
import com.vnss.core.network.dto.LensesCatalogDto
import com.vnss.core.network.dto.LocksEnvelope
import com.vnss.core.network.dto.LoginRequest
import com.vnss.core.network.dto.MembersEnvelope
import com.vnss.core.network.dto.OkMessageDto
import com.vnss.core.network.dto.ProjectLensesDto
import com.vnss.core.network.dto.ProjectLensesPutRequest
import com.vnss.core.network.dto.ProjectLensesPutResponse
import com.vnss.core.network.dto.ProjectPutRequest
import com.vnss.core.network.dto.ProjectSummaryDto
import com.vnss.core.network.dto.PutConversationRequest
import com.vnss.core.network.dto.RegisterRequest
import com.vnss.core.network.dto.RegisterResponse
import com.vnss.core.network.dto.SettingsDto
import com.vnss.core.network.dto.SettingsPutRequest
import com.vnss.core.network.dto.TestLlmRequest
import com.vnss.core.network.dto.TestLlmResponse
import com.vnss.core.network.dto.TokenDto
import com.vnss.core.network.dto.UsageDto
import com.vnss.core.network.dto.UserDto
import kotlinx.serialization.json.JsonObject
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.Headers
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * 业务 API（需要登录态）。路径相对于 `/api/v1/`。
 *
 * 每个方法的超时档位通过 `@Headers` 声明，由 [com.vnss.core.network.interceptor.TimeoutInterceptor] 应用。
 * 不带 `@Headers` 的方法吃默认的 [Timeouts.FAST_MS]。
 */
interface VnssApi {

    // ---------------------------------------------------------------- auth
    @GET("auth/me")
    @Headers("${Timeouts.HEADER}: ${Timeouts.AUTH_MS}")
    suspend fun me(): UserDto

    // ---------------------------------------------------------------- projects
    @GET("projects")
    suspend fun listProjects(): List<ProjectSummaryDto>

    @POST("projects")
    suspend fun createProject(@Body body: CreateProjectRequest): JsonObject

    @GET("projects/{id}")
    suspend fun getProject(@Path("id") id: String): JsonObject

    @PUT("projects/{id}")
    @Headers("${Timeouts.HEADER}: ${Timeouts.UPLOAD_MS}")
    suspend fun putProject(@Path("id") id: String, @Body body: ProjectPutRequest): JsonObject

    // ---------------------------------------------------------------- agent
    @GET("projects/{id}/agent/conversations")
    suspend fun listConversations(@Path("id") id: String): List<AgentConversationSummaryDto>

    @POST("projects/{id}/agent/conversations")
    suspend fun createConversation(
        @Path("id") id: String,
        @Body body: CreateConversationRequest,
    ): AgentConversationDto

    @GET("projects/{id}/agent/conversations/{cid}")
    suspend fun getConversation(@Path("id") id: String, @Path("cid") cid: String): AgentConversationDto

    @PUT("projects/{id}/agent/conversations/{cid}")
    suspend fun putConversation(
        @Path("id") id: String,
        @Path("cid") cid: String,
        @Body body: PutConversationRequest,
    ): AgentConversationDto

    // ---------------------------------------------------------------- lenses（作家眼光）
    @GET("lenses")
    suspend fun listLenses(): LensesCatalogDto

    @GET("projects/{id}/lenses")
    suspend fun getProjectLenses(@Path("id") id: String): ProjectLensesDto

    @PUT("projects/{id}/lenses")
    suspend fun putProjectLenses(
        @Path("id") id: String,
        @Body body: ProjectLensesPutRequest,
    ): ProjectLensesPutResponse

    // ---------------------------------------------------------------- collab
    @GET("projects/{id}/members")
    suspend fun members(@Path("id") id: String): MembersEnvelope

    @GET("projects/{id}/locks")
    suspend fun locks(@Path("id") id: String): LocksEnvelope

    @GET("projects/{id}/comments")
    suspend fun comments(
        @Path("id") id: String,
        @Query("chapter_id") chapterId: String? = null,
    ): CommentsEnvelope

    @POST("projects/{id}/comments")
    suspend fun addComment(@Path("id") id: String, @Body body: CommentCreateRequest): CommentDto

    @PATCH("projects/{id}/comments/{commentId}")
    suspend fun updateComment(
        @Path("id") id: String,
        @Path("commentId") commentId: String,
        @Body body: CommentUpdateRequest,
    ): CommentDto

    @DELETE("projects/{id}/comments/{commentId}")
    suspend fun deleteComment(@Path("id") id: String, @Path("commentId") commentId: String): OkMessageDto

    // ---------------------------------------------------------------- settings / usage
    @GET("settings")
    suspend fun getSettings(): SettingsDto

    @PUT("settings")
    suspend fun putSettings(@Body body: SettingsPutRequest): SettingsDto

    @POST("settings/test-llm")
    @Headers("${Timeouts.HEADER}: ${Timeouts.PROBE_MS}")
    suspend fun testLlm(@Body body: TestLlmRequest): TestLlmResponse

    @GET("usage")
    suspend fun usage(): UsageDto
}

/** 无需登录态的认证端点（注册 / 登录 / 找回）。走独立 Retrofit，不带 Authenticator。 */
interface AuthApi {
    /**
     * 返回 [retrofit2.Response]：除 JSON 外还要读 `Set-Cookie: vnss_refresh`，
     * 兼容尚未把 refresh_token 放进响应体的服务端。
     */
    @POST("auth/login")
    @Headers("${Timeouts.HEADER}: ${Timeouts.AUTH_MS}")
    suspend fun login(@Body body: LoginRequest): retrofit2.Response<TokenDto>

    @POST("auth/register")
    @Headers("${Timeouts.HEADER}: ${Timeouts.UPLOAD_MS}")
    suspend fun register(@Body body: RegisterRequest): RegisterResponse

    @POST("auth/resend-verification")
    @Headers("${Timeouts.HEADER}: ${Timeouts.UPLOAD_MS}")
    suspend fun resendVerification(@Body body: IdentifierRequest): OkMessageDto

    @POST("auth/forgot-password")
    @Headers("${Timeouts.HEADER}: ${Timeouts.UPLOAD_MS}")
    suspend fun forgotPassword(@Body body: IdentifierRequest): OkMessageDto
}
