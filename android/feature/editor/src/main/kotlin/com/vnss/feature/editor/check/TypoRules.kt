package com.vnss.feature.editor.check

/**
 * 常见别字 / 别词词表——`frontend/src/lib/typoRules.ts` 的逐条移植。
 *
 * 收录标准（沿用 Web 端，三条同时满足才收）：错写形式不另作词存在、正确形式唯一公认、
 * 错写形式不是专名。所以命中即报、零误报。**不要在这里单方面加词**：先改 `typoRules.ts`，
 * 再重新生成 `shared/test-fixtures/writing_local_cases.json`，夹具测试会逼两端保持一致。
 */
enum class TypoKind(val label: String) {
    IDIOM("成语"),
    FIXED("固定搭配"),
}

data class TypoRule(val wrong: String, val right: String, val kind: TypoKind)

data class TypoHit(
    val offset: Int,
    val length: Int,
    val wrong: String,
    val right: String,
    val kind: TypoKind,
)

object TypoRules {

    private val IDIOMS: List<Pair<String, String>> = listOf(
        "迫不急待" to "迫不及待",
        "一如继往" to "一如既往",
        "按耐不住" to "按捺不住",
        "不径而走" to "不胫而走",
        "草管人命" to "草菅人命",
        "重蹈复辙" to "重蹈覆辙",
        "穿流不息" to "川流不息",
        "打报不平" to "打抱不平",
        "甘败下风" to "甘拜下风",
        "各行其事" to "各行其是",
        "鬼计多端" to "诡计多端",
        "汗流夹背" to "汗流浃背",
        "好高鹜远" to "好高骛远",
        "既往不究" to "既往不咎",
        "娇揉造作" to "矫揉造作",
        "竭泽而鱼" to "竭泽而渔",
        "金榜提名" to "金榜题名",
        "举一返三" to "举一反三",
        "开源截流" to "开源节流",
        "空前决后" to "空前绝后",
        "脍灸人口" to "脍炙人口",
        "滥芋充数" to "滥竽充数",
        "礼上往来" to "礼尚往来",
        "名列前矛" to "名列前茅",
        "明辩是非" to "明辨是非",
        "默守成规" to "墨守成规",
        "弄巧成绌" to "弄巧成拙",
        "旁证博引" to "旁征博引",
        "披星带月" to "披星戴月",
        "迫在眉捷" to "迫在眉睫",
        "千锤百练" to "千锤百炼",
        "前扑后继" to "前仆后继",
        "情不自尽" to "情不自禁",
        "如法泡制" to "如法炮制",
        "如火如茶" to "如火如荼",
        "世外桃园" to "世外桃源",
        "首曲一指" to "首屈一指",
        "谈笑风声" to "谈笑风生",
        "提心掉胆" to "提心吊胆",
        "天翻地复" to "天翻地覆",
        "枉废心机" to "枉费心机",
        "委屈求全" to "委曲求全",
        "无微不致" to "无微不至",
        "心浮气燥" to "心浮气躁",
        "兴高彩烈" to "兴高采烈",
        "悬梁刺骨" to "悬梁刺股",
        "一愁莫展" to "一筹莫展",
        "一诺千斤" to "一诺千金",
        "义气用事" to "意气用事",
        "应接不遐" to "应接不暇",
        "永保青春" to "永葆青春",
        "有持无恐" to "有恃无恐",
        "再所不惜" to "在所不惜",
        "再接再励" to "再接再厉",
        "责无旁代" to "责无旁贷",
        "坐阵指挥" to "坐镇指挥",
        "走头无路" to "走投无路",
        "专心至志" to "专心致志",
        "莫明其妙" to "莫名其妙",
        "不知所错" to "不知所措",
    )

    private val FIXED: List<Pair<String, String>> = listOf(
        "部份" to "部分",
        "松驰" to "松弛",
        "气慨" to "气概",
        "幅射" to "辐射",
        "报歉" to "抱歉",
        "布署" to "部署",
        "罗嗦" to "啰嗦",
        "家俱" to "家具",
        "亲睐" to "青睐",
        "竞然" to "竟然",
        "峻工" to "竣工",
        "渡假" to "度假",
        "精采" to "精彩",
        "装璜" to "装潢",
        "蓝球" to "篮球",
        "决对" to "绝对",
        "沉缅" to "沉湎",
        "好象" to "好像",
        "既使" to "即使",
        "竟争" to "竞争",
        "凋弊" to "凋敝",
        "梦餍" to "梦魇",
    )

    val RULES: List<TypoRule> =
        IDIOMS.map { (w, r) -> TypoRule(w, r, TypoKind.IDIOM) } +
            FIXED.map { (w, r) -> TypoRule(w, r, TypoKind.FIXED) }

    /** 扫一遍文本，返回所有命中（按位置、长度排序）。命中即报，不做任何「智能」判断。 */
    fun findTypos(text: String): List<TypoHit> {
        if (text.isEmpty()) return emptyList()
        val hits = ArrayList<TypoHit>()
        for (rule in RULES) {
            var at = text.indexOf(rule.wrong)
            while (at >= 0) {
                hits += TypoHit(at, rule.wrong.length, rule.wrong, rule.right, rule.kind)
                at = text.indexOf(rule.wrong, at + rule.wrong.length)
            }
        }
        return hits.sortedWith(compareBy<TypoHit> { it.offset }.thenBy { it.length })
    }

    fun message(hit: TypoHit): String =
        "疑是别字：「${hit.wrong}」通常写作「${hit.right}」（${hit.kind.label}）"
}
