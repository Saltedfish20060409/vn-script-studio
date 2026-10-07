package com.vnss.core.data.json

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

internal fun JsonObject.str(key: String): String? =
    (this[key] as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotEmpty() }

internal fun JsonObject.strOrEmpty(key: String): String = str(key).orEmpty()

internal fun JsonObject.int(key: String): Int? = (this[key] as? JsonPrimitive)?.contentOrNull?.toIntOrNull()

internal fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull

internal fun JsonObject.obj(key: String): JsonObject? = this[key] as? JsonObject

internal fun JsonObject.arr(key: String): JsonArray? = this[key] as? JsonArray

internal fun JsonElement.asObjectOrNull(): JsonObject? = this as? JsonObject

internal fun JsonObject.mutate(block: MutableMap<String, JsonElement>.() -> Unit): JsonObject {
    val map = toMutableMap()
    map.block()
    return JsonObject(map)
}

internal fun JsonObject.without(vararg keys: String): JsonObject {
    val drop = keys.toSet()
    return buildJsonObject {
        for ((k, v) in this@without) {
            if (k !in drop) put(k, v)
        }
    }
}

internal fun JsonPrimitive?.text(): String = this?.contentOrNull.orEmpty()

internal fun JsonArray.objects(): List<JsonObject> = mapNotNull { it as? JsonObject }

internal fun JsonObject.putAllKeep(from: JsonObject, skip: Set<String> = emptySet()): JsonObject =
    buildJsonObject {
        for ((k, v) in this@putAllKeep) put(k, v)
        for ((k, v) in from) if (k !in skip) put(k, v)
    }

internal fun jsonStringList(el: JsonElement?): List<String> {
    val arr = el as? JsonArray ?: return emptyList()
    return arr.mapNotNull { (it as? JsonPrimitive)?.contentOrNull?.takeIf { s -> s.isNotBlank() } }
}