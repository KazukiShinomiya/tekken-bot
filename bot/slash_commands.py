"""
Discord スラッシュコマンド Bot。

コマンド一覧:
  /tekken today  — 今日の戦績を即時取得・投稿
  /tekken weekly — 週次サマリーを即時投稿
  /tekken status — Bot 稼働状況を確認
"""

import asyncio
import logging
import threading
from datetime import datetime

import discord
from discord import app_commands

import main as _bot_main
from bot.config import DISCORD_BOT_TOKEN as BOT_TOKEN, JST

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

tekken_group = app_commands.Group(name="tekken", description="鉄拳Bot コマンド")


@tekken_group.command(name="today", description="今日の戦績を取得して投稿する")
async def cmd_today(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    try:
        await asyncio.get_running_loop().run_in_executor(None, _bot_main.main)
        await interaction.followup.send("✅ 本日の戦績を投稿しました。")
    except Exception as e:
        logger.error(f"[slash_commands] /tekken today エラー: {e}")
        await interaction.followup.send(f"❌ エラーが発生しました: {e}")


@tekken_group.command(name="weekly", description="週次サマリーを投稿する")
async def cmd_weekly(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    try:
        await asyncio.get_running_loop().run_in_executor(None, _bot_main.weekly)
        await interaction.followup.send("✅ 週次サマリーを投稿しました。")
    except Exception as e:
        logger.error(f"[slash_commands] /tekken weekly エラー: {e}")
        await interaction.followup.send(f"❌ エラーが発生しました: {e}")


@tekken_group.command(name="status", description="Bot の稼働状況を確認する")
async def cmd_status(interaction: discord.Interaction) -> None:
    now = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
    await interaction.response.send_message(f"✅ Bot 稼働中 | {now} JST")


tree.add_command(tekken_group)


@client.event
async def on_ready() -> None:
    await tree.sync()
    logger.info(f"[slash_commands] Bot ログイン完了: {client.user} | スラッシュコマンド同期済み")


def start_bot() -> None:
    if not BOT_TOKEN:
        logger.warning("[slash_commands] DISCORD_BOT_TOKEN が未設定。スラッシュコマンドは無効。")
        return
    try:
        client.run(BOT_TOKEN, log_handler=None)
    except Exception as e:
        logger.error(f"[slash_commands] Bot 起動失敗: {e}")


def start_bot_thread() -> threading.Thread:
    """スラッシュコマンド Bot をバックグラウンドスレッドで起動する。"""
    t = threading.Thread(target=start_bot, daemon=True, name="discord-bot")
    t.start()
    return t
