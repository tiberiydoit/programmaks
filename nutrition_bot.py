"""
Nutrition plan bot — admin panel for fitness coach.
Клієнти бачать тільки свій план. Тренер керує через адмін панель.
"""
import base64
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    MenuButtonWebApp, ReplyKeyboardMarkup, Update, WebAppInfo,
)
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters,
)

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Конфіг ────────────────────────────────────────────────────────────────────

OWNER_ID    = int(os.getenv("OWNER_ID", "716092714"))
BOT_TOKEN   = os.getenv("NUTRITION_BOT_TOKEN", "")
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://programmaks.netlify.app")

DB_PATH = Path(os.getenv("DB_PATH", "clients_db.json"))

# ── FSM стани для /newclient ──────────────────────────────────────────────────

(
    NC_NAME, NC_TG_ID, NC_MEALS_COUNT,
    NC_DAILY, NC_STEPS,
    NC_MEAL_0, NC_MEAL_1, NC_MEAL_2, NC_MEAL_3, NC_MEAL_4,
) = range(10)

# ── Назви та часи прийомів за замовчуванням ───────────────────────────────────

MEAL_DEFAULTS = {
    3: [
        ("Сніданок", "09:00–10:00"),
        ("Обід",     "13:00–15:00"),
        ("Вечеря",   "19:00–21:00"),
    ],
    4: [
        ("Сніданок", "09:00–10:00"),
        ("Перекус",  "12:00–12:30"),
        ("Обід",     "14:00–15:00"),
        ("Вечеря",   "19:00–21:00"),
    ],
    5: [
        ("Сніданок",  "08:00–09:00"),
        ("Перекус 1", "11:00–11:30"),
        ("Обід",      "13:00–14:00"),
        ("Перекус 2", "16:30–17:00"),
        ("Вечеря",    "19:00–21:00"),
    ],
}

# ── Адмін клавіатура (тільки для тренера) ─────────────────────────────────────

ADMIN_KB = ReplyKeyboardMarkup(
    [
        ["➕ Новий клієнт", "👥 Клієнти"],
        ["📤 Надіслати план", "✏️ Редагувати"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

# ── База клієнтів (JSON файл) ─────────────────────────────────────────────────

def _load_db() -> dict:
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    return {"clients": []}


def _save_db(db: dict):
    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_client_by_slug(slug: str) -> dict | None:
    db = _load_db()
    return next((c for c in db["clients"] if c["slug"] == slug), None)


def _get_client_by_tg_id(tg_id: int) -> dict | None:
    db = _load_db()
    return next((c for c in db["clients"] if c.get("telegram_id") == tg_id), None)


def _save_client(client: dict):
    db = _load_db()
    existing = next((i for i, c in enumerate(db["clients"]) if c["slug"] == client["slug"]), None)
    if existing is not None:
        db["clients"][existing] = client
    else:
        db["clients"].append(client)
    _save_db(db)


def _all_clients() -> list[dict]:
    return _load_db()["clients"]


# ── URL генерація ─────────────────────────────────────────────────────────────

def _build_url(client: dict) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps(client, ensure_ascii=False).encode()
    ).decode()
    return f"{MINI_APP_URL}?d={payload}"


# ── Хелпери ───────────────────────────────────────────────────────────────────

def _is_owner(update: Update) -> bool:
    uid = update.effective_user.id if update.effective_user else 0
    return uid == OWNER_ID


def _client_summary(c: dict) -> str:
    d = c["daily"]
    meals_count = len(c.get("meals", []))
    tg = c.get("telegram_id") or "не вказано"
    return (
        f"👤 <b>{c['name']}</b>\n"
        f"КБЖВ: {d['kcal']} ккал | Б {d['protein']}г | Ж {d['fat']}г | В {d['carbs']}г\n"
        f"Кроки: {c.get('steps', 7000)} | Прийомів: {meals_count}\n"
        f"Telegram ID: <code>{tg}</code>"
    )


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Тренер — показуємо адмін панель
    if user_id == OWNER_ID:
        await update.message.reply_text(
            "👋 <b>Nutrition Admin</b>\n\n"
            "Обери дію на панелі нижче або скористайся командами:\n"
            "/newclient — створити клієнта\n"
            "/clients — всі клієнти\n"
            "/send — надіслати план\n"
            "/edit — редагувати",
            parse_mode="HTML",
            reply_markup=ADMIN_KB,
        )
        return

    # Клієнт — перевіряємо чи є план
    client = _get_client_by_tg_id(user_id)
    if client:
        url = _build_url(client)
        await update.message.reply_text(
            f"👋 Привіт, <b>{client['name']}</b>!\nТут твій план харчування.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 Відкрити мій план", web_app=WebAppInfo(url=url))
            ]]),
        )
    else:
        await update.message.reply_text(
            "👋 Привіт! Твій план ще не готовий.\n"
            "Зв'яжіться з тренером для отримання доступу."
        )


# ── /myid ─────────────────────────────────────────────────────────────────────

async def cmd_myid(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(
        f"Твій Telegram ID: <code>{uid}</code>",
        parse_mode="HTML",
    )


# ── /clients ──────────────────────────────────────────────────────────────────

async def cmd_clients(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    clients = _all_clients()
    if not clients:
        await update.message.reply_text("Клієнтів ще немає. Натисни ➕ Новий клієнт")
        return

    rows = []
    for c in clients:
        rows.append([
            InlineKeyboardButton(f"👤 {c['name']}", callback_data=f"view:{c['slug']}"),
            InlineKeyboardButton("✏️", callback_data=f"editclient:{c['slug']}"),
            InlineKeyboardButton("📤", callback_data=f"send:{c['slug']}"),
        ])
    await update.message.reply_text(
        f"👥 <b>Клієнти ({len(clients)}):</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ── /send ─────────────────────────────────────────────────────────────────────

async def cmd_send(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    clients = _all_clients()
    if not clients:
        await update.message.reply_text("Немає клієнтів. Натисни ➕ Новий клієнт")
        return
    rows = [[InlineKeyboardButton(c["name"], callback_data=f"send:{c['slug']}")]
            for c in clients]
    await update.message.reply_text(
        "📤 Кому надіслати план?",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ── /edit ─────────────────────────────────────────────────────────────────────

async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    clients = _all_clients()
    if not clients:
        await update.message.reply_text("Немає клієнтів.")
        return
    rows = [[InlineKeyboardButton(c["name"], callback_data=f"editclient:{c['slug']}")]
            for c in clients]
    await update.message.reply_text(
        "✏️ Кого редагувати?",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ── Обробник кнопок клавіатури ────────────────────────────────────────────────

async def handle_menu_buttons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    text = update.message.text

    if text == "➕ Новий клієнт":
        return await cmd_newclient(update, ctx)
    elif text == "👥 Клієнти":
        return await cmd_clients(update, ctx)
    elif text == "📤 Надіслати план":
        return await cmd_send(update, ctx)
    elif text == "✏️ Редагувати":
        return await cmd_edit(update, ctx)


# ── Callback handler ──────────────────────────────────────────────────────────

async def cb_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or query.from_user.id != OWNER_ID:
        return
    await query.answer()
    data = query.data

    # ── Перегляд клієнта ──────────────────────────────────────────────────────
    if data.startswith("view:"):
        slug = data[5:]
        client = _get_client_by_slug(slug)
        if not client:
            await query.edit_message_text("Клієнта не знайдено.")
            return
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ Редагувати", callback_data=f"editclient:{slug}"),
                InlineKeyboardButton("📤 Надіслати", callback_data=f"send:{slug}"),
            ],
            [InlineKeyboardButton("← Назад", callback_data="back:clients")],
        ])
        await query.edit_message_text(_client_summary(client), parse_mode="HTML", reply_markup=kb)

    # ── Надіслати план клієнту ────────────────────────────────────────────────
    elif data.startswith("send:"):
        slug = data[5:]
        client = _get_client_by_slug(slug)
        if not client:
            await query.edit_message_text("Клієнта не знайдено.")
            return

        url = _build_url(client)
        tg_id = client.get("telegram_id")

        if tg_id:
            try:
                # Надсилаємо план клієнту
                await ctx.bot.send_message(
                    chat_id=tg_id,
                    text=f"👋 <b>{client['name']}</b>, твій план харчування готовий!",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            "📋 Відкрити план",
                            web_app=WebAppInfo(url=url),
                        )
                    ]]),
                )
                # Ставимо персональну кнопку меню для клієнта
                await ctx.bot.set_chat_menu_button(
                    chat_id=tg_id,
                    menu_button=MenuButtonWebApp(
                        text="📋 Мій план",
                        web_app=WebAppInfo(url=url),
                    ),
                )
                await query.edit_message_text(
                    f"✅ План надіслано <b>{client['name']}</b>!\n"
                    f"Кнопка меню теж оновлена — клієнт може відкривати план в один клік.",
                    parse_mode="HTML",
                )
            except Exception as e:
                await query.edit_message_text(
                    f"⚠️ Не вдалося надіслати: {e}\n\n"
                    f"Посилання для ручного надсилання:\n<code>{url}</code>",
                    parse_mode="HTML",
                )
        else:
            await query.edit_message_text(
                f"⚠️ У <b>{client['name']}</b> не вказано Telegram ID.\n\n"
                f"Надішли це посилання вручну:\n<code>{url}</code>",
                parse_mode="HTML",
            )

    # ── Редагувати клієнта — вибір поля ──────────────────────────────────────
    elif data.startswith("editclient:"):
        slug = data[11:]
        client = _get_client_by_slug(slug)
        if not client:
            await query.edit_message_text("Клієнта не знайдено.")
            return

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 КБЖВ (загальне)", callback_data=f"ef:{slug}:daily")],
            [InlineKeyboardButton("🍽 Порції прийомів", callback_data=f"ef:{slug}:meals")],
            [InlineKeyboardButton("👟 Кроки на день",   callback_data=f"ef:{slug}:steps")],
            [InlineKeyboardButton("← Назад",             callback_data=f"view:{slug}")],
        ])
        await query.edit_message_text(
            _client_summary(client) + "\n\n<i>Що змінюємо?</i>",
            parse_mode="HTML",
            reply_markup=kb,
        )

    # ── Редагування поля ─────────────────────────────────────────────────────
    elif data.startswith("ef:"):
        _, slug, field = data.split(":", 2)
        client = _get_client_by_slug(slug)
        if not client:
            await query.edit_message_text("Клієнта не знайдено.")
            return

        ctx.user_data["edit_slug"] = slug
        ctx.user_data["edit_field"] = field

        if field == "daily":
            d = client["daily"]
            await query.edit_message_text(
                f"Поточне КБЖВ: <code>{d['kcal']} {d['protein']} {d['fat']} {d['carbs']}</code>\n\n"
                "Введи нові значення через пробіл:\n"
                "<code>ккал білок жир вуглеводи</code>\n\n"
                "Приклад: <code>2160 181 75 191</code>",
                parse_mode="HTML",
            )

        elif field == "steps":
            await query.edit_message_text(
                f"Поточні кроки: <b>{client.get('steps', 7000)}</b>\n\n"
                "Введи нову кількість кроків:",
                parse_mode="HTML",
            )

        elif field == "meals":
            lines = []
            for i, m in enumerate(client.get("meals", []), 1):
                lines.append(
                    f"{i}. <b>{m['name']}</b> ({m['time']})\n"
                    f"   {m['kcal']} ккал | Б{m['p']}г Ж{m['f']}г В{m['c']}г"
                )
            ctx.user_data["edit_field"] = "meal_select"
            await query.edit_message_text(
                "\n\n".join(lines) + "\n\nВведи <b>номер прийому</b> для редагування:",
                parse_mode="HTML",
            )

    # ── Назад до списку клієнтів ──────────────────────────────────────────────
    elif data == "back:clients":
        clients = _all_clients()
        rows = []
        for c in clients:
            rows.append([
                InlineKeyboardButton(f"👤 {c['name']}", callback_data=f"view:{c['slug']}"),
                InlineKeyboardButton("✏️", callback_data=f"editclient:{c['slug']}"),
                InlineKeyboardButton("📤", callback_data=f"send:{c['slug']}"),
            ])
        await query.edit_message_text(
            f"👥 <b>Клієнти ({len(clients)}):</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows),
        )


# ── Обробник текстових відповідей при редагуванні ────────────────────────────

async def handle_edit_input(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    slug  = ctx.user_data.get("edit_slug")
    field = ctx.user_data.get("edit_field")
    if not slug or not field:
        return

    client = _get_client_by_slug(slug)
    if not client:
        await update.message.reply_text("Клієнта не знайдено.")
        ctx.user_data.clear()
        return

    text = update.message.text.strip()

    if field == "daily":
        try:
            kcal, p, f, c = map(int, text.split())
        except ValueError:
            await update.message.reply_text(
                "❌ Неправильний формат. Введи: <code>2160 181 75 191</code>", parse_mode="HTML"
            )
            return
        client["daily"] = {"kcal": kcal, "protein": p, "fat": f, "carbs": c}
        _save_client(client)
        await update.message.reply_text(
            f"✅ КБЖВ <b>{client['name']}</b> оновлено:\n"
            f"{kcal} ккал | Б {p}г | Ж {f}г | В {c}г",
            parse_mode="HTML",
        )
        ctx.user_data.clear()

    elif field == "steps":
        try:
            steps = int(text)
        except ValueError:
            await update.message.reply_text("❌ Введи число, наприклад: <code>7000</code>", parse_mode="HTML")
            return
        client["steps"] = steps
        _save_client(client)
        await update.message.reply_text(
            f"✅ Кроки <b>{client['name']}</b> оновлено: <b>{steps}</b>",
            parse_mode="HTML",
        )
        ctx.user_data.clear()

    elif field == "meal_select":
        try:
            idx = int(text) - 1
            if idx < 0 or idx >= len(client.get("meals", [])):
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Введи номер прийому зі списку.")
            return
        ctx.user_data["edit_meal_idx"] = idx
        ctx.user_data["edit_field"] = "meal_data"
        m = client["meals"][idx]
        await update.message.reply_text(
            f"Редагуємо: <b>{m['name']}</b> ({m['time']})\n"
            f"Зараз: <code>{m['kcal']} {m['p']} {m['f']} {m['c']}</code>\n\n"
            "Введи нові значення:\n<code>ккал білок жир вуглеводи</code>",
            parse_mode="HTML",
        )

    elif field == "meal_data":
        try:
            kcal, p, f, c = map(int, text.split())
        except ValueError:
            await update.message.reply_text(
                "❌ Формат: <code>735 52 23 81</code>", parse_mode="HTML"
            )
            return
        idx = ctx.user_data["edit_meal_idx"]
        client["meals"][idx].update({"kcal": kcal, "p": p, "f": f, "c": c})
        _save_client(client)
        m = client["meals"][idx]
        await update.message.reply_text(
            f"✅ <b>{m['name']}</b> оновлено:\n"
            f"{kcal} ккал | Б {p}г | Ж {f}г | В {c}г",
            parse_mode="HTML",
        )
        ctx.user_data.clear()


# ── /newclient — FSM wizard ───────────────────────────────────────────────────

async def cmd_newclient(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return ConversationHandler.END
    ctx.user_data.clear()
    await update.message.reply_text(
        "➕ <b>Новий клієнт</b>\n\n"
        "Крок 1 з 5: Введи ім'я клієнта:",
        parse_mode="HTML",
    )
    return NC_NAME


async def nc_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        "Крок 2 з 5: Telegram ID клієнта?\n\n"
        "<i>Клієнт може написати боту /myid щоб дізнатись свій ID.\n"
        "Якщо не знаєш — введи 0</i>",
        parse_mode="HTML",
    )
    return NC_TG_ID


async def nc_tg_id(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        tg_id = int(update.message.text.strip())
    except ValueError:
        tg_id = 0
    ctx.user_data["telegram_id"] = tg_id if tg_id != 0 else None
    await update.message.reply_text(
        "Крок 3 з 5: Скільки прийомів їжі?\n\nВведи <b>3</b>, <b>4</b> або <b>5</b>:",
        parse_mode="HTML",
    )
    return NC_MEALS_COUNT


async def nc_meals_count(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        n = int(update.message.text.strip())
        if n not in (3, 4, 5):
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введи 3, 4 або 5:")
        return NC_MEALS_COUNT
    ctx.user_data["meals_count"] = n
    ctx.user_data["meals"] = []
    await update.message.reply_text(
        "Крок 4 з 5: Загальне КБЖВ за день.\n\n"
        "Формат: <code>ккал білок жир вуглеводи</code>\n"
        "Приклад: <code>2160 181 75 191</code>",
        parse_mode="HTML",
    )
    return NC_DAILY


async def nc_daily(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        kcal, p, f, c = map(int, update.message.text.strip().split())
    except ValueError:
        await update.message.reply_text(
            "❌ Формат: <code>2160 181 75 191</code>", parse_mode="HTML"
        )
        return NC_DAILY
    ctx.user_data["daily"] = {"kcal": kcal, "protein": p, "fat": f, "carbs": c}
    await update.message.reply_text(
        "Крок 5 з 5: Кроки на день.\n\nПриклад: <code>7000</code>",
        parse_mode="HTML",
    )
    return NC_STEPS


async def nc_steps(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        steps = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введи число, наприклад: <code>7000</code>", parse_mode="HTML")
        return NC_STEPS
    ctx.user_data["steps"] = steps
    n = ctx.user_data["meals_count"]
    meal_defs = MEAL_DEFAULTS[n]
    ctx.user_data["meal_defs"] = meal_defs
    first = meal_defs[0]
    await update.message.reply_text(
        f"Тепер вводимо порції прийомів.\n\n"
        f"<b>{first[0]}</b> ({first[1]})\n"
        f"Формат: <code>ккал білок жир вуглеводи</code>\n"
        f"Приклад: <code>735 52 23 81</code>",
        parse_mode="HTML",
    )
    return NC_MEAL_0


async def _nc_meal(update: Update, ctx: ContextTypes.DEFAULT_TYPE, idx: int, next_state: int):
    try:
        kcal, p, f, c = map(int, update.message.text.strip().split())
    except ValueError:
        await update.message.reply_text(
            "❌ Формат: <code>735 52 23 81</code>", parse_mode="HTML"
        )
        return idx + NC_MEAL_0  # повторити той самий стан

    meal_defs = ctx.user_data["meal_defs"]
    name, time = meal_defs[idx]
    ctx.user_data["meals"].append({
        "name": name, "time": time,
        "kcal": kcal, "p": p, "f": f, "c": c,
    })

    if idx + 1 < len(meal_defs):
        nxt_name, nxt_time = meal_defs[idx + 1]
        await update.message.reply_text(
            f"<b>{nxt_name}</b> ({nxt_time})\n"
            f"<code>ккал білок жир вуглеводи</code>",
            parse_mode="HTML",
        )
        return next_state

    # Всі прийоми введено — зберігаємо
    name_str = ctx.user_data["name"]
    slug = name_str.lower().replace(" ", "_")
    client = {
        "slug":        slug,
        "name":        name_str,
        "telegram_id": ctx.user_data.get("telegram_id"),
        "daily":       ctx.user_data["daily"],
        "steps":       ctx.user_data["steps"],
        "meals":       ctx.user_data["meals"],
    }
    _save_client(client)
    url = _build_url(client)

    meals_text = "\n".join(
        f"  • {m['name']}: {m['kcal']} ккал | Б{m['p']} Ж{m['f']} В{m['c']}"
        for m in client["meals"]
    )
    await update.message.reply_text(
        f"✅ <b>{name_str}</b> створено!\n\n"
        f"КБЖВ: {client['daily']['kcal']} ккал | "
        f"Б {client['daily']['protein']}г | "
        f"Ж {client['daily']['fat']}г | "
        f"В {client['daily']['carbs']}г\n"
        f"Кроки: {client['steps']}\n\n"
        f"Прийоми:\n{meals_text}\n\n"
        f"Щоб надіслати план клієнту — натисни 📤 Надіслати план",
        parse_mode="HTML",
    )
    ctx.user_data.clear()
    return ConversationHandler.END


async def nc_meal_0(u, c): return await _nc_meal(u, c, 0, NC_MEAL_1)
async def nc_meal_1(u, c): return await _nc_meal(u, c, 1, NC_MEAL_2)
async def nc_meal_2(u, c): return await _nc_meal(u, c, 2, NC_MEAL_3)
async def nc_meal_3(u, c): return await _nc_meal(u, c, 3, NC_MEAL_4)
async def nc_meal_4(u, c): return await _nc_meal(u, c, 4, ConversationHandler.END)


async def nc_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("Скасовано.", reply_markup=ADMIN_KB)
    return ConversationHandler.END


# ── Error handler ─────────────────────────────────────────────────────────────

async def _error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error("Помилка: %s", ctx.error, exc_info=ctx.error)


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise RuntimeError("NUTRITION_BOT_TOKEN не задано в .env")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_error_handler(_error_handler)

    # FSM для створення клієнта
    nc_conv = ConversationHandler(
        entry_points=[
            CommandHandler("newclient", cmd_newclient),
        ],
        states={
            NC_NAME:        [MessageHandler(filters.TEXT & ~filters.COMMAND, nc_name)],
            NC_TG_ID:       [MessageHandler(filters.TEXT & ~filters.COMMAND, nc_tg_id)],
            NC_MEALS_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, nc_meals_count)],
            NC_DAILY:       [MessageHandler(filters.TEXT & ~filters.COMMAND, nc_daily)],
            NC_STEPS:       [MessageHandler(filters.TEXT & ~filters.COMMAND, nc_steps)],
            NC_MEAL_0:      [MessageHandler(filters.TEXT & ~filters.COMMAND, nc_meal_0)],
            NC_MEAL_1:      [MessageHandler(filters.TEXT & ~filters.COMMAND, nc_meal_1)],
            NC_MEAL_2:      [MessageHandler(filters.TEXT & ~filters.COMMAND, nc_meal_2)],
            NC_MEAL_3:      [MessageHandler(filters.TEXT & ~filters.COMMAND, nc_meal_3)],
            NC_MEAL_4:      [MessageHandler(filters.TEXT & ~filters.COMMAND, nc_meal_4)],
        },
        fallbacks=[CommandHandler("cancel", nc_cancel)],
        per_chat=True,
        per_message=False,
    )

    # Команди
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("myid",      cmd_myid))
    app.add_handler(CommandHandler("clients",   cmd_clients))
    app.add_handler(CommandHandler("send",      cmd_send))
    app.add_handler(CommandHandler("edit",      cmd_edit))

    # FSM wizard
    app.add_handler(nc_conv)

    # Callback кнопки
    app.add_handler(CallbackQueryHandler(cb_handler))

    # Кнопки головної клавіатури (тільки якщо не в FSM)
    menu_filter = filters.TEXT & filters.Regex(
        r"^(➕ Новий клієнт|👥 Клієнти|📤 Надіслати план|✏️ Редагувати)$"
    )
    app.add_handler(MessageHandler(menu_filter, handle_menu_buttons))

    # Редагування полів клієнта (текстові відповіді)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_input))

    logger.info("Бот запущено. Owner ID: %s", OWNER_ID)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
