#!/usr/bin/env python3
"""
Multi-Bot Launcher
──────────────────
Ek script se multiple Telegram bots chalao.
Har bot ka apna BOT_TOKEN, PORT, BOT_NAME hoga.

Usage:
    python launch_bots.py

Config:
    BOTS list me apne bots add karo (niche dekho).
"""

import os
import asyncio
import logging
import random
import signal
import sys
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)

REACTIONS = ["👍", "❤️", "🔥", "🎉", "😍", "👏", "🤩", "💯", "😂", "🥰"]

# ─────────────────────────────────────────────────────────────────
# ✏️  APNE BOTS YAHAN ADD KARO
# Har dict me: BOT_TOKEN, PORT (alag alag), BOT_NAME, BOT_USERNAME
# ─────────────────────────────────────────────────────────────────
BOTS = [
    {
        "BOT_TOKEN":    os.environ.get("BOT_TOKEN_1", ""),
        "BOT_NAME":     os.environ.get("BOT_NAME_1",  "Reaction Bot 1"),
        "BOT_USERNAME": os.environ.get("BOT_USERNAME_1", ""),
        "PORT":         int(os.environ.get("PORT_1", 8081)),
    },
    {
        "BOT_TOKEN":    os.environ.get("BOT_TOKEN_2", ""),
        "BOT_NAME":     os.environ.get("BOT_NAME_2",  "Reaction Bot 2"),
        "BOT_USERNAME": os.environ.get("BOT_USERNAME_2", ""),
        "PORT":         int(os.environ.get("PORT_2", 8082)),
    },
    # ─── Aur bots add karne ke liye bas copy-paste karo ───
    # {
    #     "BOT_TOKEN":    os.environ.get("BOT_TOKEN_3", ""),
    #     "BOT_NAME":     os.environ.get("BOT_NAME_3",  "Reaction Bot 3"),
    #     "BOT_USERNAME": os.environ.get("BOT_USERNAME_3", ""),
    #     "PORT":         int(os.environ.get("PORT_3", 8083)),
    # },
]

# Shared API credentials (same for all bots)
API_ID   = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]


# ─── Bot Class ───────────────────────────────────────────────────
class ReactionBot:
    def __init__(self, config: dict, index: int):
        self.token    = config["BOT_TOKEN"]
        self.name     = config["BOT_NAME"]
        self.username = config["BOT_USERNAME"]
        self.port     = config["PORT"]
        self.index    = index
        self.logger   = logging.getLogger(f"Bot{index+1}:{self.name}")

        self.client = TelegramClient(
            f"bot_session_{index}",  # unique session file per bot
            API_ID,
            API_HASH,
        )
        self._register_handlers()

    def _register_handlers(self):
        # /start handler
        @self.client.on(events.NewMessage(pattern=r"^/start$"))
        async def start_handler(event):
            sender     = await event.get_sender()
            first_name = getattr(sender, "first_name", "there") or "there"

            welcome_text = (
                f"👋 **Hey {first_name}! Welcome!**\n\n"
                f"🤖 Main hoon **{self.name}**\n\n"
                f"⚡ **Mera Kaam:**\n"
                f"› Har group/channel message pe automatically react karta hoon\n"
                f"› Random emojis: 👍 ❤️ 🔥 🎉 😍 👏 🤩 💯 😂 🥰\n\n"
                f"📌 **Use karne ke liye:**\n"
                f"1️⃣ Mujhe group/channel me add karo\n"
                f"2️⃣ Admin banao\n"
                f"3️⃣ Ho gaya! 🎉\n\n"
                f"⬇️ Niche button se add karo!"
            )

            buttons = []
            if self.username:
                buttons = [[
                    Button.url("➕ Add to Group",   f"https://t.me/{self.username}?startgroup=true"),
                    Button.url("📢 Add to Channel", f"https://t.me/{self.username}?startchannel=true"),
                ]]

            await event.respond(welcome_text, buttons=buttons if buttons else None)
            self.logger.info(f"/start by {event.sender_id}")

        # Auto reaction handler
        @self.client.on(events.NewMessage())
        async def auto_react(event):
            if event.message.text and event.message.text.startswith("/"):
                return
            try:
                chat     = await event.get_chat()
                is_group = getattr(chat, "megagroup", False)
                is_chan  = getattr(chat, "broadcast", False)
                is_small = type(chat).__name__ == "Chat"

                if not (is_group or is_chan or is_small):
                    return

                emoji = random.choice(REACTIONS)
                await self.client(SendReactionRequest(
                    peer=event.chat_id,
                    msg_id=event.message.id,
                    reaction=[ReactionEmoji(emoticon=emoji)],
                ))
                self.logger.info(f"Reacted {emoji} | msg={event.message.id} | chat={event.chat_id}")

            except Exception as e:
                self.logger.debug(f"Reaction skip: {e}")

    async def start_health_server(self):
        async def health_handler(request):
            return web.Response(text=f"{self.name} OK", status=200)

        app = web.Application()
        app.router.add_get("/",       health_handler)
        app.router.add_get("/health", health_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", self.port).start()
        self.logger.info(f"✅ Health → http://0.0.0.0:{self.port}/health")

    async def run(self):
        if not self.token:
            self.logger.warning("⚠️  BOT_TOKEN missing — skipping this bot")
            return

        await self.start_health_server()
        await self.client.start(bot_token=self.token)
        me = await self.client.get_me()
        self.logger.info(f"🤖 Started: @{me.username}")
        await self.client.run_until_disconnected()


# ─── Launch All ──────────────────────────────────────────────────
async def launch_all():
    bots = [ReactionBot(cfg, i) for i, cfg in enumerate(BOTS)]

    tasks = [asyncio.create_task(b.run()) for b in bots]
    logging.getLogger("Launcher").info(f"🚀 Launching {len(bots)} bot(s)...")

    # Graceful shutdown on Ctrl+C / SIGTERM
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: [t.cancel() for t in tasks])

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        logging.getLogger("Launcher").info("🛑 All bots stopped.")


if __name__ == "__main__":
    asyncio.run(launch_all())
