package com.vnss.core.network

import com.vnss.core.network.api.AuthApi
import com.vnss.core.network.api.RefreshApi
import com.vnss.core.network.api.VnssApi
import com.vnss.core.network.dto.AgentConversationDto
import com.vnss.core.network.dto.AgentConversationSummaryDto
import com.vnss.core.network.dto.AgentRunRequestDto
import com.vnss.core.network.dto.CommentCreateRequest
import com.vnss.core.network.dto.CommentUpdateRequest
import com.vnss.core.network.dto.CreateConversationRequest
import com.vnss.core.network.dto.CreateProjectRequest
import com.vnss.core.network.dto.IdentifierRequest
import com.vnss.core.network.dto.LoginRequest
import com.vnss.core.network.dto.OkMessageDto
import com.vnss.core.network.dto.ProjectLensesPutRequest
import com.vnss.core.network.dto.ProjectPutRequest
import com.vnss.core.network.dto.ProjectSummaryDto
import com.vnss.core.network.dto.PutConversationRequest
import com.vnss.core.network.dto.RefreshRequest
import com.vnss.core.network.dto.RegisterRequest
import com.vnss.core.network.dto.RegisterResponse
import com.vnss.core.network.dto.SettingsDto
import com.vnss.core.network.dto.SettingsPutRequest
import com.vnss.core.network.dto.TestLlmRequest
import com.vnss.core.network.dto.TokenDto
import com.vnss.core.network.dto.UserDto
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.PUT

/**
 * Android 契约测试：Retrofit 接口声明、流式端点、DTO 字段 ↔ `shared/test-fixtures/android_api_contract.json`。
 *
 * 同一份夹具由后端 `backend/tests/test_android_contract.py` 对照 OpenAPI 校验——
 * 后端改接口 → 后端测试红；Android 改调用 → 这里红。两边必须一起改，这是唯一目的。
 */
class ApiContractTest {

    private val contract: JsonObject by lazy {
        val stream = checkNotNull(javaClass.classLoader?.getResourceAsStream("android_api_contract.json")) {
            "找不到 android_api_contract.json（检查 build.gradle.kts 里的 test resources srcDir）"
        }
        VnssJson.parseToJsonElement(stream.bufferedReader(Charsets.UTF_8).readText()).jsonObject
    }

    private fun normalize(path: String): String = path.replace(Regex("\\{[^}]*}"), "{}")

    private fun String.withPrefix(): String = "/api/v1/" + trimStart('/')

    private fun fixtureOps(key: String): Set<String> =
        (contract[key] as JsonArray).map {
            val o = it.jsonObject
            "${o["method"]!!.jsonPrimitive.content.lowercase()} ${normalize(o["path"]!!.jsonPrimitive.content)}"
        }.toSet()

    /** 反射读 Retrofit 注解，得到 "method /api/v1/path" 集合。 */
    private fun retrofitOps(vararg apis: Class<*>): Set<String> {
        val ops = mutableSetOf<String>()
        for (api in apis) {
            for (m in api.declaredMethods) {
                m.getAnnotation(GET::class.java)?.let { ops += "get ${normalize(it.value.withPrefix())}" }
                m.getAnnotation(POST::class.java)?.let { ops += "post ${normalize(it.value.withPrefix())}" }
                m.getAnnotation(PUT::class.java)?.let { ops += "put ${normalize(it.value.withPrefix())}" }
                m.getAnnotation(PATCH::class.java)?.let { ops += "patch ${normalize(it.value.withPrefix())}" }
                m.getAnnotation(DELETE::class.java)?.let { ops += "delete ${normalize(it.value.withPrefix())}" }
            }
        }
        return ops
    }

    @Test
    fun retrofitInterfacesMatchContractOperations() {
        val declared = retrofitOps(VnssApi::class.java, AuthApi::class.java, RefreshApi::class.java)
        val expected = fixtureOps("operations")
        assertEquals(
            "Retrofit 声明了契约里没有的接口（先把它加进 android_api_contract.json 并让后端测试通过）",
            emptySet<String>(),
            declared - expected,
        )
        assertEquals(
            "契约里有、但 Retrofit 没声明的接口（删掉契约条目，或补上声明）",
            emptySet<String>(),
            expected - declared,
        )
    }

    @Test
    fun streamEndpointsMatchContract() {
        val origin = "https://placeholder.invalid"
        // 用占位 id 生成真实 URL，再把 id 段还原成 {}，与契约的写法对齐
        fun toPath(url: String) = url.removePrefix(origin).replace("/PID/", "/{}/")
        val declared = setOf(
            "post " + toPath(ApiEndpoints.agentStream("PID")),
            "get " + toPath(ApiEndpoints.projectEvents("PID")),
        )
        assertEquals(fixtureOps("streams"), declared)
    }

    // ---------------------------------------------------------------- schema

    private fun schemaFields(name: String): Set<String> =
        (contract["schemas"]!!.jsonObject[name] as JsonArray).map { it.jsonPrimitive.content }.toSet()

    private fun fieldsOf(s: KSerializer<*>): List<String> =
        (0 until s.descriptor.elementsCount).map { s.descriptor.getElementName(it) }

    private fun requiredOf(s: KSerializer<*>): List<String> =
        (0 until s.descriptor.elementsCount).filterNot { s.descriptor.isElementOptional(it) }.map { s.descriptor.getElementName(it) }

    /** 我们发出去的请求：每个字段名都必须是后端 schema 认识的（拼错 / 后端改名会在这里红）。 */
    private fun assertRequest(schema: String, s: KSerializer<*>) {
        val unknown = fieldsOf(s).toSet() - schemaFields(schema)
        assertTrue("$schema：客户端发送了后端不认识的字段 $unknown", unknown.isEmpty())
    }

    /** 我们读的响应：必填字段必须真的在后端 schema 里（可选字段缺失不致命）。 */
    private fun assertResponse(schema: String, s: KSerializer<*>) {
        val missing = requiredOf(s).toSet() - schemaFields(schema)
        assertTrue("$schema：客户端要求但后端没有的字段 $missing", missing.isEmpty())
    }

    @Test
    fun requestDtosOnlyUseKnownFields() {
        assertRequest("LoginIn", LoginRequest.serializer())
        assertRequest("RegisterIn", RegisterRequest.serializer())
        assertRequest("RefreshIn", RefreshRequest.serializer())
        assertRequest("ForgotPasswordIn", IdentifierRequest.serializer())
        assertRequest("ResendVerifyIn", IdentifierRequest.serializer())
        assertRequest("ProjectCreateIn", CreateProjectRequest.serializer())
        assertRequest("ProjectPutIn", ProjectPutRequest.serializer())
        assertRequest("AgentRunIn", AgentRunRequestDto.serializer())
        assertRequest("AgentConversationCreateIn", CreateConversationRequest.serializer())
        assertRequest("AgentConversationPutIn", PutConversationRequest.serializer())
        assertRequest("LensesPutIn", ProjectLensesPutRequest.serializer())
        assertRequest("CommentIn", CommentCreateRequest.serializer())
        assertRequest("CommentUpdateIn", CommentUpdateRequest.serializer())
        assertRequest("SettingsPutIn", SettingsPutRequest.serializer())
        assertRequest("TestLlmIn", TestLlmRequest.serializer())
    }

    @Test
    fun responseDtosOnlyRequireKnownFields() {
        assertResponse("TokenOut", TokenDto.serializer())
        assertResponse("UserOut", UserDto.serializer())
        assertResponse("ProjectSummary", ProjectSummaryDto.serializer())
        assertResponse("RegisterOut", RegisterResponse.serializer())
        assertResponse("OkMessageOut", OkMessageDto.serializer())
        assertResponse("AgentConversationSummary", AgentConversationSummaryDto.serializer())
        assertResponse("AgentConversationOut", AgentConversationDto.serializer())
        assertResponse("SettingsOut", SettingsDto.serializer())
    }

    @Test
    fun contractFileIsWellFormed() {
        assertTrue(fixtureOps("operations").isNotEmpty())
        assertTrue(contract["schemas"]!!.jsonObject.values.all { it.jsonArray.isNotEmpty() })
    }
}
