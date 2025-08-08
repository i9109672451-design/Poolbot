"""
Telegram-бот для бассейна: FAQ + расписание + запись + перевод на оператора.

Быстрый старт:
1) Создайте бота у @BotFather → получите токен.
2) Заполните .env:
   BOT_TOKEN=xxx
   ADMIN_CHAT_ID=123456789  # ваш личный TG ID или ID операторского чата
3) Установите зависимости:
   pip install aiogram==3.13.1 python-dotenv==1.0.1 pytz==2024.1
4) Запуск:
   python bot.py

Настройки ниже помечены TODO — заполните под свой бассейн.
"""

import asyncio
import os
from datetime import datetime, timedelta, time, date
from typing import Dict, List, Tuple

import pytz
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "0"))  # TODO: укажите ID оператора/чата

# ====== КОНФИГ БАССЕЙНА (ЗАПОЛНИТЕ ПОД СЕБЯ) ======
POOL_NAME = "Ваш Бассейн"  # TODO
TZ = pytz.timezone("Europe/Moscow")  # TODO: ваш часовой пояс

# Что взять с собой
REQUIRED_ITEMS = [
    "Шапочка для плавания",
    "Купальник/плавки",
    "Сланцы",
    "Полотенце",
    "Средства гигиены (душ)",
    "Замок для шкафчика (если нужен)",
]

# Минимальный возраст ребёнка
MIN_CHILD_AGE = 4  # TODO: укажите актуально

# График работы по дням недели: 0-пн ... 6-вс (время локальное TZ)
# Пара (open, close) или None, если выходной
WEEKLY_HOURS: Dict[int, Tuple[time, time] | None] = {
    0: (time(7, 0), time(22, 0)),  # Пн
    1: (time(7, 0), time(22, 0)),  # Вт
    2: (time(7, 0), time(22, 0)),  # Ср
    3: (time(7, 0), time(22, 0)),  # Чт
    4: (time(7, 0), time(22, 0)),  # Пт
    5: (time(8, 0), time(20, 0)),  # Сб
    6: (time(9, 0), time(18, 0)),  # Вс
}

# Праздники/нерабочие дни (YYYY-MM-DD)
HOLIDAYS = {
    # "2025-01-01",
}

# Длина слота для записи (мин)
SLOT_MINUTES = 60  # TODO: 30 или 60

# Каналы записи: укажите один или несколько вариантов
BOOKING_OPTIONS = [
    "Позвонить администратору: +7 (999) 000-00-00",
    "Оставить заявку на сайте: example.com/booking",
    "Написать сюда: нажмите кнопку \"Записаться\" и укажите желаемое время",
]

# ====== ХРАНИЛИЩЕ (демо, в памяти). Замените на БД при деплое. ======
# Пример: BOOKED["2025-08-10"] = ["10:00", "15:00"] — занятые слоты локального времени
BOOKED: Dict[str, List[str]] = {}

# ====== УТИЛИТЫ ВРЕМЕНИ ======

def now_local() -> datetime:
    return datetime.now(TZ)

def local_date_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")

def is_holiday(d: date) -> bool:
    return local_date_str(d) in HOLIDAYS

def weekday_hours(d: date) -> Tuple[time, time] | None:
    if is_holiday(d):
        return None
    return WEEKLY_HOURS.get(d.weekday())

def is_open_on(d: date) -> bool:
    return weekday_hours(d) is not None

def is_open_now() -> bool:
    dt = now_local()
    hours = weekday_hours(dt.date())
    if not hours:
        return False
    open_t, close_t = hours
    return open_t <= dt.time() <= close_t

def generate_slots(d: date) -> List[str]:
    hours = weekday_hours(d)
    if not hours:
        return []
    open_t, close_t = hours
    # Генерация слотов фиксированной длительности между open_t и close_t
    start_dt = TZ.localize(datetime.combine(d, open_t))
    end_dt = TZ.localize(datetime.combine(d, close_t))
    slots = []
    cur = start_dt
    while cur + timedelta(minutes=SLOT_MINUTES) <= end_dt:
        slots.append(cur.strftime("%H:%M"))
        cur += timedelta(minutes=SLOT_MINUTES)
    # Исключаем занятые
    busy = set(BOOKED.get(local_date_str(d), []))
    return [s for s in slots if s not in busy]

def next_week_slots() -> Dict[str, List[str]]:
    today = now_local().date()
    result: Dict[str, List[str]] = {}
    for i in range(7):
        d = today + timedelta(days=i)
        free = generate_slots(d)
        if free:
            result[local_date_str(d)] = free
        else:
            result[local_date_str(d)] = []
    return result

# ====== КНОПКИ ======

MAIN_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Что взять с собой?", callback_data="faq_items")],
    [InlineKeyboardButton(text="Работаете ли сегодня?", callback_data="is_open_today")],
    [InlineKeyboardButton(text="Как записаться?", callback_data="how_to_book")],
    [InlineKeyboardButton(text="Свободное время (7 дней)", callback_data="free_slots")],
    [InlineKeyboardButton(text="С какого возраста?", callback_data="min_age")],
    [InlineKeyboardButton(text="Записаться", callback_data="book_start")],
    [InlineKeyboardButton(text="Связаться с оператором", callback_data="operator")],
])

# ====== ИНИЦ ======
dp = Dispatcher()

# Память о последнем вопросе для перевода оператору
LAST_QUESTION: Dict[int, str] = {}

# ====== ХЕНДЛЕРЫ ======

@dp.message(Command("start", "help"))
async def cmd_start(message: Message):
    await message.answer(
        f"Привет! Я бот бассейна \"{POOL_NAME}\". Чем помочь?",
        reply_markup=MAIN_KB,
    )

@dp.callback_query(F.data == "faq_items")
async def cb_faq_items(call: CallbackQuery):
    text = "\n".join(f"• {x}" for x in REQUIRED_ITEMS)
    await call.message.answer(f"Что взять с собой:\n{text}")
    await call.answer()

@dp.callback_query(F.data == "is_open_today")
async def cb_is_open_today(call: CallbackQuery):
    dt = now_local()
    flag = is_open_now()
    hours = weekday_hours(dt.date())
    if hours:
        t1, t2 = hours
        schedule = f"Сегодня работаем с {t1.strftime('%H:%M')} до {t2.strftime('%H:%M')} ({TZ.zone})."
    else:
        schedule = "Сегодня выходной."
    status = "Сейчас ОТКРЫТО ✅" if flag else "Сейчас ЗАКРЫТО ⛔"
    await call.message.answer(f"{status}\n{schedule}")
    await call.answer()

@dp.callback_query(F.data == "how_to_book")
async def cb_how_to_book(call: CallbackQuery):
    text = "\n".join(f"• {x}" for x in BOOKING_OPTIONS)
    await call.message.answer(f"Как записаться:\n{text}")
    await call.answer()

@dp.callback_query(F.data == "free_slots")
async def cb_free_slots(call: CallbackQuery):
    slots = next_week_slots()
    lines = []
    for d, times in slots.items():
        if times:
            lines.append(f"{d}: {', '.join(times)}")
        else:
            lines.append(f"{d}: нет свободных слотов или выходной")
    await call.message.answer("Свободное время на ближайшие 7 дней:\n" + "\n".join(lines))
    await call.answer()

@dp.callback_query(F.data == "min_age")
async def cb_min_age(call: CallbackQuery):
    await call.message.answer(
        f"Мы записываем детей с {MIN_CHILD_AGE} лет. Для малышей возможны занятия в сопровождении тренера (уточняйте у администратора)."
    )
    await call.answer()

# ====== Примитивная запись слота через бота (демо) ======

BOOK_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Сегодня", callback_data="book_day_0")],
    [InlineKeyboardButton(text="Завтра", callback_data="book_day_1")],
    [InlineKeyboardButton(text="Другая дата (7 дней)", callback_data="book_day_more")],
    [InlineKeyboardButton(text="Назад", callback_data="back_main")],
])

@dp.callback_query(F.data == "book_start")
async def cb_book_start(call: CallbackQuery):
    await call.message.answer("Выберите день для записи:", reply_markup=BOOK_KB)
    await call.answer()

@dp.callback_query(F.data.in_(
    {"book_day_0", "book_day_1", "book_day_more"}
))
async def cb_pick_day(call: CallbackQuery):
    today = now_local().date()
    if call.data == "book_day_0":
        d = today
        await show_day_slots(call, d)
    elif call.data == "book_day_1":
        d = today + timedelta(days=1)
        await show_day_slots(call, d)
    else:
        # показать список кнопок на 7 дней
        kb_rows = []
        for i in range(7):
            d = today + timedelta(days=i)
            kb_rows.append([InlineKeyboardButton(text=local_date_str(d), callback_data=f"book_{local_date_str(d)}")])
        kb_rows.append([InlineKeyboardButton(text="Назад", callback_data="book_start")])
        await call.message.answer("Выберите дату:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await call.answer()

async def show_day_slots(call: CallbackQuery, d: date):
    times = generate_slots(d)
    if not times:
        await call.message.answer(f"{local_date_str(d)}: нет свободных слотов или выходной")
        return
    # делаем сетку с кнопками времени
    rows = []
    for t in times:
        rows.append([InlineKeyboardButton(text=t, callback_data=f"book_time|{local_date_str(d)}|{t}")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="book_start")])
    await call.message.answer(f"Доступно {local_date_str(d)}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))

@dp.callback_query(F.data.startswith("book_"))
async def cb_book_specific_day(call: CallbackQuery):
    # формата book_YYYY-MM-DD
    _, ds = call.data.split("_", 1)
    try:
        y, m, d = map(int, ds.split("-"))
        await show_day_slots(call, date(y, m, d))
    except Exception:
        await call.message.answer("Неверная дата")
    await call.answer()

@dp.callback_query(F.data.startswith("book_time|"))
async def cb_book_time(call: CallbackQuery):
    _, ds, ts = call.data.split("|")
    # Регистрируем бронь (демо) и уведомляем оператора
    BOOKED.setdefault(ds, []).append(ts)
    await call.message.answer(f"Запрос на запись {ds} в {ts} принят. Администратор подтвердит в ближайшее время.")
    if ADMIN_CHAT_ID:
        try:
            await call.bot.send_message(
                ADMIN_CHAT_ID,
                f"Новая заявка: {call.from_user.full_name} (@{call.from_user.username or '—'})\nДата: {ds} {ts}\nUserID: {call.from_user.id}",
            )
        except Exception:
            pass
    await call.answer()

# ====== Перевод на оператора ======

@dp.callback_query(F.data == "operator")
async def cb_operator(call: CallbackQuery):
    await call.message.answer("Напишите ваш вопрос, я передам оператору. Или позвоните: +7 (999) 000-00-00")
    await call.answer()

@dp.message(F.text)
async def on_text(message: Message):
    text = message.text.strip()
    user_id = message.from_user.id

    # Лёгкие NLP-триггеры (FAQ без кнопок)
    low = text.lower()
    if any(k in low for k in ["что взять", "с собой", "шапочка", "полотенце"]):
        items = "\n".join(f"• {x}" for x in REQUIRED_ITEMS)
        await message.answer(f"Что взять с собой:\n{items}")
        return
    if "работает" in low or "открыт" in low or "сегодня" in low:
        dt = now_local()
        hours = weekday_hours(dt.date())
        status = "открыты ✅" if is_open_now() else "закрыты ⛔"
        if hours:
            t1, t2 = hours
            await message.answer(
                f"Сегодня мы {status}. Часы: {t1.strftime('%H:%M')}–{t2.strftime('%H:%M')} ({TZ.zone})."
            )
        else:
            await message.answer("Сегодня выходной.")
        return
    if "как запис" in low or "записат" in low or "запись" in low:
        txt = "\n".join(f"• {x}" for x in BOOKING_OPTIONS)
        await message.answer(f"Как записаться:\n{txt}")
        return
    if "свободн" in low and ("время" in low or "слоты" in low or "окна" in low or "недел" in low):
        slots = next_week_slots()
        lines = []
        for d, times in slots.items():
            if times:
                lines.append(f"{d}: {', '.join(times)}")
            else:
                lines.append(f"{d}: нет свободных слотов или выходной")
        await message.answer("Свободное время на ближайшие 7 дней:\n" + "\n".join(lines))
        return
    if "возраст" in low or "скольки лет" in low or "ребен" in low or "дет" in low:
        await message.answer(f"Мы записываем детей с {MIN_CHILD_AGE} лет. Детали у администратора.")
        return

    # Если не распознали — сохраняем вопрос и предлагаем оператора
    LAST_QUESTION[user_id] = text
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Передать оператору", callback_data="send_to_operator")],
        [InlineKeyboardButton(text="Меню", callback_data="back_main")],
    ])
    await message.answer("Я не до конца понял запрос. Передать оператору?", reply_markup=kb)

@dp.callback_query(F.data == "send_to_operator")
async def cb_send_to_operator(call: CallbackQuery):
    q = LAST_QUESTION.get(call.from_user.id, "(нет текста)")
    if ADMIN_CHAT_ID:
        try:
            await call.bot.send_message(
                ADMIN_CHAT_ID,
                f"Вопрос от {call.from_user.full_name} (@{call.from_user.username or '—'}), ID {call.from_user.id}:\n{q}",
            )
            await call.message.answer("Ваш вопрос передан оператору. Ответят как можно скорее.")
        except Exception:
            await call.message.answer("Не удалось передать оператору. Попробуйте позже или позвоните администратору.")
    else:
        await call.message.answer("Оператор не подключен. Укажите ADMIN_CHAT_ID в .env")
    await call.answer()

@dp.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery):
    await call.message.answer("Главное меню:", reply_markup=MAIN_KB)
    await call.answer()

# ====== MAIN ======
async def main():
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN")
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
