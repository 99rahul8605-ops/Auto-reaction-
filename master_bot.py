import os
import asyncio
import logging
import random
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.tl.functions.messages import SendReactionRequest, SendMessageRequest
from telethon.tl.types import ReactionEmoji, Channel, Chat
from motor.motor_asyncio import AsyncIOMotorClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("MasterBot")

# ─── ENV ─────────────────────────────────────────────────────────
API_ID          = int(os.environ["API_ID"])
API_HASH        = os.environ["API_HASH"]
MASTER_TOKEN    = os.environ["MASTER_BOT_TOKEN"]
MASTER_USERNAME = os.environ.get("MASTER_BOT_USERNAME", "")
MONGO_URI       = os.environ["MONGO_URI"]
PORT            = int(os.environ.get("PORT", 8080))

REACTIONS = ["👍", "❤", "🔥", "🎉", "😍", "👏", "🤩", "💯", "😂", "🥰"]

# ─── Message Effects (Telegram effect_id list) ───────────────────
# Ye wahi effects hain jo hold karke bhejte hain
EFFECTS = [
    5104841245755180586,   # 🔥 Fire
    5046509860389126442,   # 👍 Thumbs up
    5107584321108051014,   # 🎉 Party / Confetti
    5044134455711629726,   # ❤ Heart
    5027712690068940800,   # 💩 Poop (funny)
    5083162785249204200,   # 🎊 Balloons
]

# Reaction → matching effect (jab ho sake toh matching bhejo)
REACTION_EFFECT_MAP = {
    "👍": 5046509860389126442,
    "❤":  5044134455711629726,
    "🔥": 5104841245755180586,
    "🎉": 5107584321108051014,
    "😂": 5027712690068940800,
    "🥰": 5044134455711629726,
    "👏": 5046509860389126442,
    "🤩": 5107584321108051014,
    "💯": 5083162785249204200,
    "😍": 5044134455711629726,
}

# ─── MongoDB ─────────────────────────────────────────────────────
mongo_client = AsyncIOMotorClient(MONGO_URI)
db           = mongo_client["reaction_saas"]
bots_col     = db["bots"]
workers: dict[str, TelegramClient] = {}


# ─── Core reaction + effect logic ────────────────────────────────
async def do_react(worker_client, event, name):
    try:
        # Commands skip
        if event.message.text and event.message.text.startswith("/"):
            return

        chat = await event.get_chat()

        # FIX: Ab private chat (User) bhi allowed — sirf bots skip karo
        from telethon.tl.types import User
        is_megagroup   = isinstance(chat, Channel) and getattr(chat, "megagroup", False)
        is_broadcast   = isinstance(chat, Channel) and getattr(chat, "broadcast", False)
        is_small_group = isinstance(chat, Chat)
        is_private     = isinstance(chat, User) and not getattr(chat, "bot", False)

        if not (is_megagroup or is_broadcast or is_small_group or is_private):
            return  # Sirf bots ke DM skip

        emoji = random.choice(REACTIONS)

        # Step 1: Reaction do
        await worker_client(SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.message.id,
            reaction=[ReactionEmoji(emoticon=emoji)],
        ))
        logger.info(f"[{name}] ✅ Reacted {emoji} | chat={event.chat_id}")

        # Step 2: Effect ke saath reply karo (matching effect if available)
        effect_id = REACTION_EFFECT_MAP.get(emoji, random.choice(EFFECTS))

        await worker_client(SendMessageRequest(
            peer=event.chat_id,
            message=emoji,
            effect=effect_id,
            reply_to_msg_id=event.message.id,
            no_webpage=True,
        ))
        logger.info(f"[{name}] ✨ Sent effect reply | effect={effect_id}")

    except Exception as e:
        logger.error(f"[{name}] ❌ Failed: {e}")


# ─── Worker Bot ──────────────────────────────────────────────────
async def start_worker(token: str, username: str, name: str):
    if token in workers:
        return

    worker_client = TelegramClient(
        f"sessions/worker_{token[:10]}",
        API_ID,
        API_HASH,
        connection_retries=5,
        retry_delay=1,
        flood_sleep_threshold=10,
    )

    @worker_client.on(events.NewMessage(pattern=r"^/start$"))
    async def start_cmd(event):
        sender     = await event.get_sender()
        first_name = getattr(sender, "first_name", "there") or "there"
        text = (
            f"👋 **Hey {first_name}! Welcome!**\n\n"
            f"🤖 Main hoon **{name}**\n\n"
            f"⚡ Har group/channel/DM message pe automatically react karta hoon!\n"
            f"Random emojis: 👍 ❤ 🔥 🎉 😍 👏 🤩 💯 😂 🥰\n\n"
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

    @worker_client.on(events.NewMessage())
    async def auto_react(event):
        # Apna hi message ignore karo
        if event.out:
            return
        asyncio.create_task(do_react(worker_client, event, name))

    try:
        await worker_client.start(bot_token=token)
        me = await worker_client.get_me()
        workers[token] = worker_client
        logger.info(f"✅ Worker started: @{me.username} ({name})")
        asyncio.create_task(worker_client.run_until_disconnected())
    except Exception as e:
        logger.error(f"❌ Worker failed ({name}): {e}")
        await worker_client.disconnect()


async def stop_worker(token: str):
    worker_client = workers.pop(token, None)
    if worker_client:
        await worker_client.disconnect()
        logger.info(f"🛑 Worker stopped: ...{token[:10]}")


# ─── Master Bot ──────────────────────────────────────────────────
master = TelegramClient("sessions/master", API_ID, API_HASH)

waiting_for_token: set[int] = set()


async def show_my_bots(event, edit=False):
    sender_id  = event.sender_id
    sender     = await event.get_sender()
    first_name = getattr(sender, "first_name", "there") or "there"

    user_bots = await bots_col.find({"owner_id": sender_id}).to_list(length=50)

    if user_bots:
        lines = [f"👋 **Hey {first_name}!**\n\n📋 **Tumhare registered bots ({len(user_bots)}):**\n"]
        for i, doc in enumerate(user_bots, 1):
            status = "🟢" if doc["token"] in workers else "🔴"
            lines.append(f"{i}. {status} **{doc['name']}** (@{doc['username'] or 'N/A'})")
        lines.append("\n⬇️ Manage karo ya naya bot add karo:")
        text = "\n".join(lines)

        bot_buttons = []
        for doc in user_bots:
            short = doc["username"] or doc["name"]
            bot_buttons.append([
                Button.inline(f"🗑 Remove @{short}", data=f"remove_{doc['token'][:20]}")
            ])
        bot_buttons.append([Button.inline("➕ Naya Bot Add Karo", data="register")])
        buttons = bot_buttons
    else:
        text = (
            f"👋 **Hey {first_name}! Welcome!**\n\n"
            f"🚀 **Reaction Bot SaaS**\n\n"
            f"Apna bot register karo aur wo automatically har\n"
            f"group/channel/DM message pe react karega!\n\n"
            f"📌 **Kaise kaam karta hai:**\n"
            f"1️⃣ @BotFather se apna bot banao\n"
            f"2️⃣ Bot token yahan submit karo\n"
            f"3️⃣ Apne bot ko group/channel me add karo\n"
            f"4️⃣ Admin banao — bas! 🎉\n\n"
            f"⬇️ Shuru karo:"
        )
        buttons = [[Button.inline("➕ Apna Bot Register Karo", data="register")]]

    if edit:
        await event.edit(text, buttons=buttons)
    else:
        await event.respond(text, buttons=buttons)


@master.on(events.NewMessage(pattern=r"^/start$"))
async def master_start(event):
    await show_my_bots(event)


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

    if ":" not in token or len(token) < 30:
        await event.respond("❌ Token format galat hai. Dobara try karo /start se.")
        return

    existing = await bots_col.find_one({"token": token})
    if existing:
        await event.respond("⚠️ Ye token already registered hai!")
        return

    await event.respond("⏳ Token verify ho raha hai...")

    try:
        test_client = TelegramClient(f"sessions/test_{token[:10]}", API_ID, API_HASH)
        await test_client.start(bot_token=token)
        me           = await test_client.get_me()
        bot_username = me.username or ""
        bot_name     = me.first_name or "My Bot"
        await test_client.disconnect()
    except Exception as e:
        await event.respond(f"❌ Token invalid hai ya bot start nahi hua.\n\nError: `{e}`")
        return

    await bots_col.insert_one({
        "owner_id": event.sender_id,
        "token":    token,
        "username": bot_username,
        "name":     bot_name,
        "active":   True,
    })

    await start_worker(token, bot_username, bot_name)

    await event.respond(
        f"✅ **Bot successfully registered!**\n\n"
        f"🤖 **{bot_name}** (@{bot_username})\n\n"
        f"Ab apne bot ko group/channel me add karo aur admin banao!\n\n"
        f"Bot automatically react karna shuru kar dega 🎉\n\n"
        f"💡 Aur bots add karne ke liye /start karo.",
        buttons=[[
            Button.url(f"➕ @{bot_username} ko Add Karo", f"https://t.me/{bot_username}?startgroup=true"),
        ]] if bot_username else None
    )


@master.on(events.CallbackQuery(pattern=rb"^remove_(.+)$"))
async def remove_bot(event):
    token_prefix = event.data.decode().split("_", 1)[1]

    doc = await bots_col.find_one({
        "token":    {"$regex": f"^{token_prefix}"},
        "owner_id": event.sender_id,
    })

    if not doc:
        await event.answer("❌ Bot nahi mila ya ye tumhara nahi hai!", alert=True)
        return

    await stop_worker(doc["token"])
    await bots_col.delete_one({"_id": doc["_id"]})
    await event.answer(f"🗑 @{doc['username']} remove ho gaya!", alert=True)
    await show_my_bots(event, edit=True)


@master.on(events.NewMessage(pattern=r"^/mybots$"))
async def my_bots_cmd(event):
    await show_my_bots(event)


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

    tasks = []
    async for doc in bots_col.find({"active": True}):
        logger.info(f"🔄 Restoring worker: {doc['name']}")
        tasks.append(start_worker(doc["token"], doc["username"], doc["name"]))

    if tasks:
        await asyncio.gather(*tasks)

    await master.start(bot_token=MASTER_TOKEN)
    me = await master.get_me()
    logger.info(f"🤖 Master bot started: @{me.username}")

    await master.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
