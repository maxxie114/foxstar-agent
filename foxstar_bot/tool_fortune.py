from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class FortuneResult:
    mode: str
    title: str
    content: str
    sign: str = ""


CONSTELLATION_RANGES = [
    ("白羊", 3, 21, 4, 19),
    ("金牛", 4, 20, 5, 20),
    ("双子", 5, 21, 6, 21),
    ("巨蟹", 6, 22, 7, 22),
    ("狮子", 7, 23, 8, 22),
    ("处女", 8, 23, 9, 22),
    ("天秤", 9, 23, 10, 23),
    ("天蝎", 10, 24, 11, 22),
    ("射手", 11, 23, 12, 21),
    ("摩羯", 12, 22, 1, 19),
    ("水瓶", 1, 20, 2, 18),
    ("双鱼", 2, 19, 3, 20),
]

CONSTELLATION_ALIASES = {
    "白羊": "白羊",
    "白羊座": "白羊",
    "aries": "白羊",
    "金牛": "金牛",
    "金牛座": "金牛",
    "taurus": "金牛",
    "双子": "双子",
    "双子座": "双子",
    "gemini": "双子",
    "巨蟹": "巨蟹",
    "巨蟹座": "巨蟹",
    "cancer": "巨蟹",
    "狮子": "狮子",
    "狮子座": "狮子",
    "leo": "狮子",
    "处女": "处女",
    "处女座": "处女",
    "virgo": "处女",
    "天秤": "天秤",
    "天秤座": "天秤",
    "libra": "天秤",
    "天蝎": "天蝎",
    "天蝎座": "天蝎",
    "scorpio": "天蝎",
    "射手": "射手",
    "射手座": "射手",
    "sagittarius": "射手",
    "摩羯": "摩羯",
    "摩羯座": "摩羯",
    "capricorn": "摩羯",
    "水瓶": "水瓶",
    "水瓶座": "水瓶",
    "aquarius": "水瓶",
    "双鱼": "双鱼",
    "双鱼座": "双鱼",
    "pisces": "双鱼",
}

SIGN_PROFILES = {
    "白羊": {
        "tone": "直接、冲劲足、先手意识强",
        "focus": "推进、破局、抢节奏",
        "love": [
            "今天感情要靠主动，别等对方读心，你先开口反而更顺。",
            "有好感就别绕弯，真诚直给比试探更有效。",
            "情绪来得快去得也快，先把火气收一收，再聊会更甜。 ",
        ],
        "work": [
            "事业适合先手开题，卡住的事今天更适合硬推一把。",
            "你今天适合扛第一棒，但别把所有事都往自己身上拽。",
            "推进速度很快，记得给别人留一点跟上的空间。",
        ],
        "money": [
            "财运更适合快决策的小机会，但别为了爽感乱加码。",
            "资源流动感比较强，先抓确定性，再谈扩张。",
            "今天适合小范围试错，不适合把筹码一下子铺太开。",
        ],
        "colors": ["正红", "橙色", "亮白"],
        "numbers": [1, 7, 9],
    },
    "金牛": {
        "tone": "稳、耐心、讲质感",
        "focus": "打基础、收拢、优化",
        "love": [
            "感情这块今天要靠稳定输出，少闹别扭，多给确定感。",
            "慢一点反而更有吸引力，耐心回应比花哨动作更加分。",
            "别把在意憋成沉默，适当表达会让关系更稳。",
        ],
        "work": [
            "事业适合做整理、修细节、补漏洞，稳扎稳打最出效果。",
            "今天不一定适合冲得最快，但很适合把盘子做扎实。",
            "把节奏放稳，你会比别人更不容易出错。",
        ],
        "money": [
            "财运偏稳，适合把手上的资源分配得更有条理。",
            "今天更适合保守优化，而不是突然改大方向。",
            "有收获的前提是先守住节奏，别让外部噪音带偏你。",
        ],
        "colors": ["焦糖", "米白", "森林绿"],
        "numbers": [2, 5, 8],
    },
    "双子": {
        "tone": "灵活、机灵、信息流强",
        "focus": "沟通、社交、试新东西",
        "love": [
            "感情今天适合多互动，话聊开了，氛围自然会起来。",
            "你今天有一点嘴甜运，适合把想法直接说出来。",
            "别怕显得太主动，轻松一点反而更招人喜欢。",
        ],
        "work": [
            "事业上适合跑沟通线、试新方法、把堵点撬开。",
            "你今天靠信息差和反应速度吃饭，动作越灵越有优势。",
            "适合拉人、对表、推进协作，别一个人闷头做。",
        ],
        "money": [
            "财运和信息触角相关，多听多看容易找到更顺手的路。",
            "今天适合用脑子换效率，不适合硬碰硬。",
            "有些收获是从聊天和观察里来的，别把自己关太死。",
        ],
        "colors": ["白色", "浅蓝", "柠檬黄"],
        "numbers": [3, 6, 7],
    },
    "巨蟹": {
        "tone": "细腻、护短、情绪感知强",
        "focus": "关系、照顾、内部协调",
        "love": [
            "感情今天更看温度，耐心听对方说完比急着给答案更重要。",
            "你今天特别适合做暖场的人，柔软一点反而更有力量。",
            "情绪容易被放大，先稳住自己再谈关系会更顺。",
        ],
        "work": [
            "事业上适合做协同和收口，把人和事摆平就是贡献。",
            "你今天在团队里像缓冲垫，适合处理微妙的人际缝隙。",
            "先照顾好流程和节奏，后面自然顺下来。",
        ],
        "money": [
            "财运走保守线更舒服，先把节奏握稳，别被外界带着跑。",
            "今天适合做盘点和归整，不适合心急上头。",
            "你更容易从熟悉的关系和熟悉的节奏里得到支持。",
        ],
        "colors": ["淡紫", "银灰", "奶白"],
        "numbers": [3, 4, 8],
    },
    "狮子": {
        "tone": "存在感强、要面子、带头气场足",
        "focus": "表现、带队、定主轴",
        "love": [
            "感情上今天适合大大方方表达，别故作冷淡。",
            "你越坦率，越能让关系升温；硬撑体面反而容易错过。",
            "适合制造一点小仪式感，氛围会很好。",
        ],
        "work": [
            "事业适合站出来定调，别人会更愿意跟着你走。",
            "你今天适合做主心骨，但别因为好胜忽略细节。",
            "能见度很高，适合交付、展示、对外表达。",
        ],
        "money": [
            "财运更看你能不能把资源聚到关键点上。",
            "今天适合把牌面做漂亮，但别为了面子做多余动作。",
            "先把核心目标定住，资源才不容易散掉。",
        ],
        "colors": ["金色", "琥珀", "暖橙"],
        "numbers": [1, 5, 9],
    },
    "处女": {
        "tone": "细、准、讲逻辑",
        "focus": "修正、复盘、优化",
        "love": [
            "感情里别把关心全做成挑错，语气软一点效果翻倍。",
            "你今天适合做具体的小照顾，比空话更有用。",
            "别因为怕出错就不表达，真诚比完美更重要。",
        ],
        "work": [
            "事业非常适合查漏补缺、校准标准、整理细节。",
            "你今天的优势是精度，不是速度。",
            "适合做验收、复盘、梳流程，越细越能出价值。",
        ],
        "money": [
            "财运更像从优化和节省里来，先把结构理顺最重要。",
            "今天适合做归类和梳理，别让琐碎拖慢你。",
            "保持克制和清晰，会比追热点更有收获。",
        ],
        "colors": ["米白", "鼠尾草绿", "浅灰"],
        "numbers": [4, 6, 8],
    },
    "天秤": {
        "tone": "讲平衡、会协调、审美感强",
        "focus": "对齐、润滑、关系维护",
        "love": [
            "感情今天重在氛围，别让犹豫拖慢回应。",
            "你今天的魅力在分寸感，适合把话说圆但别太飘。",
            "想太多不如先迈一步，互动起来就容易顺。",
        ],
        "work": [
            "事业适合拉齐预期、对表意见、修正误会。",
            "你今天很适合做中间人，把多方情绪安顿好。",
            "别一直权衡到错过时机，差不多就可以拍板。",
        ],
        "money": [
            "财运适合做取舍和平衡，资源放在最顺手的位置就行。",
            "今天别什么都想兼顾，先保核心再谈扩展。",
            "你的收益来自判断和分配，不在于多快多猛。",
        ],
        "colors": ["浅粉", "天蓝", "雾白"],
        "numbers": [2, 6, 9],
    },
    "天蝎": {
        "tone": "集中、深、带一点压迫感",
        "focus": "洞察、拆解、定输赢",
        "love": [
            "感情里今天适合少试探多确认，别让沉默变成拉扯。",
            "你越真诚，越能避免无效猜心。",
            "今天适合把界限讲清楚，关系反而更稳。",
        ],
        "work": [
            "事业上适合盯核心问题，一刀切进重点。",
            "你今天拆问题的能力很强，适合处理复杂局面。",
            "别把所有事都搞成攻防战，能协作的时候也要协作。",
        ],
        "money": [
            "财运偏向深挖型，认真看细节比表面热闹更重要。",
            "今天适合先查清底层结构，再决定往哪边发力。",
            "别被表象带着跑，真正的收获在耐心里。",
        ],
        "colors": ["深红", "墨黑", "银灰"],
        "numbers": [3, 8, 9],
    },
    "射手": {
        "tone": "外放、乐观、爱试探边界",
        "focus": "探索、行动、扩大半径",
        "love": [
            "感情里别怕先开口，轻松一点最有魅力。",
            "今天适合主动创造见面和互动机会。",
            "你今天很适合带节奏，但别只顾自己开心。",
        ],
        "work": [
            "事业适合跑新线、试新路、接触新资源。",
            "今天的优势在视野，不在死磕一个角落。",
            "动起来会比坐着想更快找到出口。",
        ],
        "money": [
            "财运更适合从新机会和新连接里观察方向。",
            "今天适合大胆试探，但要给自己留回旋空间。",
            "把注意力放在空间和可能性上，别急着一步到位。",
        ],
        "colors": ["湖蓝", "亮橙", "白色"],
        "numbers": [3, 7, 9],
    },
    "摩羯": {
        "tone": "克制、稳、目标感强",
        "focus": "长期、执行、结果",
        "love": [
            "感情里今天别只顾务实，适当给点温度更有用。",
            "你不说别人不一定懂，所以表达比闷着更重要。",
            "关系想稳，就别只谈责任，也要谈感受。",
        ],
        "work": [
            "事业适合推进长期目标，今天做的事后劲很足。",
            "你今天更像压路机，慢但稳，适合啃硬骨头。",
            "不要急着求快，把框架搭稳才是关键。",
        ],
        "money": [
            "财运偏稳健路线，适合先巩固再外扩。",
            "今天更看重结构和耐力，而不是短时起伏。",
            "把节奏控住，比追逐新鲜感更值钱。",
        ],
        "colors": ["深灰", "棕色", "墨绿"],
        "numbers": [4, 5, 8],
    },
    "水瓶": {
        "tone": "跳脱、独立、脑回路新",
        "focus": "创意、解法、非典型路线",
        "love": [
            "感情里今天适合真诚表达自己的奇怪点，反而更迷人。",
            "别总想保持距离，适当靠近才会有故事。",
            "你今天很适合用新鲜感打开话题。",
        ],
        "work": [
            "事业适合换个脑回路，旧问题今天可能有新解法。",
            "你今天的亮点在创意和跳跃连接，别把自己框太死。",
            "适合做头脑风暴、破局、提新方案。",
        ],
        "money": [
            "财运更偏灵感型，适合观察新线索，但别急着马上全押。",
            "今天适合试小步快跑的方式，边看边调。",
            "收获来自想法和视角，不在蛮力。",
        ],
        "colors": ["电光蓝", "银白", "浅紫"],
        "numbers": [1, 4, 7],
    },
    "双鱼": {
        "tone": "柔、感受力强、想象丰富",
        "focus": "感知、连接、氛围",
        "love": [
            "感情里今天适合把温柔说出来，不要全靠对方猜。",
            "你今天很容易营造暧昧和温暖的氛围，别浪费。",
            "先照顾好自己的感受，再去接别人的情绪。",
        ],
        "work": [
            "事业适合做需要感觉和理解力的事，人情面会帮到你。",
            "今天你的优势在感知微妙变化，别强迫自己太机械。",
            "适合润色、包装、沟通、照顾氛围。",
        ],
        "money": [
            "财运更适合顺势而为，保持清醒比一时热情更重要。",
            "今天适合观察和体会，别因为心软或心动乱改节奏。",
            "把边界感守住，收获反而会更稳。",
        ],
        "colors": ["海蓝", "淡粉", "月白"],
        "numbers": [2, 7, 9],
    },
}

GENERAL_MOOD = [
    "今天整体节奏适合顺着感觉走，但关键节点还是要自己拍板。",
    "今天更适合把注意力放在眼前最有把握的一步。",
    "今天的状态有一点先抑后扬，越往后越顺。",
    "今天不怕慢，就怕乱，稳住节奏反而更容易赢。",
    "今天最容易出彩的地方在于你处理细节和关系的方式。",
]

HUANGLI_POOL = [
    {"yi": "祭祀、作灶、平治道涂、整理旧事", "ji": "搬家、安床、冲动签约、仓促远行"},
    {"yi": "出行、求医、谈合作、安排行程、联络老友", "ji": "破土、冲动下决定、情绪化争执、行丧"},
    {"yi": "祈福、订约、斋醮、复盘计划", "ji": "大修、搬迁、夜间远行、重大承诺"},
    {"yi": "嫁娶、修造、扫舍、见朋友", "ji": "仓促做重大安排、口舌争强、下猛药"},
    {"yi": "会友、修整、整理资料、复盘安排", "ji": "急着表态、硬顶情绪、把小事拖成大事"},
]

DIVINATION_POOL = [
    ("吉卦顺遂", "整体向上，心态放平，做事顺着节奏推进即可。"),
    ("火山旅 变 火风鼎", "动中见机，适合主动出击、扩社交、找新机会。"),
    ("天地否", "宜守不宜攻，先收拢节奏，等更好的时机。"),
    ("泽风大过", "力度够，但不要过头，先看结构再决定下一步。"),
    ("风雷益", "适合小步前进，边做边修正，越走越顺。"),
]

GAN_ZHI_YEAR = ["甲子", "乙丑", "丙寅", "丁卯", "戊辰", "己巳", "庚午", "辛未"]
DIRECTION_POOL = ["正东", "正南", "正西", "正北", "东北", "西南", "西北"]


class LocalFortuneTool:
    def get_fortune(self, mode: str = "all", sign: str = "") -> FortuneResult:
        normalized = str(mode or "all").strip().lower()
        if normalized in {"star", "sign", "constellation", "zodiac"}:
            resolved = _normalize_sign(sign) or _today_sign()
            return FortuneResult(
                mode="constellation",
                title="星座运势",
                content=self.get_constellation_fortune(resolved),
                sign=resolved,
            )
        if normalized in {"huangli", "almanac"}:
            return FortuneResult(mode="huangli", title="黄历", content=self.get_huangli())
        if normalized in {"divination", "plum", "meihua", "梅花"}:
            return FortuneResult(mode="divination", title="卦象", content=self.get_divination())
        if normalized not in {"all", "full", "today"}:
            raise ValueError("mode must be one of: all, constellation, huangli, divination")
        sign_name = _normalize_sign(sign) or _today_sign()
        content = (
            f"{self.get_constellation_fortune(sign_name)}\n"
            f"{'-' * 30}\n"
            f"{self.get_huangli()}\n"
            f"{'-' * 30}\n"
            f"{self.get_divination()}"
        )
        return FortuneResult(mode="all", title="今日运势总览", content=content, sign=sign_name)

    def get_constellation_fortune(self, sign: str = "") -> str:
        sign_name = _normalize_sign(sign) or _today_sign()
        today = dt.date.today()
        profile = SIGN_PROFILES[sign_name]
        mood = _pick(GENERAL_MOOD, today.isoformat(), sign_name, "mood")
        love = _pick(profile["love"], today.isoformat(), sign_name, "love")
        work = _pick(profile["work"], today.isoformat(), sign_name, "work")
        money = _pick(profile["money"], today.isoformat(), sign_name, "money")
        color = _pick(profile["colors"], today.isoformat(), sign_name, "color")
        number = _pick(profile["numbers"], today.isoformat(), sign_name, "number")
        return (
            f"✨【{sign_name} 今日离线运势】✨\n"
            f"📅日期：{today.isoformat()}\n"
            f"💫综合：{profile['tone']}。{profile['focus']}是今天的主轴。{mood}\n"
            f"❤️感情：{love}\n"
            f"💼事业：{work}\n"
            f"💰财运：{money}\n"
            f"🍀幸运颜色：{color}\n"
            f"🔢幸运数字：{number}"
        )

    def get_huangli(self) -> str:
        today = dt.date.today()
        item = _pick(HUANGLI_POOL, today.isoformat(), "huangli")
        ganzhi = GAN_ZHI_YEAR[today.year % len(GAN_ZHI_YEAR)]
        direction = _pick(DIRECTION_POOL, today.isoformat(), "direction")
        return (
            "📜【今日离线黄历】📜\n"
            f"公历：{today.isoformat()}\n"
            f"岁次干支：{ganzhi}\n"
            f"✅宜：{item['yi']}\n"
            f"❌忌：{item['ji']}\n"
            f"🧭顺势方位：{direction}\n"
            "⚠️提示：今天更适合稳一点，重要决定先确认再推进。"
        )

    def get_divination(self) -> str:
        today = dt.date.today()
        now = dt.datetime.now()
        gua_name, explain = _pick(DIVINATION_POOL, today.isoformat(), str(now.hour), "divination")
        moving = (_seed(today.isoformat(), str(now.hour), "moving") % 6) + 1
        return (
            "🔮【离线卦象】🔮\n"
            f"本卦：{gua_name}\n"
            f"动爻：第{moving}爻\n"
            f"卦象解读：{explain}\n"
            "✨总结：今天的关键不是玄学本身，而是顺势而为。"
        )


def _seed(*parts: str) -> int:
    key = "|".join(parts).encode("utf-8")
    return int(hashlib.sha256(key).hexdigest()[:12], 16)


def _pick(pool, *parts):
    idx = _seed(*parts) % len(pool)
    return pool[idx]


def _normalize_sign(value: str) -> str:
    lookup = str(value or "").strip().lower()
    if not lookup:
        return ""
    return CONSTELLATION_ALIASES.get(lookup, "")


def _today_sign() -> str:
    now = dt.datetime.now()
    month, day = now.month, now.day
    for name, m1, d1, m2, d2 in CONSTELLATION_RANGES:
        if (month == m1 and day >= d1) or (month == m2 and day <= d2):
            return name
    return "双子"
