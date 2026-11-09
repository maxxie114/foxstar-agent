from foxstar_bot.router import clean_search_query


def test_clean_search_query_removes_mentions_and_command_words():
    query = clean_search_query("@FoxStar 用Exa查一下 今天美国和伊朗的新闻", "FoxStar")

    assert query == "今天美国和伊朗的新闻"


def test_clean_search_query_does_not_invent_nvax():
    query = clean_search_query("@FoxStar 查一下 NVDA 今日价格", "FoxStar")

    assert "NVDA" in query
    assert "FoxStar" not in query


def test_clean_search_query_removes_nvax_alias_without_mention():
    query = clean_search_query("FoxStar, 查一下逆水寒手游月饼活动配方", "FoxStar")

    assert query == "逆水寒手游月饼活动配方"
