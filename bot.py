import os
import logging
import asyncio
import random
from aiohttp import web
from telethon import TelegramClient, events
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji, Channel, Chat

# ─── Logging Setup ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Config from Environment ─────────────────────────────────────
API_ID    = int(os.environ["API_ID"])
API_HASH  = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
PORT      = int(os.environ.get("PORT", 8080))

# ─── Reactions Pool ──────────────────────────────────────────────
REACTIONS = ["👍", "❤️", "🔥", "🎉", "😍", "👏", "🤩", "💯", "😂", "🥰"]

# ─── Telethon Client ─────────────────────────────────────────────
client = TelegramClient("bot_session", API_ID, API_HASH)


# ─── Auto Reaction Handler ───────────────────────────────────────
@client.on(events.NewMessage())
async def auto_react(event):
    """React to every new message in groups and channels."""
    try:
        # Skip commands
        if event.message.text and event.message.text.startswith("/"):
            return

        chat = await event.get_chat()

        # FIX: Use proper Telethon type checks instead of __name__
        is_megagroup = isinstance(chat, Channel) and getattr(chat, "megagroup", False)
        is_broadcast = isinstance(chat, Channel) and getattr(chat, "broadcast", False)
        is_small_group = isinstance(chat, Chat)

        if not (is_megagroup or is_broadcast or is_small_group):
            return  # Skip private chats / unknown

        emoji = random.choice(REACTIONS)

        await client(SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.message.id,
            reaction=[ReactionEmoji(emoticon=emoji)],
        ))

        logger.info(
            f"Reacted {emoji} to msg {event.message.id} in chat {event.chat_id}"
        )

    except Exception as e:
        logger.debug(f"Could not react: {e}")


# ─── Health Check Server ──────────────────────────────────────────
async def health_handler(request):
    return web.Response(text="OK", status=200)


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health server running on port {PORT}")


# ─── Main Entry Point ─────────────────────────────────────────────
async def main():
    await start_health_server()
    await client.start(bot_token=BOT_TOKEN)
    logger.info("Bot started and listening for messages...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
