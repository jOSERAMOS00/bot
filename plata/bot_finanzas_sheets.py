from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta
import os
import json

# ───── CONFIGURACIÓN GENERAL ─────
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SPREADSHEET_ID = os.getenv('GOOGLE_SPREADSHEET_ID')
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_FILE_CONTENT')

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("La variable de entorno 'TELEGRAM_BOT_TOKEN' no está configurada.")
if not SPREADSHEET_ID:
    raise ValueError("La variable de entorno 'GOOGLE_SPREADSHEET_ID' no está configurada.")
if not GOOGLE_CREDENTIALS_JSON:
    raise ValueError("La variable de entorno 'GOOGLE_CREDENTIALS_FILE_CONTENT' no está configurada.")

SHEET_NAME_PERSONAL = 'Personal-Cris'
SHEET_NAME_NEGOCIOS = 'Negocios'

MENU_PRINCIPAL = 0
TIPO_CUENTA = 1
TIPO_MOVIMIENTO = 2
DESCRIPCION = 3
MONTO = 4
FECHA = 5
VER_SALDO_SELECCION_CUENTA = 6
VER_ULTIMOS_MOVIMIENTOS_SELECCION_CUENTA = 7

# ───── CONEXIÓN A GOOGLE SHEETS ─────
scopes = ["https://www.googleapis.com/auth/spreadsheets"]

try:
    credentials_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    credentials = Credentials.from_service_account_info(credentials_info, scopes=scopes)
    client = gspread.authorize(credentials)
except json.JSONDecodeError as e:
    print(f"Error al decodificar las credenciales JSON: {e}")
    exit()
except Exception as e:
    print(f"Error al autenticar con Google Sheets: {e}")
    exit()

try:
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    sheet_personal = spreadsheet.worksheet(SHEET_NAME_PERSONAL)
    sheet_negocios = spreadsheet.worksheet(SHEET_NAME_NEGOCIOS)
except gspread.exceptions.WorksheetNotFound as e:
    print(f"Error: {e}")
    exit()
except Exception as e:
    print(f"Error general: {e}")
    exit()

# ───── FUNCIONES AUXILIARES ─────
def guardar_en_sheet(sheet_object, data):
    row_data = [
        data.get("movimiento", ""),
        data.get("descripcion", ""),
        data.get("monto", ""),
        data.get("fecha", "")
    ]
    try:
        sheet_object.append_row(row_data)
    except Exception as e:
        print(f"Error al guardar en {sheet_object.title}: {e}")

def calcular_saldo_desde_movimientos(sheet_object):
    saldo_actual = 0.0
    try:
        all_data = sheet_object.get_all_values()
        if not all_data or len(all_data) < 2: 
            return 0.0
        for row_index, row in enumerate(all_data):
            if row_index == 0:
                continue
            if len(row) > 2:
                try:
                    movimiento_tipo = row[0].strip().lower()
                    monto_str = row[2].strip().replace(',', '')
                    monto = int(float(monto_str))
                    if movimiento_tipo == "crédito":
                        saldo_actual += monto
                    elif movimiento_tipo == "débito":
                        saldo_actual -= monto
                except (ValueError, IndexError):
                    continue
        return saldo_actual
    except Exception as e:
        print(f"Error al calcular saldo: {e}")
        return 0.0

def obtener_ultimos_movimientos(sheet_object, num_movimientos=10):
    try:
        all_data = sheet_object.get_all_values()
        if not all_data or len(all_data) < 2:
            return []
        recent_moves = all_data[1:][-num_movimientos:][::-1] 
        formatted_moves = []
        for move in recent_moves:
            movimiento = move[0] if len(move) > 0 else "N/A"
            descripcion = move[1] if len(move) > 1 else "Sin descripción"
            monto = f"${int(float(move[2])):,}" if len(move) > 2 and move[2].strip() else "$0"
            fecha = move[3] if len(move) > 3 else "Fecha desconocida"
            formatted_moves.append(f"• Fecha: {fecha} | Tipo: {movimiento.upper()} | Monto: {monto} | Desc: {descripcion}")
        return formatted_moves
    except Exception as e:
        print(f"Error al obtener últimos movimientos: {e}")
        return []

async def salir_desde_cualquier_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Sesión finalizada. Gracias por usar el gestor financiero.")
    return ConversationHandler.END

# ───── MANEJADORES ─────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_keyboard = [["1", "2"], ["3", "4"], ["Salir"]]
    await update.message.reply_text(
        "👋 Bienvenido. ¿Qué desea hacer?\n\n"
        "1️⃣ Registrar un nuevo movimiento\n"
        "2️⃣ Consultar saldo\n"
        "3️⃣ Ver historial de movimientos\n"
        "4️⃣ Otra opción\n"
        "➡️ Salir",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    context.user_data["temp_data"] = {}
    context.user_data["selected_sheet"] = None
    return MENU_PRINCIPAL

async def menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opcion = update.message.text.strip().lower()
    if opcion == "salir":
        return await salir_desde_cualquier_estado(update, context)
    if opcion == "1":
        reply_keyboard = [["1", "2"], ["Salir"]]
        await update.message.reply_text(
            "Seleccione la cuenta:\n1️⃣ Personal\n2️⃣ Negocio",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return TIPO_CUENTA
    elif opcion == "2":
        reply_keyboard = [["1", "2"], ["Salir"]]
        await update.message.reply_text(
            "Seleccione la cuenta para ver saldo:\n1️⃣ Personal\n2️⃣ Negocio",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return VER_SALDO_SELECCION_CUENTA
    elif opcion == "3":
        reply_keyboard = [["1", "2"], ["Salir"]]
        await update.message.reply_text(
            "Seleccione la cuenta para ver historial:\n1️⃣ Personal\n2️⃣ Negocio",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return VER_ULTIMOS_MOVIMIENTOS_SELECCION_CUENTA
    else:
        await update.message.reply_text("❌ Opción inválida.")
        return MENU_PRINCIPAL

async def tipo_cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opcion = update.message.text.strip().lower()
    if opcion == "salir":
        return await salir_desde_cualquier_estado(update, context)
    selected_sheet_obj = None
    account_name = ""
    if opcion == "1":
        selected_sheet_obj = sheet_personal
        account_name = SHEET_NAME_PERSONAL
    elif opcion == "2":
        selected_sheet_obj = sheet_negocios
        account_name = SHEET_NAME_NEGOCIOS
    else:
        await update.message.reply_text("❌ Opción inválida.")
        return TIPO_CUENTA
    context.user_data["selected_sheet"] = selected_sheet_obj
    context.user_data.setdefault("temp_data", {})["account_name"] = account_name
    reply_keyboard = [["1", "2"], ["Salir"]]
    await update.message.reply_text(
        "Tipo de movimiento:\n1️⃣ Crédito (+)\n2️⃣ Débito (-)",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return TIPO_MOVIMIENTO

async def tipo_movimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opcion = update.message.text.strip().lower()
    if opcion == "salir":
        return await salir_desde_cualquier_estado(update, context)
    movimiento = "Crédito" if opcion == "1" else "Débito" if opcion == "2" else None
    if not movimiento:
        await update.message.reply_text("❌ Opción inválida.")
        return TIPO_MOVIMIENTO
    context.user_data.setdefault("temp_data", {})["movimiento"] = movimiento
    await update.message.reply_text("✍️ Ingrese descripción:")
    return DESCRIPCION

async def descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower() == "salir":
        return await salir_desde_cualquier_estado(update, context)
    context.user_data.setdefault("temp_data", {})["descripcion"] = update.message.text
    opciones_monto = [["10000", "20000", "50000"], ["Salir"]]
    await update.message.reply_text(
        "💲 Ingrese el monto o elija una opción:",
        reply_markup=ReplyKeyboardMarkup(opciones_monto, one_time_keyboard=True, resize_keyboard=True)
    )
    return MONTO

async def monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower() == "salir":
        return await salir_desde_cualquier_estado(update, context)
    try:
        monto_valor = int(update.message.text.strip())
        if monto_valor <= 0:
            raise ValueError
        context.user_data.setdefault("temp_data", {})["monto"] = monto_valor
    except ValueError:
        await update.message.reply_text("❌ Ingrese un número válido.")
        return MONTO
    reply_keyboard_fecha = [["Hoy", "Ayer", "Anteayer"], ["Salir"]]
    await update.message.reply_text(
        "🗓️ Seleccione o ingrese la fecha (YYYY-MM-DD):",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard_fecha, one_time_keyboard=True, resize_keyboard=True)
    )
    return FECHA

async def fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower() == "salir":
        return await salir_desde_cualquier_estado(update, context)
    fecha_str_input = update.message.text.strip().lower()
    today = datetime.today()
    if fecha_str_input == "hoy":
        fecha_a_guardar = today.strftime('%Y-%m-%d')
    elif fecha_str_input == "ayer":
        fecha_a_guardar = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    elif fecha_str_input == "anteayer":
        fecha_a_guardar = (today - timedelta(days=2)).strftime('%Y-%m-%d')
    else:
        try:
            datetime.strptime(fecha_str_input, '%Y-%m-%d')
            fecha_a_guardar = fecha_str_input
        except ValueError:
            await update.message.reply_text("❌ Fecha inválida.")
            return FECHA
    user_temp_data = context.user_data["temp_data"]
    user_temp_data["fecha"] = fecha_a_guardar
    selected_sheet_obj = context.user_data.get("selected_sheet")
    guardar_en_sheet(selected_sheet_obj, user_temp_data)
    saldo_actual = calcular_saldo_desde_movimientos(selected_sheet_obj)
    reply_keyboard = [["1", "2"], ["3", "4"], ["Salir"]]
    await update.message.reply_text(
        f"✅ Movimiento registrado.\n💰 Saldo actual: ${saldo_actual:,.0f}\n\n¿Qué desea hacer ahora?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return MENU_PRINCIPAL

async def ver_saldo_seleccion_cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower() == "salir":
        return await salir_desde_cualquier_estado(update, context)
    opcion = update.message.text.strip()
    if opcion == "1":
        saldo = calcular_saldo_desde_movimientos(sheet_personal)
        cuenta = SHEET_NAME_PERSONAL
    elif opcion == "2":
        saldo = calcular_saldo_desde_movimientos(sheet_negocios)
        cuenta = SHEET_NAME_NEGOCIOS
    else:
        await update.message.reply_text("❌ Opción inválida.")
        return VER_SALDO_SELECCION_CUENTA
    await update.message.reply_text(f"💰 Saldo en {cuenta}: ${saldo:,.0f}")
    return await start(update, context)

async def ver_ultimos_movimientos_seleccion_cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower() == "salir":
        return await salir_desde_cualquier_estado(update, context)
    opcion = update.message.text.strip()
    if opcion == "1":
        movimientos = obtener_ultimos_movimientos(sheet_personal)
        cuenta = SHEET_NAME_PERSONAL
    elif opcion == "2":
        movimientos = obtener_ultimos_movimientos(sheet_negocios)
        cuenta = SHEET_NAME_NEGOCIOS
    else:
        await update.message.reply_text("❌ Opción inválida.")
        return VER_ULTIMOS_MOVIMIENTOS_SELECCION_CUENTA
    if movimientos:
        await update.message.reply_text("\n".join(movimientos))
    else:
        await update.message.reply_text(f"No hay movimientos en {cuenta}.")
    return await start(update, context)

# ───── INICIAR EL BOT ─────
def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MENU_PRINCIPAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, menu_principal)],
            TIPO_CUENTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, tipo_cuenta)],
            TIPO_MOVIMIENTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, tipo_movimiento)],
            DESCRIPCION: [MessageHandler(filters.TEXT & ~filters.COMMAND, descripcion)],
            MONTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, monto)],
            FECHA: [MessageHandler(filters.TEXT & ~filters.COMMAND, fecha)],
            VER_SALDO_SELECCION_CUENTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, ver_saldo_seleccion_cuenta)],
            VER_ULTIMOS_MOVIMIENTOS_SELECCION_CUENTA: [MessageHandler(filters.TEXT & ~filters.COMMAND, ver_ultimos_movimientos_seleccion_cuenta)],
        },
        fallbacks=[CommandHandler("start", start)]
    )
    application.add_handler(conv_handler)
    print("Bot iniciado...")
    application.run_polling()

if __name__ == "__main__":
    main()
