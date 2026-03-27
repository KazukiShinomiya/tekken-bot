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

import bot.db as db
import main as _bot_main
from bot.config import DISCORD_BOT_TOKEN as BOT_TOKEN, JST
from bot.stats import count_wins, count_losses

logger = logging.getLogger(__name__)

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

tekken_group = app_commands.Group(name="tekken", description="鉄拳Bot コマンド")


@tekken_group.command(name="today", description="戦績を取得して投稿する（省略時は今日、日付指定も可）")
@app_commands.describe(date="対象日 YYYY-MM-DD（省略すると今日）")
async def cmd_today(interaction: discord.Interaction, date: str | None = None) -> None:
    await interaction.response.defer(thinking=True)
    try:
        if date is not None:
            datetime.strptime(date, "%Y-%m-%d")  # バリデーション
            target_date = date
        else:
            target_date = datetime.now(JST).strftime("%Y-%m-%d")
        await _bot_main.main(target_date=target_date)
        await interaction.followup.send(f"✅ {target_date} の戦績を投稿しました。")
    except ValueError:
        await interaction.followup.send("❌ 日付形式が正しくありません（YYYY-MM-DD）。")
    except Exception as e:
        logger.error(f"[slash_commands] /tekken today エラー: {e}")
        await interaction.followup.send(f"❌ エラーが発生しました: {e}")


@tekken_group.command(name="weekly", description="週次サマリーを投稿する")
async def cmd_weekly(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    try:
        await _bot_main.weekly()
        await interaction.followup.send("✅ 週次サマリーを投稿しました。")
    except Exception as e:
        logger.error(f"[slash_commands] /tekken weekly エラー: {e}")
        await interaction.followup.send(f"❌ エラーが発生しました: {e}")


@tekken_group.command(name="status", description="Bot の稼働状況を確認する")
async def cmd_status(interaction: discord.Interaction) -> None:
    now = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
    await interaction.response.send_message(f"✅ Bot 稼働中 | {now} JST")


@tekken_group.command(name="vs", description="特定の対戦相手との通算成績を確認する")
@app_commands.describe(name="対戦相手の名前（部分一致）")
async def cmd_vs(interaction: discord.Interaction, name: str) -> None:
    await interaction.response.defer(thinking=True)
    battles = db.search_battles_vs_opponent(name)
    if not battles:
        await interaction.followup.send(f"❌ `{name}` との対戦記録が見つかりません。")
        return

    wins   = count_wins(battles)
    losses = count_losses(battles)
    total  = wins + losses
    wr     = wins / total * 100 if total else 0

    chara_count: dict[str, int] = {}
    for b in battles:
        c = b.get("opp_chara") or "???"
        chara_count[c] = chara_count.get(c, 0) + 1
    main_chara = max(chara_count, key=chara_count.__getitem__) if chara_count else "???"

    recent = sorted(battles, key=lambda x: x["battle_at"], reverse=True)[:5]
    recent_lines = []
    for b in recent:
        dt   = datetime.fromtimestamp(b["battle_at"], JST).strftime("%m/%d")
        icon = "✅" if b["won"] else "❌"
        recent_lines.append(f"{icon} {dt}  {b.get('my_chara','???')} vs {b.get('opp_chara','???')}")

    embed = discord.Embed(
        title=f"🔍 vs {name} の通算成績",
        color=0x57F287 if wr >= 50 else 0xED4245,
    )
    embed.add_field(name="通算", value=f"{wins}勝{losses}敗 ({wr:.0f}%)", inline=True)
    embed.add_field(name="対戦キャラ（最多）", value=main_chara, inline=True)
    if recent_lines:
        embed.add_field(name="直近5試合", value="\n".join(recent_lines), inline=False)
    await interaction.followup.send(embed=embed)


@tekken_group.command(name="chara", description="特定キャラクターとの対戦成績を確認する")
@app_commands.describe(name="キャラクター名（例: Bryan, Jin）")
async def cmd_chara(interaction: discord.Interaction, name: str) -> None:
    await interaction.response.defer(thinking=True)
    battles = db.get_battles_by_opp_chara(name)
    if not battles:
        await interaction.followup.send(f"❌ `{name}` との対戦記録が見つかりません。")
        return

    wins   = count_wins(battles)
    losses = count_losses(battles)
    total  = wins + losses
    wr     = wins / total * 100 if total else 0

    recent = sorted(battles, key=lambda x: x["battle_at"], reverse=True)[:10]
    recent_icons = " ".join("✅" if b["won"] else "❌" for b in recent)

    embed = discord.Embed(
        title=f"🥊 vs {name} の通算成績",
        color=0x57F287 if wr >= 50 else 0xED4245,
    )
    embed.add_field(name="通算",   value=f"{wins}勝{losses}敗", inline=True)
    embed.add_field(name="勝率",   value=f"{wr:.1f}%",          inline=True)
    embed.add_field(name="総試合", value=f"{total}戦",          inline=True)
    embed.add_field(name="直近10試合", value=recent_icons or "-", inline=False)
    await interaction.followup.send(embed=embed)


@tekken_group.command(name="top", description="キャラ別対戦成績ランキングを確認する（全期間）")
async def cmd_top(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    stats = db.get_matchup_ranking(min_battles=2)
    if not stats:
        await interaction.followup.send("❌ 対戦データが足りません（各キャラ2戦以上必要）。")
        return

    lines = []
    for row in stats[:20]:
        chara  = row["opp_chara"] or "???"
        wins   = row["wins"]
        total  = row["total"]
        losses = total - wins
        wr     = wins / total * 100
        icon   = "✅" if wr > 50 else ("❌" if wr < 50 else "➖")
        lines.append(f"{icon} {chara:<12} {wins}勝{losses}敗 ({wr:.0f}%)")

    embed = discord.Embed(
        title="📊 キャラ別対戦成績（試合数順）",
        description="```\n" + "\n".join(lines) + "\n```",
        color=0x5865F2,
    )
    await interaction.followup.send(embed=embed)


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
