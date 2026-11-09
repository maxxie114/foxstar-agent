from pathlib import Path

from foxstar_bot.commands import CommandProcessor
from foxstar_bot.config import AppConfig
from foxstar_bot.memory_store import MemoryStore
from foxstar_bot.persistence import Database
from foxstar_bot.skills import SkillRegistry
from foxstar_bot.tool_games import AI_BASICS_QUIZ, COMMON_SENSE_QUIZ, NISHUIHAN_QUIZ, MiniGameTool


def test_game_commands_work(tmp_path):
    config = AppConfig(openai_api_key="x")
    db = Database(tmp_path / "bot.sqlite3")
    processor = CommandProcessor(config, db, MemoryStore(db))

    dice_result = processor.handle("/dice 2 6", "room", True, is_admin=True)
    rps_result = processor.handle("/rps rock", "room", True, is_admin=True)
    game_start = processor.handle("/game start quiz_ai", "room", True, is_admin=True)
    game_status = processor.handle("/game status", "room", True, is_admin=True)
    game_end = processor.handle("/game end", "room", True, is_admin=True)
    game_status_after = processor.handle("/game status", "room", True, is_admin=True)

    assert "d6 x2" in dice_result.reply
    assert "✂️" in rps_result.reply
    assert "第1题" in game_start.reply
    assert "type=quiz" in game_status.reply
    assert "game ended." in game_end.reply
    assert "game: none" in game_status_after.reply


def test_game_skills_exist():
    registry = SkillRegistry(Path("skills"))
    assert registry.get_skill("roll_dice") is not None
    assert registry.get_skill("rock_paper_scissors") is not None
    assert registry.get_skill("chengyu_chain") is not None
    assert registry.get_skill("riddle_game") is not None
    assert registry.get_skill("quiz_buzzer") is not None
    assert registry.get_skill("weather_lookup") is not None


def test_local_game_tool_is_randomized_but_well_formed():
    tool = MiniGameTool()
    dice = tool.roll_dice(count=3, sides=6)
    assert len(dice.rolls) == 3
    assert 3 <= dice.total <= 18

    rps = tool.play_rps("rock")
    assert rps.player_choice == "rock"
    assert rps.bot_choice in {"rock", "paper", "scissors"}
    assert rps.outcome in {"win", "lose", "draw"}

    opening = tool.pick_chengyu_opening()
    assert isinstance(opening, str) and len(opening) == 4

    quiz = tool.pick_quiz_questions("ai", 3)
    assert len(quiz) == 3

    brain_teasers = tool.pick_brain_teasers(10)
    assert len(brain_teasers) == 10
    assert all(item.question and item.answers for item in brain_teasers)

    assert tool.is_valid_chengyu("一见钟情")
    assert not tool.is_valid_chengyu("接不上了")
    response = tool.pick_chengyu_response("一", [])
    assert response
    assert response.startswith("一")


def test_quiz_banks_have_expected_scale():
    assert len(COMMON_SENSE_QUIZ) >= 100
    assert len(AI_BASICS_QUIZ) >= 100
    assert len(NISHUIHAN_QUIZ) >= 100


def test_brain_teaser_bank_works_without_external_corpus():
    tool = MiniGameTool()
    from foxstar_bot.tool_games import BRAIN_TEASER_BANK
    assert tool._load_brain_teasers() == BRAIN_TEASER_BANK
