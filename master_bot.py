import os
import asyncio
import logging
import random
from aiohttp import web
from telethon import TelegramClient, events, Button
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji, Channel, Chat, User
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

# ─── OWNER ID — sirf ye use kar sakta hai ────────────────────────
# Apna Telegram user ID yahan daalo (integer)
# Pata karne ke liye @userinfobot pe /start bhejo
OWNER_ID = int(os.environ["OWNER_ID"])

REACTIONS = ["👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱", "🤬", "😢", "🎉", "🤩", "🤮", "💩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴", "😍", "🐳", "❤‍🔥", "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆", "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈", "😴", "😭", "🤓", "👻", "👨‍💻", "👀", "🎃", "🙈", "😇", "😂"]

# ─── MongoDB ─────────────────────────────────────────────────────
mongo_client = AsyncIOMotorClient(MONGO_URI)
db           = mongo_client["reaction_saas"]
bots_col     = db["bots"]
users_col    = db["users"]   # har bot ke users track karne ke liye
workers: dict[str, TelegramClient] = {}

# broadcast state
waiting_for_broadcast: bool = False


# ─── Owner check decorator ────────────────────────────────────────
def owner_only(func):
    async def wrapper(event, *args, **kwargs):
        if event.sender_id != OWNER_ID:
            await event.respond("🚫 **Ye bot sirf owner ke liye hai!**")
            logger.warning(f"Unauthorized access attempt by user_id={event.sender_id}")
            return
        return await func(event, *args, **kwargs)
    return wrapper





# ─── Core reaction logic ──────────────────────────────────────────
SAFE_REACTIONS = ["👍", "❤", "🔥", "🎉", "😂"]

# Per-chat allowed reactions cache
_reaction_cache: dict = {}


async def get_allowed_reactions(worker_client, chat, chat_id):
    if chat_id in _reaction_cache:
        return _reaction_cache[chat_id]

    allowed = []
    try:
        from telethon.tl.functions.channels import GetFullChannelRequest
        from telethon.tl.functions.messages import GetFullChatRequest
        from telethon.tl.types import (
            ChatReactionsAll, ChatReactionsSome, ChatReactionsNone,
            ReactionEmoji as RE,
        )

        if isinstance(chat, Channel):
            full      = await worker_client(GetFullChannelRequest(chat))
            available = full.full_chat.available_reactions
        elif isinstance(chat, Chat):
            full      = await worker_client(GetFullChatRequest(chat.id))
            available = full.full_chat.available_reactions
        else:
            _reaction_cache[chat_id] = REACTIONS
            return REACTIONS

        if isinstance(available, ChatReactionsAll):
            allowed = REACTIONS
        elif isinstance(available, ChatReactionsNone):
            allowed = []
        elif isinstance(available, ChatReactionsSome):
            allowed = [r.emoticon for r in available.reactions if isinstance(r, RE)]
        else:
            allowed = SAFE_REACTIONS

    except Exception as e:
        logger.debug(f"Could not fetch reactions for {chat_id}: {e}")
        allowed = SAFE_REACTIONS

    _reaction_cache[chat_id] = allowed
    return allowed


async def do_react(worker_client, event, name):
    try:
        if event.message.text and event.message.text.startswith("/"):
            return

        chat = await event.get_chat()

        is_megagroup   = isinstance(chat, Channel) and getattr(chat, "megagroup", False)
        is_broadcast   = isinstance(chat, Channel) and getattr(chat, "broadcast", False)
        is_small_group = isinstance(chat, Chat)
        is_private     = isinstance(chat, User) and not getattr(chat, "bot", False)

        if not (is_megagroup or is_broadcast or is_small_group or is_private):
            return

        allowed = await get_allowed_reactions(worker_client, chat, event.chat_id)

        if not allowed:
            logger.debug(f"[{name}] Reactions disabled | chat={event.chat_id}")
            return

        emoji = random.choice(allowed)

        await worker_client(SendReactionRequest(
            peer=event.chat_id,
            msg_id=event.message.id,
            reaction=[ReactionEmoji(emoticon=emoji)],
        ))
        logger.info(f"[{name}] Reacted {emoji} | chat={event.chat_id}")

    except Exception as e:
        logger.error(f"[{name}] Failed: {e}")

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

        # User ko DB mein save karo (upsert — duplicate nahi banega)
        await users_col.update_one(
            {"bot_token": token, "user_id": event.sender_id},
            {"$set": {"user_id": event.sender_id, "bot_token": token, "bot_name": name}},
            upsert=True,
        )

        caption = (
            "**Aᴜᴛᴏ Rᴇᴀᴄᴛɪᴏɴ Bᴏᴛ**\n\n"
            "𖣘 I Aᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ Rᴇᴀᴄᴛ Tᴏ Eᴠᴇʀʏ Nᴇᴡ Pᴏꜱᴛ Iɴ Yᴏᴜʀ Cʜᴀɴɴᴇʟ Wɪᴛʜ Eᴍᴏᴊɪꜱ.\n\n"
            "**Hᴏᴡ Tᴏ Uꜱᴇ:**\n"
            "➜ 1. Mᴀᴋᴇ Mᴇ Aᴅᴍɪɴ Iɴ Yᴏᴜʀ Cʜᴀɴɴᴇʟ\n"
            "➜ 2. Pᴏꜱᴛ A Mᴇꜱꜱᴀɢᴇ Iɴ Yᴏᴜʀ Cʜᴀɴɴᴇʟ"
        )
        buttons = []
        if username:
            buttons.append([
                Button.url("➕ Add to Group",   f"https://t.me/{username}?startgroup=true"),
                Button.url("📢 Add to Channel", f"https://t.me/{username}?startchannel=true"),
            ])
        buttons.append([
            Button.url("📣 Support Channel", "https://t.me/Bot_support_channell"),
        ])

        image_url = "https://ibb.co/qQNn0YX"
        try:
            async with worker_client.action(event.chat_id, "typing"):
                pass
            await worker_client.send_file(
                event.chat_id,
                file=image_url,
                caption=caption,
                buttons=buttons,
            )
        except Exception:
            # Image load na ho to sirf text bhejo
            await event.respond(caption, buttons=buttons)

    @worker_client.on(events.NewMessage())
    async def auto_react(event):
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

waiting_for_token: bool = False


async def show_my_bots(event, edit=False):
    user_bots = await bots_col.find({"owner_id": OWNER_ID}).to_list(length=50)

    if user_bots:
        lines = [f"📋 **Registered Bots ({len(user_bots)}):**\n"]
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
            f"👋 **Welcome Owner!**\n\n"
            f"🚀 Koi bot registered nahi hai abhi.\n\n"
            f"📌 **Kaise kaam karta hai:**\n"
            f"1️⃣ @BotFather se apna bot banao\n"
            f"2️⃣ Bot token yahan submit karo\n"
            f"3️⃣ Apne bot ko group/channel me add karo\n"
            f"4️⃣ Admin banao — bas! 🎉"
        )
        buttons = [
            [Button.inline("➕ Bot Register Karo", data="register")],
            [Button.url("📣 Support Channel", "https://t.me/Bot_support_channell")],
        ]

    if edit:
        await event.edit(text, buttons=buttons)
    else:
        await event.respond(text, buttons=buttons)


@master.on(events.NewMessage(pattern=r"^/start$"))
@owner_only
async def master_start(event):
    await show_my_bots(event)


@master.on(events.NewMessage(pattern=r"^/mybots$"))
@owner_only
async def my_bots_cmd(event):
    await show_my_bots(event)


@master.on(events.CallbackQuery(data="register"))
async def ask_for_token(event):
    if event.sender_id != OWNER_ID:
        await event.answer("🚫 Unauthorized!", alert=True)
        return
    global waiting_for_token
    waiting_for_token = True
    await event.respond(
        "🔑 **BotFather token paste karo:**\n\n"
        "Token aisa dikhta hai:\n`123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxx`\n\n"
        "❌ Cancel karna ho to /cancel bhejo"
    )
    await event.answer()


@master.on(events.NewMessage(pattern=r"^/cancel$"))
@owner_only
async def cancel_registration(event):
    global waiting_for_token
    waiting_for_token = False
    await event.respond("❌ Registration cancel ho gaya.")


@master.on(events.NewMessage())
async def handle_token_input(event):
    global waiting_for_token
    if event.sender_id != OWNER_ID:
        await event.respond("🚫 **Ye bot sirf owner ke liye hai!**")
        return
    if not waiting_for_token:
        return
    if waiting_for_broadcast:  # broadcast mode me token input ignore karo
        return
    if not event.message.text or event.message.text.startswith("/"):
        return

    token = event.message.text.strip()
    waiting_for_token = False

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
        "owner_id": OWNER_ID,
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
        f"Bot automatically react karna shuru kar dega 🎉",
        buttons=[[
            Button.url(f"➕ @{bot_username} ko Add Karo", f"https://t.me/{bot_username}?startgroup=true"),
        ]] if bot_username else None
    )


@master.on(events.CallbackQuery(pattern=rb"^remove_(.+)$"))
async def remove_bot(event):
    if event.sender_id != OWNER_ID:
        await event.answer("🚫 Unauthorized!", alert=True)
        return

    token_prefix = event.data.decode().split("_", 1)[1]
    doc = await bots_col.find_one({
        "token":    {"$regex": f"^{token_prefix}"},
        "owner_id": OWNER_ID,
    })

    if not doc:
        await event.answer("❌ Bot nahi mila!", alert=True)
        return

    await stop_worker(doc["token"])
    await bots_col.delete_one({"_id": doc["_id"]})
    await event.answer(f"🗑 @{doc['username']} remove ho gaya!", alert=True)
    await show_my_bots(event, edit=True)



# ─── Broadcast ───────────────────────────────────────────────────
@master.on(events.NewMessage(pattern=r"^/broadcast$"))
@owner_only
async def broadcast_cmd(event):
    global waiting_for_broadcast
    waiting_for_broadcast = True
    await event.respond(
        "📢 **Broadcast Message Bhejo:**\n\n"
        "Ab jo bhi message bhejoge wo saare registered bots apne apne users ko bhejenge.\n\n"
        "Text, photo, video — kuch bhi bhej sakte ho.\n"
        "❌ Cancel: /cancel"
    )


@master.on(events.NewMessage())
async def handle_broadcast_input(event):
    global waiting_for_broadcast
    if event.sender_id != OWNER_ID:
        return
    if not waiting_for_broadcast:
        return
    if waiting_for_token:  # token input mode me broadcast ignore karo
        return
    if event.message.text and event.message.text.startswith("/"):
        return

    waiting_for_broadcast = False

    # Saare active bots fetch karo
    all_bots = await bots_col.find({"active": True}).to_list(length=500)
    if not all_bots:
        await event.respond("⚠️ Koi bot registered nahi hai.")
        return

    status_msg = await event.respond("⏳ Broadcast shuru ho raha hai...")

    total_sent    = 0
    total_failed  = 0
    total_blocked = 0

    for bot_doc in all_bots:
        token = bot_doc["token"]
        worker_client = workers.get(token)
        if not worker_client:
            continue

        # Us bot ke saare users fetch karo
        bot_users = await users_col.find({"bot_token": token}).to_list(length=10000)
        if not bot_users:
            continue

        for user_doc in bot_users:
            try:
                await worker_client.forward_messages(
                    entity=user_doc["user_id"],
                    messages=event.message.id,
                    from_peer=event.chat_id,
                )
                total_sent += 1
            except Exception as e:
                err = str(e).lower()
                if "blocked" in err or "user is deactivated" in err or "forbidden" in err:
                    total_blocked += 1
                    # Block kiya hua user remove karo DB se
                    await users_col.delete_one({"_id": user_doc["_id"]})
                else:
                    total_failed += 1
                    logger.debug(f"Broadcast failed for {user_doc['user_id']}: {e}")

            # Flood avoid karne ke liye thoda wait
            await asyncio.sleep(0.05)

    await status_msg.edit(
        f"✅ **Broadcast Complete!**\n\n"
        f"📤 Sent: {total_sent}\n"
        f"🚫 Blocked/Removed: {total_blocked}\n"
        f"❌ Failed: {total_failed}"
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

    tasks = []
    async for doc in bots_col.find({"active": True}):
        logger.info(f"🔄 Restoring worker: {doc['name']}")
        tasks.append(start_worker(doc["token"], doc["username"], doc["name"]))

    if tasks:
        await asyncio.gather(*tasks)

    await master.start(bot_token=MASTER_TOKEN)
    me = await master.get_me()
    logger.info(f"🤖 Master bot started: @{me.username} | Owner: {OWNER_ID}")

    await master.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
