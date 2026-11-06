import asyncio
import os
import sqlite3
import aiohttp
import aiohttp
from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================== SOZLAMALAR ==================
BOT_TOKEN = "BOT_TOKEN_SHU_YERGA"
MAIN_ADMINS = [123456789]                      # asosiy admin ID lari

BUBBLE_URL = "https://bubble.example.com"      # Bubble havolasi
BUBBLE_CHAT_URL = "https://bubble.example.com/chat"  # Bubble Chat havolasi
GUIDE_URL = "https://t.me/your_channel/1"      # Qo'llanma havolasi

# Bubble AI API (token yoki IP/URL). Bo'sh qoldirsangiz, API o'chiq bo'ladi.
BUBBLE_API_URL = ""                            # masalan: http://1.2.3.4:8000/v1/chat
BUBBLE_API_TOKEN = ""
# ================================================

db = sqlite3.connect("bot.db")
db.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT, username TEXT)")
db.execute("CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY)")
db.execute("CREATE TABLE IF NOT EXISTS channels(chat_id TEXT PRIMARY KEY, title TEXT, url TEXT)")
db.commit()


def is_admin(uid: int) -> bool:
    return uid in MAIN_ADMINS or db.execute(
        "SELECT 1 FROM admins WHERE id=?", (uid,)).fetchone() is not None


class S(StatesGroup):
    add_admin = State()
    broadcast = State()
    add_channel = State()
    ai_chat = State()


# ---------- Klaviaturalar ----------
def main_kb(uid: int) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text="Bubble AI Chat")]]
    if is_admin(uid):
        rows.append([KeyboardButton(text="Admin Panel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


back_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Botga qaytish")]], resize_keyboard=True)

start_ikb = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="Bubble", url=BUBBLE_URL),
    InlineKeyboardButton(text="Qo'llanma", url=GUIDE_URL),
]])

admin_ikb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="➕ Admin qo'shish", callback_data="adm_add")],
    [InlineKeyboardButton(text="📢 Reklama tarqatish", callback_data="adm_ads")],
    [InlineKeyboardButton(text="🔒 Majburiy obuna", callback_data="adm_sub")],
    [InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="adm_users")],
])


# ---------- Majburiy obuna ----------
async def not_subscribed(bot: Bot, uid: int):
    missing = []
    for chat_id, title, url in db.execute("SELECT chat_id,title,url FROM channels"):
        try:
            m = await bot.get_chat_member(chat_id, uid)
            if m.status in ("left", "kicked"):
                missing.append((title, url))
        except Exception:
            continue  # bot kanalda admin emas bo'lsa o'tkazib yuboriladi
    return missing


def sub_kb(missing):
    kb = InlineKeyboardBuilder()
    for title, url in missing:
        kb.row(InlineKeyboardButton(text=title, url=url))
    kb.row(InlineKeyboardButton(text="✅ Tekshirish", callback_data="sub_check"))
    return kb.as_markup()


class SubMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = event.from_user
        if is_admin(user.id) or (isinstance(event, CallbackQuery) and event.data == "sub_check"):
            return await handler(event, data)
        missing = await not_subscribed(data["bot"], user.id)
        if missing:
            msg = event.message if isinstance(event, CallbackQuery) else event
            await msg.answer("Botdan foydalanish uchun kanallarga obuna bo'ling:",
                             reply_markup=sub_kb(missing))
            if isinstance(event, CallbackQuery):
                await event.answer()
            return
        return await handler(event, data)


# ---------- Bubble API ----------
async def ask_bubble(text: str) -> str:
    headers = {"Authorization": f"Bearer {BUBBLE_API_TOKEN}"}
    async with aiohttp.ClientSession() as s:
        async with s.post(BUBBLE_API_URL, json={"message": text},
                          headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as r:
            data = await r.json()
            # Bubble javob formatiga qarab moslang:
            return data.get("reply") or data.get("answer") or str(data)


dp = Dispatcher(storage=MemoryStorage())
dp.message.middleware(SubMiddleware())
dp.callback_query.middleware(SubMiddleware())


# ---------- Foydalanuvchi qismi ----------
@dp.message(CommandStart())
async def start(m: Message, state: FSMContext):
    await state.clear()
    u = m.from_user
    db.execute("INSERT OR REPLACE INTO users VALUES(?,?,?)",
               (u.id, u.full_name, u.username or ""))
    db.commit()
    await m.answer(f"Salom, {u.full_name}! 👋", reply_markup=main_kb(u.id))
    await m.answer("Quyidagilardan birini tanlang:", reply_markup=start_ikb)


@dp.callback_query(F.data == "sub_check")
async def sub_check(c: CallbackQuery):
    missing = await not_subscribed(c.bot, c.from_user.id)
    if missing:
        return await c.answer("Hali hamma kanalga obuna bo'lmadingiz!", show_alert=True)
    await c.message.delete()
    await c.message.answer("Rahmat! Endi botdan foydalanishingiz mumkin.",
                           reply_markup=main_kb(c.from_user.id))


@dp.message(F.text == "Bubble AI Chat")
async def ai_chat(m: Message, state: FSMContext):
    if BUBBLE_API_URL:
        await state.set_state(S.ai_chat)
    await m.answer("Bubble Chatga o'tish:", reply_markup=back_kb)
    await m.answer("👇", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Bubble Chat", url=BUBBLE_CHAT_URL)]]))


@dp.message(F.text == "Botga qaytish")
async def back(m: Message, state: FSMContext):
    await state.clear()
    await m.answer("Bosh menyu", reply_markup=main_kb(m.from_user.id))
    await m.answer("Quyidagilardan birini tanlang:", reply_markup=start_ikb)


@dp.message(S.ai_chat, F.text)
async def ai_message(m: Message):
    try:
        await m.answer(await ask_bubble(m.text))
    except Exception as e:
        await m.answer(f"API xatosi: {e}")


# ---------- Admin panel ----------
@dp.message(F.text == "Admin Panel")
async def admin_panel(m: Message):
    if is_admin(m.from_user.id):
        await m.answer("🛠 Admin panel", reply_markup=admin_ikb)


@dp.callback_query(F.data.startswith(("adm_", "sub_add", "sub_del")))
async def admin_cb(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        return await c.answer("Ruxsat yo'q", show_alert=True)
    d = c.data
    if d == "adm_add":
        await state.set_state(S.add_admin)
        await c.message.answer("Yangi adminning Telegram ID sini yuboring:")
    elif d == "adm_ads":
        await state.set_state(S.broadcast)
        await c.message.answer("Reklama xabarini yuboring (matn, rasm, video...):")
    elif d == "adm_sub":
        kb = InlineKeyboardBuilder()
        text = "🔒 Majburiy obuna kanallari:\n"
        for chat_id, title, _ in db.execute("SELECT * FROM channels"):
            text += f"• {title} ({chat_id})\n"
            kb.row(InlineKeyboardButton(text=f"❌ {title}", callback_data=f"sub_del:{chat_id}"))
        kb.row(InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="sub_add"))
        await c.message.answer(text + "\nBot kanalda admin bo'lishi shart.",
                               reply_markup=kb.as_markup())
    elif d == "sub_add":
        await state.set_state(S.add_channel)
        await c.message.answer("Kanal username yoki ID sini yuboring (masalan @kanal):")
    elif d.startswith("sub_del:"):
        db.execute("DELETE FROM channels WHERE chat_id=?", (d.split(":", 1)[1],))
        db.commit()
        await c.message.answer("Kanal o'chirildi.")
    elif d == "adm_users":
        rows = db.execute("SELECT id,name,username FROM users").fetchall()
        await c.message.answer(f"👥 Jami: {len(rows)} ta")
        lines = [f"{i}. {n} — {'@' + u if u else 'username yo`q'} ({uid})"
                 for i, (uid, n, u) in enumerate(rows, 1)]
        for k in range(0, len(lines), 50):
            await c.message.answer("\n".join(lines[k:k + 50]))
    await c.answer()


@dp.message(S.add_admin)
async def do_add_admin(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    if not (m.text or "").strip().isdigit():
        return await m.answer("Faqat raqamli ID yuboring.")
    db.execute("INSERT OR IGNORE INTO admins VALUES(?)", (int(m.text),))
    db.commit()
    await state.clear()
    await m.answer("✅ Admin qo'shildi.")


@dp.message(S.add_channel)
async def do_add_channel(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    ref = (m.text or "").strip()
    try:
        chat = await m.bot.get_chat(ref)
        url = f"https://t.me/{chat.username}" if chat.username else await m.bot.export_chat_invite_link(chat.id)
        db.execute("INSERT OR REPLACE INTO channels VALUES(?,?,?)",
                   (str(chat.id), chat.title, url))
        db.commit()
        await m.answer(f"✅ Qo'shildi: {chat.title}")
    except Exception as e:
        await m.answer(f"Xatolik: {e}\nBot kanalda admin ekanini tekshiring.")
    await state.clear()


@dp.message(S.broadcast)
async def do_broadcast(m: Message, state: FSMContext):
    if not is_admin(m.from_user.id):
        return
    await state.clear()
    ok = fail = 0
    for (uid,) in db.execute("SELECT id FROM users").fetchall():
        try:
            await m.copy_to(uid)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await m.answer(f"📢 Yuborildi: {ok}\nYetmadi: {fail}")


async def main():
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
