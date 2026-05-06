import os
import sys

LOCK_FILE = "/tmp/bot.lock"

if os.path.exists(LOCK_FILE):
    print("❌ Вече има стартиран бот. Излизам...")
    sys.exit()

with open(LOCK_FILE, "w") as f:
    f.write("running")
import discord
from discord.ext import commands, tasks
import aiohttp
from bs4 import BeautifulSoup
import os
import re
import hashlib
import asyncio
from datetime import datetime

# ============================================================
#  КОНФИГУРАЦИЯ
# ============================================================
DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN")
CHANNEL_ID      = int(os.getenv("CHANNEL_ID"))
CHECK_INTERVAL  = int(os.getenv("CHECK_INTERVAL", "30"))
# ============================================================

TRUMP_URL = "https://www.trumpstruth.org/"

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
bot = commands.Bot(command_prefix="!", intents=intents)

_cached_last_id: str | None = None
_started = False  # Предотвратява двоен старт при reconnect


def extract_date(soup, html: str) -> str:
    time_tag = soup.find("time")
    if time_tag:
        val = time_tag.get("datetime") or time_tag.get_text(strip=True)
        if val:
            return val
    for cls in ["timestamp", "date", "created-at"]:
        tag = soup.find(class_=cls)
        if tag:
            return tag.get_text(strip=True)
    match = re.search(
        r'(January|February|March|April|May|June|July|August'
        r'|September|October|November|December)'
        r'\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s+[AP]M',
        html
    )
    if match:
        return match.group(0)
    match = re.search(
        r'(January|February|March|April|May|June|July|August'
        r'|September|October|November|December)'
        r'\s+\d{1,2},\s+\d{4}',
        html
    )
    if match:
        return match.group(0)
    return "Неизвестна дата"


async def fetch_latest_post():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                TRUMP_URL,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status != 200:
                    print(f"[ERROR] HTTP {resp.status}")
                    return None
                html = await resp.text()

        soup = BeautifulSoup(html, "html.parser")
        posts = soup.find_all("div", class_="truth")
        if not posts:
            posts = soup.find_all("p")
        if not posts:
            print("[WARN] Не са намерени постове.")
            return None

        first = posts[0]
        text = first.get_text(separator=" ", strip=True)
        date_str = extract_date(soup, html)
        stable_text = " ".join(text.split())[:100]
        post_id = hashlib.md5(stable_text.encode()).hexdigest()
        link_tag = first.find("a", href=True)
        original_url = link_tag["href"] if link_tag else TRUMP_URL

        return {
            "id":   post_id,
            "text": text[:1500],
            "date": date_str,
            "url":  original_url,
        }
    except Exception as e:
        print(f"[ERROR] Грешка при fetch: {e}")
        return None


async def load_last_id_from_discord() -> str | None:
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if channel is None:
            return None
        async for message in channel.history(limit=100):
            if message.author == bot.user and message.embeds:
                footer = message.embeds[0].footer
                if footer and footer.text and "ID:" in footer.text:
                    for part in footer.text.split("|"):
                        part = part.strip()
                        if part.startswith("ID:"):
                            found_id = part.replace("ID:", "").strip()
                            print(f"[DISCORD] Намерен последен ID: {found_id[:8]}...")
                            return found_id
        return None
    except Exception as e:
        print(f"[WARN] Грешка при четене на Discord история: {e}")
        return None


def build_embed(post: dict) -> discord.Embed:
    url = post["url"] if post["url"].startswith("http") else TRUMP_URL
    embed = discord.Embed(
        title="🇺🇸 Нова публикация на Доналд Тръмп",
        description=post["text"],
        color=0xE8192C,
        url=url,
        timestamp=datetime.utcnow(),
    )
    embed.set_author(name="Donald J. Trump · @realDonaldTrump")
    embed.add_field(name="📅 Публикувано", value=post["date"], inline=False)
    embed.add_field(
        name="🔗 Източник",
        value="[trumpstruth.org](https://www.trumpstruth.org/)",
        inline=False
    )
    embed.set_footer(text=f"Truth Social Monitor Bot | ID: {post['id']}")
    return embed


@tasks.loop(seconds=CHECK_INTERVAL)
async def check_for_new_posts():
    global _cached_last_id

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print(f"[ERROR] Канал {CHANNEL_ID} не е намерен!")
        return

    post = await fetch_latest_post()
    if post is None:
        return

    print(f"[CHECK] Кеш: {_cached_last_id[:8] if _cached_last_id else 'Няма'} | Нов: {post['id'][:8]} ({datetime.now().strftime('%H:%M:%S')})")

    if post["id"] != _cached_last_id:
        print(f"[NEW POST] {post['date']} — {post['text'][:80]}...")
        _cached_last_id = post["id"]
        embed = build_embed(post)
        await channel.send(
            content="@everyone 🚨 **Тръмп публикува нещо ново в Truth Social!**",
            embed=embed,
        )
    else:
        print(f"[CHECK] Няма нов пост.")


@check_for_new_posts.before_loop
async def before_check():
    global _cached_last_id
    await bot.wait_until_ready()
    await asyncio.sleep(5)
    _cached_last_id = await load_last_id_from_discord()
    print(f"[BOT] Последен ID при старт: {_cached_last_id[:8] if _cached_last_id else 'Няма'}")
    print(f"[BOT] Проверка на всеки {CHECK_INTERVAL} секунди.")


@bot.event
async def on_ready():
    global _started
    print(f"[BOT] Влязох като: {bot.user} (ID: {bot.user.id})")

    # Стартираме loop-а само ВЕДНЪЖ — предотвратява дублиране при reconnect
    if not _started:
        _started = True
        check_for_new_posts.start()
        print("[BOT] Мониторингът стартиран.")
    else:
        print("[BOT] Reconnect — мониторингът вече работи, не стартираме отново.")


@bot.command(name="lastpost")
async def last_post(ctx):
    await ctx.send("⏳ Проверявам Truth Social...")
    post = await fetch_latest_post()
    if post:
        embed = build_embed(post)
        await ctx.send(embed=embed)
    else:
        await ctx.send("❌ Не успях да намеря пост. Опитай по-късно.")


@bot.command(name="status")
async def status(ctx):
    embed = discord.Embed(title="📊 Статус на бота", color=0x00AAFF)
    embed.add_field(name="✅ Онлайн", value="Да", inline=True)
    embed.add_field(name="⏱️ Интервал", value=f"{CHECK_INTERVAL} сек.", inline=True)
    embed.add_field(
        name="🆔 Последен пост ID",
        value=_cached_last_id[:8] + "..." if _cached_last_id else "Все още не е засечен",
        inline=False
    )
    await ctx.send(embed=embed)


bot.run(DISCORD_TOKEN)
