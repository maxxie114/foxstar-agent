from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from random import shuffle

from foxstar_bot.quiz_banks import AI_BASICS_QUIZ_RAW, COMMON_SENSE_QUIZ_RAW, NISHUIHAN_QUIZ_RAW


RPS_ALIASES = {
    "rock": "rock",
    "r": "rock",
    "石头": "rock",
    "paper": "paper",
    "p": "paper",
    "布": "paper",
    "scissors": "scissors",
    "s": "scissors",
    "剪刀": "scissors",
}

RPS_DISPLAY = {
    "rock": "石头",
    "paper": "布",
    "scissors": "剪刀",
}


@dataclass(frozen=True)
class DiceRollResult:
    count: int
    sides: int
    rolls: list[int]
    total: int


@dataclass(frozen=True)
class RpsResult:
    player_choice: str
    bot_choice: str
    outcome: str


@dataclass(frozen=True)
class RiddlePrompt:
    question: str
    answers: tuple[str, ...]


@dataclass(frozen=True)
class QuizQuestion:
    question: str
    answers: tuple[str, ...]
    explanation: str = ""


CHENGYU_OPENINGS: tuple[str, ...] = (
    "一马当先",
    "春暖花开",
    "青出于蓝",
    "风调雨顺",
    "海阔天空",
    "一见钟情",
    "大展宏图",
    "四海升平",
    "金玉满堂",
    "龙腾虎跃",
    "气定神闲",
    "水到渠成",
    "柳暗花明",
    "乘风破浪",
    "妙手回春",
    "行云流水",
    "后来居上",
    "当仁不让",
    "同舟共济",
    "百炼成钢",
)


RIDDLE_BANK: tuple[RiddlePrompt, ...] = (
    RiddlePrompt("一口咬掉牛尾巴。打一字。", ("告",)),
    RiddlePrompt("上下一体。打一字。", ("卡",)),
    RiddlePrompt("十五天。打一字。", ("胖",)),
    RiddlePrompt("四面都是山，山山都相连。打一字。", ("田",)),
    RiddlePrompt("一只黑狗，不叫不吼。打一字。", ("默",)),
    RiddlePrompt("一月一日非今天。打一字。", ("明",)),
    RiddlePrompt("半个月亮。打一字。", ("胖",)),
    RiddlePrompt("需要一半，留下一半。打一字。", ("雷",)),
    RiddlePrompt("一点一横长，一撇到南洋。打一字。", ("广",)),
    RiddlePrompt("皇帝新衣。打一字。", ("袭",)),
    RiddlePrompt("不是葱，不是蒜，一层一层裹紫缎。打一蔬菜。", ("洋葱",)),
    RiddlePrompt("有面没有口，有脚没有手，虽有四只脚，自己不会走。打一家具。", ("桌子",)),
    RiddlePrompt("白天不懂夜的黑，晚上出来陪你飞。打一自然现象。", ("星星",)),
    RiddlePrompt("一物生来真奇怪，肚里孩子不出来。打一植物。", ("玉米",)),
    RiddlePrompt("红公鸡，绿尾巴，身体钻到地底下。打一蔬菜。", ("胡萝卜",)),
    RiddlePrompt("有门没有锁，有路没有人走。打一生活用品。", ("书",)),
    RiddlePrompt("屋子方方，有门没窗，屋外热烘烘，屋里冰霜。打一电器。", ("冰箱",)),
    RiddlePrompt("兄弟几个真和气，天天并肩坐一起。打一人体部位。", ("牙齿",)),
    RiddlePrompt("一个黑孩，从不开口，要是开口，掉出舌头。打一食物。", ("瓜子",)),
    RiddlePrompt("麻屋子，红帐子，里面住个白胖子。打一食物。", ("花生",)),
    RiddlePrompt("长长一条龙，走路轰隆隆，遇水它就停，过山又进洞。打一交通工具。", ("火车",)),
    RiddlePrompt("有风不动无风动，不动无风动有风。打一日用品。", ("扇子",)),
    RiddlePrompt("一个小姑娘，生在水中央，身穿粉红衫，坐在绿船上。打一植物。", ("荷花",)),
    RiddlePrompt("说鸟不是鸟，躲在树上叫，自夸懂得多，其实全不晓。打一动物。", ("蝉",)),
    RiddlePrompt("身穿白袍子，头戴红帽子，走路像公子，说话高嗓子。打一动物。", ("鹅",)),
    RiddlePrompt("弯弯一座桥，雨后天上挂。打一自然现象。", ("彩虹",)),
    RiddlePrompt("有时落在山腰，有时挂在树梢，有时像面圆镜，有时像把镰刀。打一自然现象。", ("月亮",)),
    RiddlePrompt("不洗真干净，洗洗不干净，不洗有人吃，洗了没人用。打一水。", ("泥水",)),
    RiddlePrompt("弟兄七八个，围着柱子坐，只要一分开，衣服就扯破。打一果实。", ("蒜", "大蒜")),
    RiddlePrompt("左一片，右一片，隔着山头不见面。打一人体器官。", ("耳朵",)),
    RiddlePrompt("五个兄弟，住在一起，名字不同，高矮不齐。打一人体部位。", ("手指",)),
    RiddlePrompt("十个客人十间屋，冷了进去暖了出。打一物。", ("手套",)),
    RiddlePrompt("有头无颈，有眼无眉，有翅难飞，无脚能追。打一鱼类。", ("鱼",)),
    RiddlePrompt("小时青青肚里空，长大有红也有青，剖开肚子看看看，一颗一颗小珍珠。打一水果。", ("石榴",)),
    RiddlePrompt("小小伞兵满天飞，落在田野不怕累。打一植物传播物。", ("蒲公英",)),
    RiddlePrompt("一边是红，一边是绿，一边怕风，一边怕雨。打一字。", ("秋",)),
    RiddlePrompt("一只小船两头尖，早晨驶来晚上还。打一生活用品。", ("梭子",)),
    RiddlePrompt("一位小姑娘，生在水中央，身穿白衣裳，坐在绿船上。打一植物。", ("莲花", "荷花")),
    RiddlePrompt("驼背公公，力大无穷；爱驮什么，车水马龙。打一交通设施。", ("桥",)),
    RiddlePrompt("远看像座亭，近看没窗棂，有门没有锁，冬暖夏天冷。打一建筑。", ("冰屋",)),
)


BRAIN_TEASER_BANK: tuple[RiddlePrompt, ...] = (
    RiddlePrompt("什么东西越洗越脏，不洗反而有人吃？", ("水", "洗菜水")),
    RiddlePrompt("什么门永远关不上？", ("球门",)),
    RiddlePrompt("什么车从来不需要加油？", ("风车",)),
    RiddlePrompt("什么蛋打不烂，煮不熟，更不能吃？", ("笨蛋", "坏蛋")),
    RiddlePrompt("什么人天天去看病，却从来不生病？", ("医生",)),
    RiddlePrompt("什么东西明明是你的，别人却用得比你多？", ("名字",)),
    RiddlePrompt("什么东西越剪越大？", ("洞", "窟窿")),
    RiddlePrompt("什么时候四减一会等于五？", ("切掉一个角", "切角")),
    RiddlePrompt("什么布不能做衣服？", ("瀑布",)),
    RiddlePrompt("什么虎不会咬人？", ("壁虎",)),
    RiddlePrompt("什么马不会跑？", ("木马",)),
    RiddlePrompt("什么东西有眼睛却看不见？", ("针", "针眼")),
    RiddlePrompt("什么东西你用右手拿不到？", ("右手",)),
    RiddlePrompt("什么东西越热越爱出来？", ("汗", "汗水")),
    RiddlePrompt("什么地方开口说话要付钱？", ("打电话", "电话里")),
    RiddlePrompt("什么人站着睡觉？", ("马",)),
    RiddlePrompt("什么字大家都会念错？", ("错",)),
    RiddlePrompt("什么东西倒立后会增加一半？", ("6", "六")),
    RiddlePrompt("什么书在书店买不到？", ("秘书",)),
    RiddlePrompt("什么帽不能戴？", ("螺帽",)),
    RiddlePrompt("什么东西一旦长出来，每个人都想把它剪掉？", ("指甲", "头发")),
    RiddlePrompt("什么路最窄？", ("冤家路窄",)),
    RiddlePrompt("什么东西越分享越多？", ("快乐", "知识", "经验")),
    RiddlePrompt("什么瓜不能吃？", ("傻瓜", "笨瓜")),
    RiddlePrompt("什么河里从来没有水？", ("银河",)),
    RiddlePrompt("什么东西切开后还是完整的一块？", ("水",)),
)


def _make_quiz_bank(raw: tuple[tuple[str, tuple[str, ...], str], ...]) -> tuple[QuizQuestion, ...]:
    return tuple(QuizQuestion(question=question, answers=answers, explanation=explanation) for question, answers, explanation in raw)


COMMON_SENSE_QUIZ: tuple[QuizQuestion, ...] = _make_quiz_bank(COMMON_SENSE_QUIZ_RAW)
AI_BASICS_QUIZ: tuple[QuizQuestion, ...] = _make_quiz_bank(AI_BASICS_QUIZ_RAW)
NISHUIHAN_QUIZ: tuple[QuizQuestion, ...] = _make_quiz_bank(NISHUIHAN_QUIZ_RAW)


class MiniGameTool:
    _idiom_words: frozenset[str] | None = None
    _idiom_by_first_char: dict[str, tuple[str, ...]] | None = None
    _brain_teasers: tuple[RiddlePrompt, ...] | None = None

    def roll_dice(self, count: int = 1, sides: int = 6) -> DiceRollResult:
        dice_count = max(1, min(int(count or 1), 10))
        dice_sides = max(2, min(int(sides or 6), 100))
        rolls = [random.randint(1, dice_sides) for _ in range(dice_count)]
        return DiceRollResult(count=dice_count, sides=dice_sides, rolls=rolls, total=sum(rolls))

    def play_rps(self, choice: str) -> RpsResult:
        player = self._normalize_rps_choice(choice)
        if not player:
            raise ValueError("choice must be one of: rock, paper, scissors / 石头, 布, 剪刀")
        bot = random.choice(["rock", "paper", "scissors"])
        if bot == player:
            outcome = "draw"
        elif (player == "rock" and bot == "scissors") or (player == "paper" and bot == "rock") or (player == "scissors" and bot == "paper"):
            outcome = "win"
        else:
            outcome = "lose"
        return RpsResult(player_choice=player, bot_choice=bot, outcome=outcome)

    def pick_riddles(self, count: int = 10) -> list[RiddlePrompt]:
        picks = min(max(int(count or 1), 1), len(RIDDLE_BANK))
        return random.sample(list(RIDDLE_BANK), picks)

    def pick_brain_teasers(self, count: int = 10) -> list[RiddlePrompt]:
        bank = self._load_brain_teasers()
        picks = min(max(int(count or 1), 1), len(bank))
        return random.sample(list(bank), picks)

    def pick_chengyu_opening(self, lookahead: int = 3) -> str:
        candidates = list(CHENGYU_OPENINGS)
        shuffle(candidates)
        for candidate in candidates:
            if self._has_future_chain(candidate, {candidate}, max(0, int(lookahead or 0))):
                return candidate
        return random.choice(list(CHENGYU_OPENINGS))

    def is_valid_chengyu(self, value: str) -> bool:
        candidate = str(value or "").strip()
        if len(candidate) != 4:
            return False
        if not all("\u4e00" <= ch <= "\u9fff" for ch in candidate):
            return False
        words, _ = self._load_idiom_index()
        return candidate in words

    def pick_chengyu_response(self, start_char: str, used: list[str], lookahead: int = 2) -> str:
        _, by_first = self._load_idiom_index()
        candidates = list(by_first.get(str(start_char or ""), ()))
        if not candidates:
            return ""
        used_set = {str(item) for item in used if str(item)}
        fresh = [item for item in candidates if item not in used_set]
        if not fresh:
            return ""
        shuffle(fresh)
        depth = max(0, int(lookahead or 0))
        for candidate in fresh[:300]:
            if self._has_future_chain(candidate, used_set | {candidate}, depth):
                return candidate
        return fresh[0]

    def pick_quiz_questions(self, category: str, count: int = 10) -> list[QuizQuestion]:
        lookup = {
            "common": COMMON_SENSE_QUIZ,
            "ai": AI_BASICS_QUIZ,
            "nsh": NISHUIHAN_QUIZ,
        }
        pool = lookup.get(str(category or "").strip().lower())
        if not pool:
            raise ValueError("quiz category must be one of: common, ai, nsh")
        picks = min(max(int(count or 1), 1), len(pool))
        return random.sample(list(pool), picks)

    @staticmethod
    def normalize_riddle_answer(value: str) -> str:
        return "".join(str(value or "").strip().split()).lower()

    @staticmethod
    def _normalize_rps_choice(value: str) -> str:
        lookup = str(value or "").strip().lower()
        return RPS_ALIASES.get(lookup, "")

    @classmethod
    def _load_brain_teasers(cls) -> tuple[RiddlePrompt, ...]:
        if cls._brain_teasers is not None:
            return cls._brain_teasers
        resource_path = Path(__file__).resolve().parent / "resources" / "brain_teasers_full.json"
        prompts: list[RiddlePrompt] = []
        if resource_path.exists():
            with resource_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            for item in payload:
                if not isinstance(item, dict):
                    continue
                question = str(item.get("question") or "").strip()
                raw_answers = item.get("answers") or []
                if not question or not isinstance(raw_answers, list):
                    continue
                answers = tuple(str(answer).strip() for answer in raw_answers if str(answer).strip())
                if answers:
                    prompts.append(RiddlePrompt(question=question, answers=answers))
        if not prompts:
            prompts = list(BRAIN_TEASER_BANK)
        cls._brain_teasers = tuple(prompts)
        return cls._brain_teasers

    @classmethod
    def _load_idiom_index(cls) -> tuple[frozenset[str], dict[str, tuple[str, ...]]]:
        if cls._idiom_words is not None and cls._idiom_by_first_char is not None:
            return cls._idiom_words, cls._idiom_by_first_char
        resource_dir = Path(__file__).resolve().parent / "resources"
        source_files = (
            resource_dir / "idiom.json",
            resource_dir / "chinese_xinhua_ci.json",
            resource_dir / "mapull_idiom.json",
            resource_dir / "mapull_word.json",
        )
        words = set(CHENGYU_OPENINGS)
        by_first: dict[str, list[str]] = {}
        for data_path in source_files:
            if not data_path.exists():
                continue
            with data_path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            for item in payload:
                if not isinstance(item, dict):
                    continue
                word = str(item.get("word") or item.get("name") or item.get("ci") or "").strip()
                if len(word) != 4:
                    continue
                if not all("\u4e00" <= ch <= "\u9fff" for ch in word):
                    continue
                words.add(word)
        for word in sorted(words):
            by_first.setdefault(word[0], []).append(word)
        cls._idiom_words = frozenset(words)
        cls._idiom_by_first_char = {key: tuple(values) for key, values in by_first.items()}
        return cls._idiom_words, cls._idiom_by_first_char

    @classmethod
    def _has_future_chain(cls, current_word: str, used: set[str], depth: int) -> bool:
        if depth <= 0:
            return True
        _, by_first = cls._load_idiom_index()
        next_candidates = by_first.get(current_word[-1], ())
        if not next_candidates:
            return False
        checked = 0
        for next_word in next_candidates:
            if next_word in used:
                continue
            checked += 1
            if cls._has_future_chain(next_word, used | {next_word}, depth - 1):
                return True
            if checked >= 80:
                break
        return False
