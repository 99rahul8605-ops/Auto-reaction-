import os
import asyncio
import logging
import random
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("MasterBot")

# ─── ENV ─────────────────────────────────────────────────────────
API_ID      = int(os.environ["API_ID"])
API_HASH    = os.environ["API_HASH"]
MASTER_TOKEN = os.environ["MASTER_BOT_TOKEN"]
MASTER_USERNAME = os.environ.get("MASTER_BOT_USERNAME", "")
MONGO_URI   = os.environ["MONGO_URI"]
PORT        = int(os.environ.get("PORT", 8080))

REACTIONS = ["👍", "❤️", "🔥", "🎉", "😍", "👏", "🤩", "💯", "😂", "🥰"]

# ─── MongoDB ─────────────────────────────────────────────────────
mongo_client = AsyncIOMotorClient(MONGO_URI)
db           = mongo_client["reaction_saas"]
bots_col     = db["bots"]        # registered bot tokens
workers: dict[str, TelegramClient] = {}  # token → running client


# ─── Worker Bot (cloned logic) ───────────────────────────────────
async def start_worker(token: str, username: str, name: str):
    if token in workers:
        return  # already running

    client = TelegramClient(f"sessions/worker_{token[:10]}", API_ID, API_HASH)

    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def start_cmd(event):
        sender     = await event.get_sender()
        first_name = getattr(sender, "first_name", "there") or "there"
        text = (
            f"👋 **Hey {first_name}! Welcome!**\n\n"
            f"🤖 Main hoon **{name}**\n\n"
            f"⚡ Har group/channel message pe automatically react karta hoon!\n"
            f"Random emojis: 👍 ❤️ 🔥 🎉 😍 👏 🤩 💯 😂 🥰\n\n"
            f"📌 **Use karne ke liye:**\n"
            f"1️⃣ Group/channel me add karo\n"
            f"2️⃣ Admin banao\n"
            f"3️⃣ Ho gaya! 🎉"
        )
        buttons = None
        if username:
            buttons = [[
                Button.url("➕ Add to Group",   f"https://t.me/{username}?startgroup=true"),
                Button.url("📢 Add to Channel", f"https://t.me/{username}?startchannel=true"),
            ]]
        await event.respond(text, buttons=buttons)

    @client.on(events.NewMessage())
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
            await client(SendReactionRequest(
                peer=event.chat_id,
                msg_id=event.message.id,
                reaction=[ReactionEmoji(emoticon=emoji)],
            ))
            logger.info(f"[{name}] Reacted {emoji} | chat={event.chat_id}")
        except Exception as e:
            logger.debug(f"[{name}] Skip: {e}")

    try:
        await client.start(bot_token=token)
        me = await client.get_me()
        workers[token] = client
        logger.info(f"✅ Worker started: @{me.username} ({name})")
        asyncio.create_task(client.run_until_disconnected())
    except Exception as e:
        logger.error(f"❌ Worker failed ({name}): {e}")
        await client.disconnect()


async def stop_worker(token: str):
    client = workers.pop(token, None)
    if client:
        await client.disconnect()
        logger.info(f"🛑 Worker stopped for token ...{token[:10]}")


# ─── Master Bot ──────────────────────────────────────────────────
master = TelegramClient("sessions/master", API_ID, API_HASH)

# State: user_id → waiting for token input
waiting_for_token: set[int] = set()


@master.on(events.NewMessage(pattern=r"^/start$"))
async def master_start(event):
    sender     = await event.get_sender()
    first_name = getattr(sender, "first_name", "there") or "there"

    # Check if user already has a bot registered
    existing = await bots_col.find_one({"owner_id": event.sender_id})

    if existing:
        text = (
            f"👋 **Hey {first_name}!**\n\n"
            f"✅ Tumhara bot already registered hai:\n"
            f"🤖 **{existing['name']}** (@{existing['username'] or 'N/A'})\n\n"
            f"Manage karne ke liye niche buttons use karo:"
        )
        buttons = [[
            Button.inline("🗑 Bot Remove Karo", data=f"remove_{event.sender_id}"),
            Button.inline("📊 Status", data=f"status_{event.sender_id}"),
        ]]
    else:
        text = (
            f"👋 **Hey {first_name}! Welcome!**\n\n"
            f"🚀 **Reaction Bot SaaS**\n\n"
            f"Apna bot register karo aur wo automatically har\n"
            f"group/channel message pe react karega!\n\n"
            f"📌 **Kaise kaam karta hai:**\n"
            f"1️⃣ @BotFather se apna bot banao\n"
            f"2️⃣ Bot token yahan submit karo\n"
            f"3️⃣ Apne bot ko group/channel me add karo\n"
            f"4️⃣ Admin banao — bas! 🎉\n\n"
            f"⬇️ Shuru karo:"
        )
        buttons = [[Button.inline("➕ Apna Bot Register Karo", data="register")]]

    await event.respond(text, buttons=buttons)


@master.on(events.CallbackQuery(data="register"))
async def ask_for_token(event):
    waiting_for_token.add(event.sender_id)
    await event.respond(
        "🔑 **Apna BotFather token paste karo:**\n\n"
        "Token aisa dikhta hai:\n`123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxx`\n\n"
        "❌ Cancel karna ho to /cancel bhejo"
    )
    await event.answer()


@master.on(events.NewMessage(pattern=r"^/cancel$"))
async def cancel_registration(event):
    waiting_for_token.discard(event.sender_id)
    await event.respond("❌ Registration cancel ho gaya.")


@master.on(events.NewMessage())
async def handle_token_input(event):
    if event.sender_id not in waiting_for_token:
        return
    if not event.message.text or event.message.text.startswith("/"):
        return

    token = event.message.text.strip()
    waiting_for_token.discard(event.sender_id)

    # Basic token format check
    if ":" not in token or len(token) < 30:
        await event.respond("❌ Token format galat hai. Dobara try karo /start se.")
        return

    # Check if token already registered
    existing = await bots_col.find_one({"token": token})
    if existing:
        await event.respond("⚠️ Ye token already registered hai!")
        return

    await event.respond("⏳ Token verify ho raha hai...")

    # Verify token by trying to get bot info
    try:
        test_client = TelegramClient(f"sessions/test_{token[:10]}", API_ID, API_HASH)
        await test_client.start(bot_token=token)
        me = await test_client.get_me()
        bot_username = me.username or ""
        bot_name     = me.first_name or "My Bot"
        await test_client.disconnect()
    except Exception as e:
        await event.respond(f"❌ Token invalid hai ya bot start nahi hua.\n\nError: `{e}`")
        return

    # Save to MongoDB
    await bots_col.insert_one({
        "owner_id": event.sender_id,
        "token":    token,
        "username": bot_username,
        "name":     bot_name,
        "active":   True,
    })

    # Start worker
    await start_worker(token, bot_username, bot_name)

    await event.respond(
        f"✅ **Bot successfully registered!**\n\n"
        f"🤖 **{bot_name}** (@{bot_username})\n\n"
        f"Ab apne bot ko group/channel me add karo aur admin banao!\n\n"
        f"Bot automatically react karna shuru kar dega 🎉",
        buttons=[[
            Button.url(f"➕ @{bot_username} ko Add Karo", f"https://t.me/{bot_username}?startgroup=true"),
        ]] if bot_username else None
    )


@master.on(events.CallbackQuery(pattern=rb"^remove_(\d+)$"))
async def remove_bot(event):
    owner_id = int(event.data.decode().split("_")[1])
    if event.sender_id != owner_id:
        await event.answer("❌ Ye tumhara bot nahi hai!", alert=True)
        return

    doc = await bots_col.find_one({"owner_id": owner_id})
    if not doc:
        await event.answer("Koi bot registered nahi hai.", alert=True)
        return

    await stop_worker(doc["token"])
    await bots_col.delete_one({"owner_id": owner_id})
    await event.edit("🗑 **Bot remove ho gaya!**\n\nDobara add karne ke liye /start karo.")


@master.on(events.CallbackQuery(pattern=rb"^status_(\d+)$"))
async def bot_status(event):
    owner_id = int(event.data.decode().split("_")[1])
    doc = await bots_col.find_one({"owner_id": owner_id})
    if not doc:
        await event.answer("Koi bot nahi mila.", alert=True)
        return

    is_running = doc["token"] in workers
    status     = "🟢 Running" if is_running else "🔴 Stopped"

    await event.answer(
        f"Bot: @{doc['username']}\nStatus: {status}",
        alert=True
    )


# ─── Health Server ───────────────────────────────────────────────
async def health_handler(req):
    return web.Response(text=f"OK | Workers: {len(workers)}", status=200)


async def start_health_server():
    app = web.Application()
    app.router.add_get("/",       health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info(f"✅ Health → http://0.0.0.0:{PORT}/health")


# ─── Main ────────────────────────────────────────────────────────
async def main():
    os.makedirs("sessions", exist_ok=True)

    await start_health_server()

    # Load all active bots from MongoDB and start workers
    async for doc in bots_col.find({"active": True}):
        logger.info(f"🔄 Restoring worker: {doc['name']}")
        await start_worker(doc["token"], doc["username"], doc["name"])

    await master.start(bot_token=MASTER_TOKEN)
    me = await master.get_me()
    logger.info(f"🤖 Master bot started: @{me.username}")

    await master.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
