"""
bot/exceptions.py のテスト。
例外クラスの継承関係と raise / catch を検証する。
"""

import pytest

from bot.exceptions import (
    AnalysisError,
    DatabaseError,
    DataFetchError,
    DiscordPostError,
    TekkenBotError,
)


def test_tekken_bot_error_is_exception():
    assert issubclass(TekkenBotError, Exception)


def test_data_fetch_error_is_tekken_bot_error():
    assert issubclass(DataFetchError, TekkenBotError)


def test_discord_post_error_is_tekken_bot_error():
    assert issubclass(DiscordPostError, TekkenBotError)


def test_analysis_error_is_tekken_bot_error():
    assert issubclass(AnalysisError, TekkenBotError)


def test_database_error_is_tekken_bot_error():
    assert issubclass(DatabaseError, TekkenBotError)


def test_can_raise_and_catch_as_base():
    """サブクラスを TekkenBotError として捕捉できる。"""
    with pytest.raises(TekkenBotError):
        raise DataFetchError("fetch failed")


def test_each_subclass_is_catchable_individually():
    """各サブクラスが個別に catch できる。"""
    for cls in (DataFetchError, DiscordPostError, AnalysisError, DatabaseError):
        with pytest.raises(cls):
            raise cls("error")


def test_exception_message_preserved():
    """例外メッセージが保持される。"""
    err = DataFetchError("something went wrong")
    assert "something went wrong" in str(err)
