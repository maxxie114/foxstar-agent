from __future__ import annotations

from dataclasses import dataclass

FORMAT_STYLES = {"strict", "human", "free"}

DEFAULT_FORMAT_STYLE = "strict"

MBTI_TYPES = {
    "intj",
    "intp",
    "entj",
    "entp",
    "infj",
    "infp",
    "enfj",
    "enfp",
    "istj",
    "isfj",
    "estj",
    "esfj",
    "istp",
    "isfp",
    "estp",
    "esfp",
}

ZODIAC_ALIASES = {
    "aries": "aries",
    "baiyang": "aries",
    "\u767d\u7f8a": "aries",
    "\u767d\u7f8a\u5ea7": "aries",
    "taurus": "taurus",
    "jinniu": "taurus",
    "\u91d1\u725b": "taurus",
    "\u91d1\u725b\u5ea7": "taurus",
    "gemini": "gemini",
    "shuangzi": "gemini",
    "\u53cc\u5b50": "gemini",
    "\u53cc\u5b50\u5ea7": "gemini",
    "cancer": "cancer",
    "juxie": "cancer",
    "\u5de8\u87f9": "cancer",
    "\u5de8\u87f9\u5ea7": "cancer",
    "leo": "leo",
    "shizi": "leo",
    "\u72ee\u5b50": "leo",
    "\u72ee\u5b50\u5ea7": "leo",
    "virgo": "virgo",
    "chunv": "virgo",
    "\u5904\u5973": "virgo",
    "\u5904\u5973\u5ea7": "virgo",
    "libra": "libra",
    "tiancheng": "libra",
    "tianping": "libra",
    "\u5929\u79e4": "libra",
    "\u5929\u79e4\u5ea7": "libra",
    "\u5929\u5e73": "libra",
    "\u5929\u5e73\u5ea7": "libra",
    "scorpio": "scorpio",
    "tianxie": "scorpio",
    "\u5929\u874e": "scorpio",
    "\u5929\u874e\u5ea7": "scorpio",
    "sagittarius": "sagittarius",
    "sheshou": "sagittarius",
    "\u5c04\u624b": "sagittarius",
    "\u5c04\u624b\u5ea7": "sagittarius",
    "capricorn": "capricorn",
    "mojie": "capricorn",
    "\u6469\u7faf": "capricorn",
    "\u6469\u7faf\u5ea7": "capricorn",
    "\u9b54\u7faf": "capricorn",
    "\u9b54\u7faf\u5ea7": "capricorn",
    "aquarius": "aquarius",
    "shuiping": "aquarius",
    "\u6c34\u74f6": "aquarius",
    "\u6c34\u74f6\u5ea7": "aquarius",
    "pisces": "pisces",
    "shuangyu": "pisces",
    "\u53cc\u9c7c": "pisces",
    "\u53cc\u9c7c\u5ea7": "pisces",
}

ZODIAC_SIGNS = tuple(dict.fromkeys(ZODIAC_ALIASES.values()))

GENDER_ALIASES = {
    "female": "feminine",
    "feminine": "feminine",
    "girl": "feminine",
    "girly": "feminine",
    "woman": "feminine",
    "nv": "feminine",
    "nusheng": "feminine",
    "nvsheng": "feminine",
    "\u5973": "feminine",
    "\u5973\u751f": "feminine",
    "\u5973\u5b69": "feminine",
    "\u5973\u6027": "feminine",
    "\u59d0\u59b9": "feminine",
    "male": "masculine",
    "masculine": "masculine",
    "boy": "masculine",
    "man": "masculine",
    "nan": "masculine",
    "\u7537": "masculine",
    "\u7537\u751f": "masculine",
    "\u7537\u6027": "masculine",
    "neutral": "neutral",
    "zhongxing": "neutral",
    "\u4e2d\u6027": "neutral",
}

TONE_ALIASES = {
    "soft": "soft",
    "gentle": "soft",
    "tender": "soft",
    "sweet": "sweet",
    "cute": "cute",
    "playful": "playful",
    "warm": "warm",
    "wenrou": "soft",
    "ruan": "soft",
    "keai": "cute",
    "\u67d4\u8f6f": "soft",
    "\u6e29\u67d4": "soft",
    "\u8f6f": "soft",
    "\u751c": "sweet",
    "\u751c\u4e00\u70b9": "sweet",
    "\u53ef\u7231": "cute",
    "\u4fcf\u76ae": "playful",
    "\u6e29\u6696": "warm",
}

GENDER_TRAITS = tuple(dict.fromkeys(GENDER_ALIASES.values()))

TONE_TRAITS = tuple(dict.fromkeys(TONE_ALIASES.values()))

MBTI_PROMPTS = {
    "intj": "cool, concise, strategic, and comfortable pointing out weak logic",
    "intp": "curious, analytic, and dryly precise",
    "entj": "decisive, direct, and action-oriented",
    "entp": "quick, playful, argumentative in a fun way, and good at reframing",
    "infj": "quietly perceptive, warm, and good at reading subtext",
    "infp": "gentle, sincere, and values-driven",
    "enfj": "warm, socially aware, and good at smoothing the room without becoming fake",
    "enfp": "bright, spontaneous, emotionally warm, and good at catching jokes",
    "istj": "steady, factual, and practical",
    "isfj": "soft, patient, attentive, and supportive",
    "estj": "practical, organized, and blunt when needed",
    "esfj": "warm, social, and responsive to group mood",
    "istp": "calm, terse, hands-on, and a little dry",
    "isfp": "soft-spoken, sensory, sincere, and low-drama",
    "estp": "bold, lively, teasing, and quick to act",
    "esfp": "expressive, playful, social, and light",
}

ZODIAC_PROMPTS = {
    "aries": "a little bolder, more direct, energetic, playful, and quick to react, but not aggressive",
    "taurus": "steady, warm, grounded, and not easily rushed",
    "gemini": "quick, chatty, curious, and good at switching angles",
    "cancer": "soft, caring, protective, and emotionally aware",
    "leo": "confident, sunny, expressive, and a little theatrical",
    "virgo": "detail-aware, practical, clean, and gently critical",
    "libra": "balanced, socially smooth, aesthetic, and conflict-aware",
    "scorpio": "sharp, intense, perceptive, and good at reading hidden motives",
    "sagittarius": "open, funny, direct, and adventurous",
    "capricorn": "calm, mature, pragmatic, and no-nonsense",
    "aquarius": "independent, quirky, abstract, and a little detached",
    "pisces": "dreamy, soft, empathetic, and emotionally fluid",
}

GENDER_PROMPTS = {
    "feminine": "use a softer feminine-coded voice: warm, emotionally aware, light, cute when appropriate, but do not claim to be a woman or mention gender",
    "masculine": "use a slightly more masculine-coded voice: steady, direct, protective, and low-drama, but do not claim to be a man or mention gender",
    "neutral": "keep the voice gender-neutral and avoid gender-coded performance",
}

TONE_PROMPTS = {
    "soft": "make the tone softer, gentler, and less confrontational",
    "sweet": "make the tone sweeter and warmer without becoming cloying",
    "cute": "allow a bit more cute/playful wording when it fits the chat",
    "playful": "allow more playful interjections and light teasing",
    "warm": "make the tone warmer and more emotionally responsive",
}

@dataclass(frozen=True)
class StyleProfile:
    format_style: str = DEFAULT_FORMAT_STYLE
    personality_traits: tuple[str, ...] = ()

    @property
    def storage_value(self) -> str:
        parts = [self.format_style, *self.personality_traits]
        return " ".join(parts)

    @property
    def display_value(self) -> str:
        if not self.personality_traits:
            return self.format_style
        return f"{self.format_style} {' '.join(self.personality_traits)}"

def parse_style_tokens(tokens: list[str]) -> tuple[StyleProfile | None, str]:
    normalized = [_normalize_token(token) for token in tokens if token.strip()]
    if not normalized:
        return None, style_help()
    if normalized == ["clear"]:
        return StyleProfile(), ""

    format_style = DEFAULT_FORMAT_STYLE
    traits: list[str] = []
    for token in normalized:
        if token in FORMAT_STYLES:
            format_style = token
            continue
        trait = normalize_personality_trait(token)
        if trait is None:
            return None, f"Unknown style: {token}. {style_help()}"
        if trait not in traits:
            traits.append(trait)

    return StyleProfile(format_style=format_style, personality_traits=tuple(traits)), ""

def parse_stored_style(value: str | None) -> StyleProfile:
    if not value:
        return StyleProfile()
    profile, error = parse_style_tokens(value.split())
    if profile is None:
        return StyleProfile()
    return profile

def normalize_personality_trait(token: str) -> str | None:
    token = _normalize_token(token)
    if token in MBTI_TYPES:
        return token
    return ZODIAC_ALIASES.get(token) or GENDER_ALIASES.get(token) or TONE_ALIASES.get(token)

def style_personality_prompt(profile: StyleProfile) -> str:
    if not profile.personality_traits:
        return ""

    mbti = [trait.upper() for trait in profile.personality_traits if trait in MBTI_TYPES]
    zodiac = [trait for trait in profile.personality_traits if trait in ZODIAC_SIGNS]
    gender = [trait for trait in profile.personality_traits if trait in GENDER_TRAITS]
    tone = [trait for trait in profile.personality_traits if trait in TONE_TRAITS]
    parts: list[str] = []
    if mbti:
        parts.append("MBTI hints: " + ", ".join(mbti))
    if zodiac:
        parts.append("zodiac hints: " + ", ".join(zodiac))
    if gender:
        parts.append("gender-coded voice hints: " + ", ".join(gender))
    if tone:
        parts.append("tone hints: " + ", ".join(tone))
    instructions = _trait_instructions(profile.personality_traits)
    return (
        "Current group style includes personality hints: "
        + "; ".join(parts)
        + ". Apply these as noticeable voice and temperament guidance, not as roleplay or identity claims. "
        + instructions
        + " Do not claim the bot literally has an MBTI type, zodiac sign, or gender. Do not mention this setting unless asked."
    )

def _normalize_token(token: str) -> str:
    return token.strip().lower().replace("-", "").replace("_", "")

def _trait_instructions(traits: tuple[str, ...]) -> str:
    descriptions: list[str] = []
    for trait in traits:
        if trait in MBTI_PROMPTS:
            descriptions.append(f"{trait.upper()}: {MBTI_PROMPTS[trait]}.")
        elif trait in ZODIAC_PROMPTS:
            descriptions.append(f"{trait}: {ZODIAC_PROMPTS[trait]}.")
        elif trait in GENDER_PROMPTS:
            descriptions.append(f"{trait}: {GENDER_PROMPTS[trait]}.")
        elif trait in TONE_PROMPTS:
            descriptions.append(f"{trait}: {TONE_PROMPTS[trait]}.")
    if not descriptions:
        return ""
    return "Concrete voice guidance: " + " ".join(descriptions)
