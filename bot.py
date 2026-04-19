import discord
from discord.ext import commands, tasks
import aiohttp
from bs4 import BeautifulSoup
import os
import json
import asyncio
from datetime import datetime

# ============================================================
#  КОНФИГУРАЦИЯ — попълни тук своите данни
# ============================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID    = int(os.getenv("CHANNEL_ID"))
CHECK_INTERVAL   = 60                   # Проверка на всеки 60 секунди
LAST_POST_FILE   = "last_post_id.json"  # Файл за запазване на последния пост
# ============================================================

TRUMP_URL = "https://www.trumpstruth.org/"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


def load_last_post_id() -> str | None:
    if os.path.exists(LAST_POST_FILE):
        with open(LAST_POST_FILE, "r") as f:
            data = json.load(f)
            return data.get("last_id")
    return None


def save_last_post_id(post_id: str):
    with open(LAST_POST_FILE, "w") as f:
        json.dump({"last_id": post_id}, f)


async def fetch_latest_post() -> dict | None:
    """Взима последния пост от trumpstruth.org"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(TRUMP_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    print(f"[ERROR] HTTP {resp.status} от trumpstruth.org")
                    return None
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")

        # Намираме блоковете с постове
        posts = soup.find_all("div", class_="truth")
        if not posts:
            # Опитваме с по-общ селектор
            posts = soup.find_all("p")

        if not posts:
            print("[WARN] Не са намерени постове в HTML-а.")
            return None

        first = posts[0]
        text = first.get_text(separator=" ", strip=True)

        # Намираме дата/час
        time_tag = soup.find("time") or soup.find(class_="timestamp")
        date_str = time_tag.get_text(strip=True) if time_tag else "Неизвестна дата"

        # Уникален ID — използваме хеш на текста
        import hashlib
        post_id = hashlib.md5(text.encode()).hexdigest()

        # Линк към оригиналния пост
        link_tag = first.find("a", href=True)
        original_url = link_tag["href"] if link_tag else TRUMP_URL

        return {
            "id":   post_id,
            "text": text[:1500],   # Discord има лимит
            "date": date_str,
            "url":  original_url,
        }

    except Exception as e:
        print(f"[ERROR] Грешка при fetch: {e}")
        return None


def build_embed(post: dict) -> discord.Embed:
    embed = discord.Embed(
        title="🇺🇸 Нова публикация на Доналд Тръмп",
        description=post["text"],
        color=0xE8192C,
        url=post["url"] if post["url"].startswith("http") else TRUMP_URL,
        timestamp=datetime.utcnow(),
    )
    embed.set_author(
        name="Donald J. Trump · @realDonaldTrump",
        icon_url="https://upload.wikimedia.org/wikipedia/commons/thumb/5/56/White_shark.jpg/1px-White_shark.jpg",
    )
    embed.add_field(name="📅 Публикувано", value=post["date"], inline=False)
    embed.add_field(name="🔗 Източник", value="[trumpstruth.org](https://www.trumpstruth.org/)", inline=False)
    embed.set_footer(text="Truth Social Monitor Bot")
    return embed


@tasks.loop(seconds=CHECK_INTERVAL)
async def check_for_new_posts():
    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"[ERROR] Канал {CHANNEL_ID} не е намерен!")
        return

    post = await fetch_latest_post()
    if post is None:
        return

    last_id = load_last_post_id()

    if post["id"] != last_id:
        print(f"[NEW POST] {post['date']} — {post['text'][:80]}...")
        save_last_post_id(post["id"])

        embed = build_embed(post)
        await channel.send(
            content="@everyone 🚨 **Тръмп публикува нещо ново в Truth Social!**",
            embed=embed,
        )
    else:
        print(f"[CHECK] Няма нов пост. ({datetime.now().strftime('%H:%M:%S')})")


@check_for_new_posts.before_loop
async def before_check():
    await bot.wait_until_ready()
    print("[BOT] Готов. Стартирам мониторинга...")


@bot.event
async def on_ready():
    print(f"[BOT] Влязох като: {bot.user} (ID: {bot.user.id})")
    print(f"[BOT] Следя Truth Social на всеки {CHECK_INTERVAL} секунди.")
    check_for_new_posts.start()


@bot.command(name="lastpost")
async def last_post(ctx):
    """!lastpost — показва последния намерен пост"""
    await ctx.send("⏳ Проверявам Truth Social...")
    post = await fetch_latest_post()
    if post:
        embed = build_embed(post)
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Не успях да намеря пост. Опитай по-късно.")


@bot.command(name="status")
async def status(ctx):
    """!status — показва статуса на бота"""
    last_id = load_last_post_id()
    embed = discord.Embed(title="📊 Статус на бота", color=0x00AAFF)
    embed.add_field(name="✅ Онлайн", value="Да", inline=True)
    embed.add_field(name="⏱️ Интервал", value=f"{CHECK_INTERVAL} сек.", inline=True)
    embed.add_field(name="🆔 Последен пост ID", value=last_id or "Все още не е засечен", inline=False)
    await ctx.send(embed=embed)


bot.run(DISCORD_TOKEN)
