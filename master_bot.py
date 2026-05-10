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
API_ID           = int(os.environ["API_ID"])
API_HASH         = os.environ["API_HASH"]
MASTER_TOKEN     = os.environ["MASTER_BOT_TOKEN"]
MASTER_USERNAME  = os.environ.get("MASTER_BOT_USERNAME", "")
MONGO_URI        = os.environ["MONGO_URI"]
PORT             = int(os.environ.get("PORT", 8080))

REACTIONS = ["👍", "❤️", "🔥", "🎉", "😍", "👏", "🤩", "💯", "😂", "🥰"]

WELCOME_MSG = """Aᴜᴛᴏ Rᴇᴀᴄᴛɪᴏɴ Bᴏᴛ

𖣘 I Aᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ Rᴇᴀᴄᴛ Tᴏ Eᴠᴇʀʏ Nᴇᴡ Pᴏꜱᴛ Iɴ Yᴏᴜʀ Cʜᴀɴɴᴇʟ Wɪᴛʜ Eᴍᴏᴊɪꜱ.

Hᴏᴡ Tᴏ Uꜱᴇ:
➜ 1. Mᴀᴋᴇ Mᴇ Aᴅᴍɪɴ Iɴ Yᴏᴜʀ Cʜᴀɴɴᴇʟ
➜ 2. Pᴏꜱᴛ A Mᴇꜱꜱᴀɢᴇ Iɴ Yᴏᴜʀ Cʜᴀɴɴᴇʟ"""

# ─── MongoDB ─────────────────────────────────────────────────────
mongo_client = AsyncIOMotorClient(MONGO_URI)
db           = mongo_client["reaction_saas"]
bots_col     = db["bots"]
workers: dict[str, TelegramClient] = {}

waiting_for_token: set[int] = set()


# ─── Worker Bot ──────────────────────────────────────────────────
async def start_worker(token: str, username: str, name: str):
    if token in workers:
        return

    client = TelegramClient(f"sessions/worker_{token[:10]}", API_ID, API_HASH)

    # /start on worker bot
    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def start_cmd(event):
        sender     = await event.get_sender()
        first_name = getattr(sender, "first_name", "there") or "there"
        text = WELCOME_MSG
        buttons = None
        if username:
            buttons = [[
                Button.url("➕ Add To Group",   f"https://t.me/{username}?startgroup=true"),
                Button.url("📢 Add To Channel", f"https://t.me/{username}?startchannel=true"),
            ]]
        await event.respond(text, buttons=buttons)

    # FIX 1: Use event.is_group / event.is_channel — most reliable way
    @client.on(events.NewMessage(incoming=True))
    async def auto_react(event):
        if not event.is_group and not event.is_channel:
            return
        if event.message.text and event.message.text.startswith("/"):
            return
        try:
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
        logger.info(f"✅ Worker: @{me.username} ({name})")
        asyncio.create_task(client.run_until_disconnected())
    except Exception as e:
        logger.error(f"❌ Worker failed ({name}): {e}")
        await client.disconnect()


async def stop_worker(token: str):
    client = workers.pop(token, None)
    if client:
        await client.disconnect()
        logger.info(f"🛑 Stopped worker ...{token[:10]}")


# ─── Master Bot ──────────────────────────────────────────────────
master = TelegramClient("sessions/master", API_ID, API_HASH)


# FIX 2: /start shows ALL registered bots of user + "Add Another Bot" button
@master.on(events.NewMessage(pattern=r"^/start$"))
async def master_start(event):
    sender     = await event.get_sender()
    first_name = getattr(sender, "first_name", "there") or "there"

    user_bots = await bots_col.find({"owner_id": event.sender_id}).to_list(length=50)

    if user_bots:
        bot_list = "\n".join(
            [f"🤖 **{b['name']}** (@{b['username'] or 'N/A'}) — "
             f"{'🟢 Running' if b['token'] in workers else '🔴 Stopped'}"
             for b in user_bots]
        )
        text = (
            f"👋 **Hey {first_name}!**\n\n"
            f"📋 **Tumhare Registered Bots:**\n{bot_list}\n\n"
            f"Aur bot add karo ya manage karo:"
        )
        # FIX 3: "Add Another Bot" button always shown
        buttons = [
            [Button.inline("➕ Add Another Bot", data="register")],
            [Button.inline("🗑 Ek Bot Remove Karo", data="list_remove"),
             Button.inline("📊 All Status", data=f"allstatus_{event.sender_id}")],
        ]
    else:
        text = (
            f"👋 **Hey {first_name}! Welcome!**\n\n"
            + WELCOME_MSG +
            "\n\n⬇️ Apna bot register karo:"
        )
        buttons = [[Button.inline("➕ Apna Bot Register Karo", data="register")]]

    await event.respond(text, buttons=buttons)


@master.on(events.CallbackQuery(data=b"register"))
async def ask_for_token(event):
    waiting_for_token.add(event.sender_id)
    await event.respond(
        "🔑 **Apna BotFather token paste karo:**\n\n"
        "Token aisa dikhta hai:\n`123456789:AAFxxxxxxxxxxxxxxxxxxxxxxxxx`\n\n"
        "❌ Cancel → /cancel"
    )
    await event.answer()


@master.on(events.NewMessage(pattern=r"^/cancel$"))
async def cancel_reg(event):
    waiting_for_token.discard(event.sender_id)
    await event.respond("❌ Cancel ho gaya.")


@master.on(events.NewMessage())
async def handle_token_input(event):
    if event.sender_id not in waiting_for_token:
        return
    if not event.message.text or event.message.text.startswith("/"):
        return

    token = event.message.text.strip()
    waiting_for_token.discard(event.sender_id)

    if ":" not in token or len(token) < 30:
        await event.respond("❌ Token format galat hai. /start se dobara try karo.")
        return

    dup = await bots_col.find_one({"token": token})
    if dup:
        await event.respond("⚠️ Ye token already registered hai!")
        return

    await event.respond("⏳ Token verify ho raha hai...")

    try:
        test = TelegramClient(f"sessions/test_{token[:10]}", API_ID, API_HASH)
        await test.start(bot_token=token)
        me           = await test.get_me()
        bot_username = me.username or ""
        bot_name     = me.first_name or "My Bot"
        await test.disconnect()
    except Exception as e:
        await event.respond(f"❌ Token invalid!\n\nError: `{e}`")
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
        f"✅ **Bot registered!**\n\n"
        f"🤖 **{bot_name}** (@{bot_username})\n\n"
        f"Ab group/channel me add karo aur admin banao 🎉",
        buttons=[[
            Button.url("➕ Add To Group",   f"https://t.me/{bot_username}?startgroup=true"),
            Button.url("📢 Add To Channel", f"https://t.me/{bot_username}?startchannel=true"),
        ]] if bot_username else None
    )


# List bots for removal
@master.on(events.CallbackQuery(data=b"list_remove"))
async def list_for_remove(event):
    user_bots = await bots_col.find({"owner_id": event.sender_id}).to_list(length=50)
    if not user_bots:
        await event.answer("Koi bot nahi mila!", alert=True)
        return
    buttons = [
        [Button.inline(f"🗑 {b['name']} (@{b['username'] or 'N/A'})",
                       data=f"rm_{b['token'][:20]}")]
        for b in user_bots
    ]
    buttons.append([Button.inline("« Wapas", data="back_start")])
    await event.edit("Kaun sa bot remove karna hai?", buttons=buttons)


@master.on(events.CallbackQuery(pattern=rb"^rm_(.+)$"))
async def remove_bot(event):
    token_prefix = event.data.decode().split("_", 1)[1]
    doc = await bots_col.find_one({
        "owner_id": event.sender_id,
        "token": {"$regex": f"^{token_prefix}"}
    })
    if not doc:
        await event.answer("Bot nahi mila!", alert=True)
        return
    await stop_worker(doc["token"])
    await bots_col.delete_one({"_id": doc["_id"]})
    await event.edit(
        f"🗑 **{doc['name']}** remove ho gaya!\n\nAur bot add karne ke liye /start karo.",
    )


@master.on(events.CallbackQuery(pattern=rb"^allstatus_(\d+)$"))
async def all_status(event):
    user_bots = await bots_col.find({"owner_id": event.sender_id}).to_list(length=50)
    if not user_bots:
        await event.answer("Koi bot nahi!", alert=True)
        return
    lines = [
        f"{'🟢' if b['token'] in workers else '🔴'} @{b['username'] or 'N/A'} — {b['name']}"
        for b in user_bots
    ]
    await event.answer("\n".join(lines), alert=True)


@master.on(events.CallbackQuery(data=b"back_start"))
async def back_to_start(event):
    await event.delete()
    # re-trigger /start
    sender     = await event.get_sender()
    first_name = getattr(sender, "first_name", "there") or "there"
    user_bots  = await bots_col.find({"owner_id": event.sender_id}).to_list(length=50)
    if user_bots:
        bot_list = "\n".join(
            [f"🤖 **{b['name']}** (@{b['username'] or 'N/A'}) — "
             f"{'🟢 Running' if b['token'] in workers else '🔴 Stopped'}"
             for b in user_bots]
        )
        text    = f"👋 **Hey {first_name}!**\n\n📋 **Tumhare Bots:**\n{bot_list}"
        buttons = [
            [Button.inline("➕ Add Another Bot", data="register")],
            [Button.inline("🗑 Ek Bot Remove Karo", data="list_remove"),
             Button.inline("📊 All Status", data=f"allstatus_{event.sender_id}")],
        ]
        await master.send_message(event.sender_id, text, buttons=buttons)


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

    async for doc in bots_col.find({"active": True}):
        logger.info(f"🔄 Restoring: {doc['name']}")
        await start_worker(doc["token"], doc["username"], doc["name"])

    await master.start(bot_token=MASTER_TOKEN)
    me = await master.get_me()
    logger.info(f"🤖 Master: @{me.username}")
    await master.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
