package com.vnss.core.data.json

import com.vnss.core.common.WordCount
import com.vnss.core.database.ChapterEntity
import com.vnss.core.database.ProjectEntity
import com.vnss.core.database.SyncStates
import com.vnss.core.model.Chapter
import com.vnss.core.model.ChapterDigest
import com.vnss.core.model.ChapterFacts
import com.vnss.core.model.CharacterState
import com.vnss.core.model.Foreshadow
import com.vnss.core.model.Ledger
import com.vnss.core.model.Project
import com.vnss.core.model.SyncState
import com.vnss.core.model.Volume
import com.vnss.core.network.VnssJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.put

/** 项目 JSON ↔ Room / 领域模型。移动端不认识的字段原样待在 rawJson / 顶层对象里。 */
object ProjectJson {

    fun parse(root: JsonObject): ParsedProject {
        val id = root.str("id") ?: error("项目 JSON 缺少 id")
        val title = root.strOrEmpty("title")
        val logline = root.str("logline")
        val genre = root.str("genre")
        val updatedAt = root.str("updatedAt") ?: root.str("updated_at")
        val chapters = root.arr("chapters")?.objects().orEmpty()
        val volumes = root.arr("volumes")?.objects().orEmpty().mapNotNull { v ->
            val vid = v.str("id") ?: return@mapNotNull null
            Volume(vid, v.strOrEmpty("title").ifBlank { "未命名卷" })
        }
        return ParsedProject(
            id = id,
            title = title.ifBlank { "未命名作品" },
            logline = logline,
            genre = genre,
            updatedAt = updatedAt,
            volumes = volumes,
            chapters = chapters,
            ledgerJson = root.obj("writingLedger")?.toString(),
            chapterIndexJson = root.arr("chapterIndex")?.toString(),
            volumesJson = root.arr("volumes")?.toString(),
        )
    }

    fun parseOrNull(raw: String): JsonObject? =
        runCatching { VnssJson.parseToJsonElement(raw).jsonObject }.getOrNull()

    fun parseArray(raw: String?): List<JsonObject> {
        if (raw.isNullOrBlank()) return emptyList()
        return runCatching { (VnssJson.parseToJsonElement(raw) as? JsonArray)?.objects().orEmpty() }.getOrDefault(emptyList())
    }

    fun projectEntity(
        parsed: ParsedProject,
        listOrder: Int,
        listUpdatedAt: String? = parsed.updatedAt,
        now: Long = System.currentTimeMillis(),
    ) = ProjectEntity(
        id = parsed.id,
        title = parsed.title,
        logline = parsed.logline,
        genre = parsed.genre,
        serverUpdatedAt = parsed.updatedAt,
        listUpdatedAt = listUpdatedAt,
        chaptersCount = parsed.chapters.size,
        listOrder = listOrder,
        detailLoaded = true,
        volumesJson = parsed.volumesJson,
        ledgerJson = parsed.ledgerJson,
        chapterIndexJson = parsed.chapterIndexJson,
        lastRefreshedAt = now,
    )

    fun listEntity(
        id: String,
        title: String,
        logline: String?,
        genre: String?,
        updatedAt: String?,
        chaptersCount: Int,
        listOrder: Int,
        existing: ProjectEntity?,
    ) = ProjectEntity(
        id = id,
        title = title.ifBlank { existing?.title ?: "未命名作品" },
        logline = logline ?: existing?.logline,
        genre = genre ?: existing?.genre,
        serverUpdatedAt = existing?.serverUpdatedAt,
        listUpdatedAt = updatedAt ?: existing?.listUpdatedAt,
        chaptersCount = chaptersCount,
        listOrder = listOrder,
        detailLoaded = existing?.detailLoaded ?: false,
        volumesJson = existing?.volumesJson,
        ledgerJson = existing?.ledgerJson,
        chapterIndexJson = existing?.chapterIndexJson,
        lastRefreshedAt = existing?.lastRefreshedAt ?: 0L,
    )

    fun chapterFromServer(projectId: String, orderIndex: Int, ch: JsonObject, now: Long): ChapterEntity {
        val id = ch.str("id") ?: error("章节缺少 id")
        val title = ch.strOrEmpty("title")
        val prose = ch.strOrEmpty("prose")
        val blocks = ch.arr("blocks")
        val scriptOnly = prose.isBlank() && !blocks.isNullOrEmpty()
        return ChapterEntity(
            id = id,
            projectId = projectId,
            orderIndex = orderIndex,
            title = title,
            synopsis = ch.str("synopsis"),
            volumeId = ch.str("volumeId"),
            prose = prose,
            words = WordCount.count(prose),
            published = !ch.str("publishedAt").isNullOrBlank(),
            scriptOnly = scriptOnly,
            rawJson = stripProse(ch).toString(),
            baseProse = prose,
            baseTitle = title,
            syncState = SyncStates.SYNCED,
            isNew = false,
            syncError = null,
            remoteProse = null,
            remoteTitle = null,
            localUpdatedAt = now,
        )
    }

    fun newLocalChapter(
        id: String,
        projectId: String,
        title: String,
        orderIndex: Int,
        now: Long,
    ): ChapterEntity {
        val raw = buildJsonObject {
            put("id", id)
            put("title", title)
            put("blocks", buildJsonArray { })
        }
        return ChapterEntity(
            id = id,
            projectId = projectId,
            orderIndex = orderIndex,
            title = title,
            synopsis = null,
            volumeId = null,
            prose = "",
            words = 0,
            published = false,
            scriptOnly = false,
            rawJson = raw.toString(),
            baseProse = "",
            baseTitle = title,
            syncState = SyncStates.DIRTY,
            isNew = true,
            syncError = null,
            remoteProse = null,
            remoteTitle = null,
            localUpdatedAt = now,
        )
    }

    /** 上传用：在该章原始 JSON 上覆盖 title/prose，其它字段原样。 */
    fun overlayForUpload(entity: ChapterEntity): JsonObject {
        val raw = parseOrNull(entity.rawJson) ?: buildJsonObject { put("id", entity.id) }
        return buildJsonObject {
            for ((k, v) in raw) {
                if (k != "title" && k != "prose") put(k, v)
            }
            put("id", entity.id)
            put("title", entity.title)
            put("prose", entity.prose)
        }
    }

    fun stripProse(ch: JsonObject): JsonObject = ch.without("prose")

    fun replaceChapters(root: JsonObject, byId: Map<String, JsonObject>): JsonObject {
        val existing = root.arr("chapters")?.objects().orEmpty()
        val used = HashSet<String>()
        val next = ArrayList<JsonObject>(existing.size + byId.size)
        for (ch in existing) {
            val id = ch.str("id") ?: continue
            val replacement = byId[id]
            next += replacement ?: ch
            used += id
        }
        for ((id, ch) in byId) {
            if (id !in used) next += ch
        }
        return root.mutate {
            put("chapters", JsonArray(next))
        }
    }

    fun toDomain(entity: ProjectEntity): Project {
        val volumes = parseArray(entity.volumesJson).mapNotNull { v ->
            val id = v.str("id") ?: return@mapNotNull null
            Volume(id, v.strOrEmpty("title").ifBlank { "未命名卷" })
        }
        return Project(
            id = entity.id,
            title = entity.title,
            logline = entity.logline,
            genre = entity.genre,
            updatedAt = entity.listUpdatedAt ?: entity.serverUpdatedAt,
            volumes = volumes,
        )
    }

    fun toDomain(entity: ChapterEntity) = Chapter(
        id = entity.id,
        projectId = entity.projectId,
        title = entity.title,
        synopsis = entity.synopsis,
        prose = entity.prose,
        volumeId = entity.volumeId,
        syncState = syncState(entity.syncState),
        syncError = entity.syncError,
        scriptOnly = entity.scriptOnly,
    )

    fun syncState(raw: String): SyncState = when (raw) {
        SyncStates.DIRTY -> SyncState.DIRTY
        SyncStates.CONFLICT -> SyncState.CONFLICT
        else -> SyncState.SYNCED
    }

    fun parseLedger(ledgerJson: String?, indexJson: String?, chapterTitles: Map<String, String>): Ledger {
        val ledger = ledgerJson?.let { parseOrNull(it) }
        val index = indexJson?.let { runCatching { VnssJson.parseToJsonElement(it) }.getOrNull() as? JsonArray }
        val digests = index?.objects().orEmpty().mapNotNull { e ->
            val id = e.str("chapterId") ?: return@mapNotNull null
            ChapterDigest(
                chapterId = id,
                title = e.strOrEmpty("title").ifBlank { chapterTitles[id].orEmpty() },
                synopsis = e.strOrEmpty("synopsis"),
                speakers = jsonStringList(e["speakers"]),
                openHook = e.strOrEmpty("openHook"),
                closeHook = e.strOrEmpty("closeHook"),
            )
        }
        val facts = ledger?.arr("chapterFacts")?.objects().orEmpty().mapNotNull { f ->
            val id = f.str("chapterId") ?: return@mapNotNull null
            ChapterFacts(
                chapterId = id,
                title = f.strOrEmpty("title").ifBlank { chapterTitles[id].orEmpty() },
                facts = jsonStringList(f["facts"]),
                keyQuotes = jsonStringList(f["keyQuotes"]),
            )
        }
        val states = ledger?.arr("characterStates")?.objects().orEmpty().map { s ->
            CharacterState(
                chapterId = s.strOrEmpty("chapterId"),
                chapterTitle = s.strOrEmpty("chapterTitle").ifBlank { chapterTitles[s.strOrEmpty("chapterId")].orEmpty() },
                characterName = s.strOrEmpty("characterName"),
                emotion = s.strOrEmpty("emotion"),
                body = s.strOrEmpty("body"),
                relations = s.strOrEmpty("relations"),
            )
        }
        val foreshadows = ledger?.arr("foreshadows")?.objects().orEmpty().mapIndexed { i, f ->
            Foreshadow(
                id = f.str("id") ?: "fs-$i",
                hook = f.strOrEmpty("hook"),
                plantedChapter = f.strOrEmpty("plantedChapter"),
                status = f.strOrEmpty("status").ifBlank { "open" },
                note = f.strOrEmpty("note"),
                paidInChapter = f.str("paidInChapter"),
            )
        }
        return Ledger(digests, facts, states, foreshadows)
    }

    data class ParsedProject(
        val id: String,
        val title: String,
        val logline: String?,
        val genre: String?,
        val updatedAt: String?,
        val volumes: List<Volume>,
        val chapters: List<JsonObject>,
        val ledgerJson: String?,
        val chapterIndexJson: String?,
        val volumesJson: String?,
    )
}


