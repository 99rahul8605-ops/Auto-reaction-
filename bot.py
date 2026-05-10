import os
import logging
import asyncio
import random
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji

# ─── Logging Setup ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Config from Environment ─────────────────────────────────────
API_ID       = int(os.environ["API_ID"])
API_HASH     = os.environ["API_HASH"]
BOT_TOKEN    = os.environ["BOT_TOKEN"]
PORT         = int(os.environ.get("PORT", 8080))
BOT_NAME     = os.environ.get("BOT_NAME", "Auto Reaction Bot")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "")  # e.g. myreactionbot (without @)

# ─── Reactions Pool ──────────────────────────────────────────────
REACTIONS = ["👍", "❤️", "🔥", "🎉", "😍", "👏", "🤩", "💯", "😂", "🥰"]

# ─── Telethon Client ─────────────────────────────────────────────
client = TelegramClient("bot_session", API_ID, API_HASH)


# ─── /start Command ──────────────────────────────────────────────
@client.on(events.NewMessage(pattern=r"^/start$"))
async def start_handler(event):
    sender     = await event.get_sender()
    first_name = getattr(sender, "first_name", "there") or "there"

    welcome_text = (
        f"👋 **Hey {first_name}! Welcome!**\n\n"
        f"🤖 Main hoon **{BOT_NAME}**\n\n"
        f"⚡ **Mera Kaam:**\n"
        f"› Har group/channel message pe automatically react karta hoon\n"
        f"› Random emojis use karta hoon: 👍 ❤️ 🔥 🎉 😍 👏 🤩 💯 😂 🥰\n\n"
        f"📌 **Use karne ke liye:**\n"
        f"1️⃣ Mujhe apne group/channel me add karo\n"
        f"2️⃣ Admin banao (reactions permission do)\n"
        f"3️⃣ Ho gaya! Main khud react karta rahunga 🎉\n\n"
        f"⬇️ Niche button se seedha add karo!"
    )

    buttons = []
    if BOT_USERNAME:
        buttons = [[
            Button.url("➕ Add to Group",   f"https://t.me/{BOT_USERNAME}?startgroup=true"),
            Button.url("📢 Add to Channel", f"https://t.me/{BOT_USERNAME}?startchannel=true"),
        ]]

    await event.respond(welcome_text, buttons=buttons if buttons else None)
    logger.info(f"/start by user {event.sender_id}")


# ─── Auto Reaction Handler ───────────────────────────────────────
@client.on(events.NewMessage())
async def auto_react(event):
    # Skip commands
    if event.message.text and event.message.text.startswith("/"):
        return

    try:
        chat      = await event.get_chat()
        is_group  = getattr(chat, "megagroup", False)
        is_chan   = getattr(chat, "broadcast", False)
        is_small  = type(chat).__name__ == "Chat"

        if not (is_group or is_chan or is_small):
            return

        emoji = random.choice(REACTIONS)
        await client(SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.message.id,
            reaction=[ReactionEmoji(emoticon=emoji)],
        ))
        logger.info(f"Reacted {emoji} | msg={event.message.id} | chat={event.chat_id}")

    except Exception as e:
        logger.debug(f"Reaction skip (chat={event.chat_id}): {e}")


# ─── Health Check Server ─────────────────────────────────────────
async def health_handler(request):
    return web.Response(text="OK", status=200)


async def start_health_server():
    app = web.Application()
    app.router.add_get("/",       health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info(f"✅ Health server → http://0.0.0.0:{PORT}/health")


# ─── Main ────────────────────────────────────────────────────────
async def main():
    await start_health_server()
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    logger.info(f"🤖 Running: @{me.username} | {BOT_NAME} | port={PORT}")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
