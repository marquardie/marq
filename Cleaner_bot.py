from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from telegram.ext import (Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext, ConversationHandler)
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, time
import re
from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
creds_json = os.getenv("GOOGLE_CREDS_JSON")
with open("google-creds.json", "w") as f:
    f.write(creds_json.replace("\\n", "\n"))

GOOGLE_CREDS_FILE = "google-creds.json"

# Авторизація Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_FILE, scope)
client = gspread.authorize(creds)
sheet = client.open("Window Robot Rental").sheet1
context_sheet = client.open("Window Robot Rental").worksheet("Context")

# Етапи діалогу
DATE, NAME, PHONE, DISTRICT, STREET, DURATION, CONFIRM = range(7)
ADMIN_CHAT_ID = 1168672386

# Отримати доступні дати
def get_available_dates():
    all_dates = sheet.col_values(1)[1:]
    statuses = sheet.col_values(2)[1:]
    formatted_dates = []
    for d in all_dates:
        try:
            parsed = datetime.strptime(d.strip(), '%d.%m.%Y')
            formatted_dates.append(parsed.strftime('%d.%m.%Y'))
        except ValueError:
            try:
                parsed = datetime.strptime(d.strip(), '%Y-%m-%d')
                formatted_dates.append(parsed.strftime('%d.%m.%Y'))
            except ValueError:
                formatted_dates.append(str(d).strip())
    return {date: status.strip().lower() for date, status in zip(formatted_dates, statuses)}

def get_context_text(column_letter):
    return context_sheet.acell(f"{column_letter}2").value

def get_week_start(date):
    return date - timedelta(days=date.weekday())

def generate_week_buttons(week_offset=0):
    today = datetime.now()
    cutoff_time = time(14, 0)
    now_time = today.time()
    available_dates = get_available_dates()
    week_start = get_week_start(today) + timedelta(weeks=week_offset)

    week_buttons = []
    for i in range(6):
        day = week_start + timedelta(days=i)
        str_date = day.strftime("%d.%m.%Y")
        status = available_dates.get(str_date, '')

        is_today = (day.date() == today.date())
        after_cutoff_today = is_today and now_time > cutoff_time

        is_available = status == 'вільна'
        is_disabled = not is_available or (is_today and after_cutoff_today)

        if is_disabled:
            week_buttons.append([InlineKeyboardButton(f"🚫 {str_date}", callback_data="disabled")])
        else:
            week_buttons.append([InlineKeyboardButton(f"✅ {str_date}", callback_data=f"select_{str_date}")])

    nav_buttons = [[
        InlineKeyboardButton("➡️ Наступний тиждень", callback_data="next_week") if week_offset == 0 else InlineKeyboardButton("⬅️ Поточний тиждень", callback_data="current_week"),
        InlineKeyboardButton("📋 Меню", callback_data="menu")
    ]]
    week_buttons.extend(nav_buttons)
    return InlineKeyboardMarkup(week_buttons)

# --- Обробники ---
def show_start_button(update: Update, context: CallbackContext):
    keyboard = [[KeyboardButton("📋 Меню")]]
    update.message.reply_text("Натисни, щоб продовжити ⬇️", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

def send_menu(chat_id, context):
    keyboard = [
        [InlineKeyboardButton("📜 Правила оренди", callback_data="rules")],
        [InlineKeyboardButton("💰 Оплата і умови доставки 📍", callback_data="payment")],
        [InlineKeyboardButton("✅ Забронювати", callback_data="book_now")],
        [InlineKeyboardButton("🛠 Інструкція використання", callback_data="manual")]
    ]
    context.bot.send_message(chat_id=chat_id, text="📋 Головне меню:", reply_markup=InlineKeyboardMarkup(keyboard))

def start(update: Update, context: CallbackContext):
    send_menu(update.message.chat_id, context)

def handle_info_buttons(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data

    if data == "rules":
        text = get_context_text("B")
    elif data == "payment":
        text = get_context_text("C")
    elif data == "manual":
        text = get_context_text("A")
    elif data == "menu":
        send_menu(query.from_user.id, context)
        return ConversationHandler.END
    elif data == "book_now":
        query.edit_message_text("Введіть, будь ласка, Ваше ім'я та прізвище:")
        return NAME
    else:
        text = "Ой, щось пішло не так!"

    query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="menu")]]))
    
def handle_duration(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    duration = int(query.data.split("_")[1])
    context.user_data['duration'] = duration
    query.edit_message_text("Оберіть дату початку бронювання:", reply_markup=generate_week_buttons())
    return DATE

def select_date(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()

    if query.data.startswith("select_"):
        selected_date = query.data.replace("select_", "")
        context.user_data['selected_date'] = selected_date  # 🔧 Без .clear()
        query.message.delete()
        confirm_text = (f"Перевірте дані перед бронюванням:\n"
                        f"Дата: {selected_date} ({context.user_data.get('duration', 1)} доба/доб)\n"
                        f"Ім'я: {context.user_data.get('name')}\n"
                        f"Район: {context.user_data.get('district')}\n"
                        f"Вулиця: {context.user_data.get('street')}\n"
                        f"Телефон: {context.user_data.get('phone')}\n\nПідтвердити?")
        keyboard = [
            [InlineKeyboardButton("✅ Підтвердити", callback_data='confirm')],
            [InlineKeyboardButton("❌ Скасувати", callback_data='cancel')]
        ]
        context.bot.send_message(chat_id=query.from_user.id, text=confirm_text, reply_markup=InlineKeyboardMarkup(keyboard))
        return CONFIRM

    if query.data == "disabled":
        query.answer("Ця дата недоступна для бронювання. Оберіть іншу дату", show_alert=True)
        return DATE
    if query.data == "next_week":
        query.edit_message_reply_markup(reply_markup=generate_week_buttons(week_offset=1))
        return DATE
    if query.data == "current_week":
        query.edit_message_reply_markup(reply_markup=generate_week_buttons(week_offset=0))
        return DATE

# --- Сценарій бронювання ---
def get_name(update: Update, context: CallbackContext):
    name = update.message.text.strip()

    # Перевірка: тільки літери і пробіли, мінімум 2 літери
    if not re.fullmatch(r"[A-Za-zА-Яа-яІіЇїЄєҐґ\s]+", name) or len(name.replace(" ", "")) < 2:
        update.message.reply_text("Введіть коректне ім'я (лише літери, мінімум 2 символи):")
        return NAME

    context.user_data['name'] = name
    districts = [[InlineKeyboardButton(d, callback_data=d)] for d in [
        "🏛 Галицький", "🏡 Франківський", "🌳 Сихівський",
        "🚉 Залізничний", "🌲 Шевченківський", "🏰 Личаківський", "🏘 Околиці"
    ]]
    update.message.reply_text("Оберіть район:", reply_markup=InlineKeyboardMarkup(districts))
    return DISTRICT


def get_district(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    context.user_data['district'] = query.data
    context.bot.send_message(chat_id=query.from_user.id, text="Введіть, будь ласка, адресу доставки:")
    return STREET

def normalize_street(text):
    text = text.lower()
    text = re.sub(r"^вул\\.?\\s*|вулиця\\s*", "", text)
    text = re.sub(r"\\s+\\d+.*", "", text)
    return text.strip()

def get_street(update: Update, context: CallbackContext):
    user_input = update.message.text.strip()
    street = normalize_street(user_input)
    if len(street) < 3:
        update.message.reply_text("Введіть коректну назву вулиці (мінімум 3 символи):")
        return STREET
    context.user_data['street'] = user_input
    update.message.reply_text("Введіть, будь ласка, свій номер телефону:")
    return PHONE

def get_phone(update: Update, context: CallbackContext):
    phone = update.message.text.strip().replace(" ", "")
    pattern = r'^(\+?380|0)?(67|68|96|97|98|77|50|66|95|99|75|63|73|93)\d{7}$'
    if not re.match(pattern, phone):
        update.message.reply_text("Невірний формат. Приклад: 067xxxxxxx або +38067xxxxxxx")
        return PHONE
    context.user_data['phone'] = phone

    keyboard = [
        [InlineKeyboardButton("1 доба", callback_data="duration_1")],
        [InlineKeyboardButton("2 доби", callback_data="duration_2")]
    ]
    update.message.reply_text("На скільки днів хочете забронювати?", reply_markup=InlineKeyboardMarkup(keyboard))
    return DURATION

def handle_duration(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    duration = int(query.data.split("_")[1])
    context.user_data['duration'] = duration
    query.edit_message_text("Оберіть дату початку бронювання:", reply_markup=generate_week_buttons())
    return DATE

def confirm_booking(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = context.user_data

    if query.data == 'confirm':
        cell = sheet.find(data['selected_date'])
        duration = data.get('duration', 1)

        # Перевірити доступність кожного дня в діапазоні
        for i in range(duration):
            row = cell.row + i
            status = sheet.cell(row, 2).value.strip().lower()
            if status != 'вільна':
                query.edit_message_text(
                    f"На жаль, дата {sheet.cell(row, 1).value} недоступна для бронювання. Будь ласка, оберіть інші дати.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Повернутись до вибору дати", callback_data="retry_date")]
                    ])
                )
                return CONFIRM

        # Оновити дані для всіх днів
        for i in range(duration):
            row = cell.row + i
            sheet.update(f"C{row}:F{row}", [[data['name'], '', data['phone'], f"{data['district']} - {data['street']}"]])
            sheet.update_cell(row, 2, 'заброньована')

        query.edit_message_text(
            f"Бронювання з {data['selected_date']} {'на 2 доби' if duration == 2 else 'на 1 добу'} підтверджено! Будь ласка, очікуйте дзвінка від менеджера.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Повернутись в меню", callback_data="menu")]])
        )

        context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"НОВЕ БРОНЮВАННЯ:\n"
                f"Дата: {data['selected_date']} ({duration} доба/доб)\n"
                f"{data['name']}\n"
                f"Телефон: {data['phone']}\n"
                f"Адреса: {data['district']} - {data['street']}"
            )
        )
        return ConversationHandler.END

    elif query.data == 'retry_date':
        query.edit_message_text("Оберіть дату початку бронювання:", reply_markup=generate_week_buttons())
        return DATE

    elif query.data == 'cancel':
        query.edit_message_text(
            "Бронювання скасовано.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 Повернутись в меню", callback_data="menu")]])
        )
        return ConversationHandler.END

def cancel(update: Update, context: CallbackContext):
    if update.callback_query:
        update.callback_query.answer()
        update.callback_query.edit_message_text("Бронювання скасовано.")
    else:
        update.message.reply_text("Бронювання скасовано.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- MAIN ---
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", show_start_button))
    dp.add_handler(MessageHandler(Filters.regex("^📋 Меню$"), start))

    # Перенесення обробника кнопок меню окремо
    dp.add_handler(CallbackQueryHandler(handle_info_buttons, pattern='^(rules|payment|manual|menu)$'))

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(handle_info_buttons, pattern='^book_now$')
        ],
        states={
            DATE: [
                CallbackQueryHandler(select_date, pattern='^select_.*$'),
                CallbackQueryHandler(select_date, pattern='^(next_week|current_week|disabled)$')
            ],
            NAME: [MessageHandler(Filters.text & ~Filters.command, get_name)],
            DISTRICT: [CallbackQueryHandler(get_district)],
            STREET: [MessageHandler(Filters.text & ~Filters.command, get_street)],
            PHONE: [MessageHandler(Filters.text & ~Filters.command, get_phone)],
            DURATION: [CallbackQueryHandler(handle_duration, pattern='^duration_')],
            CONFIRM: [
                CallbackQueryHandler(confirm_booking, pattern='^confirm$'),
                CallbackQueryHandler(confirm_booking, pattern='^cancel$'),
                CallbackQueryHandler(confirm_booking, pattern='^retry_date$'),
    ]
},
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern='^cancel$')
        ],
        allow_reentry=True
    )

    dp.add_handler(conv_handler)
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
