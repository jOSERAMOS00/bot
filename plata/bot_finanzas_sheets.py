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
# Obtener el token del bot de Telegram desde las variables de entorno
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
# Obtener el ID de la hoja de cálculo de Google desde las variables de entorno
SPREADSHEET_ID = os.getenv('GOOGLE_SPREADSHEET_ID')
# Obtener el contenido JSON de las credenciales de servicio desde las variables de entorno
GOOGLE_CREDENTIALS_JSON = os.getenv('GOOGLE_CREDENTIALS_FILE_CONTENT')

# Verificar que las variables de entorno estén configuradas
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("La variable de entorno 'TELEGRAM_BOT_TOKEN' no está configurada.")
if not SPREADSHEET_ID:
    raise ValueError("La variable de entorno 'GOOGLE_SPREADSHEET_ID' no está configurada.")
if not GOOGLE_CREDENTIALS_JSON:
    raise ValueError("La variable de entorno 'GOOGLE_CREDENTIALS_FILE_CONTENT' no está configurada.")

# Define los nombres exactos de sus dos hojas/pestañas en Google Sheets
SHEET_NAME_PERSONAL = 'Personal-Cris'
SHEET_NAME_NEGOCIOS = 'Negocios'

# ───── MAPEO DE COLUMNAS PARA REGISTROS EN CADA HOJA ─────
# Estos son los encabezados que DEBEN estar en la fila 1 de CADA UNA de sus hojas (Personal y Negocios):
# A             B           C       D
# movimiento | descripcion | monto | fecha

# ───── ESTADOS DE CONVERSACIÓN ─────
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

# Cargar credenciales desde la variable de entorno JSON
try:
    credentials_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    credentials = Credentials.from_service_account_info(credentials_info, scopes=scopes)
    client = gspread.authorize(credentials)
except json.JSONDecodeError as e:
    print(f"Error al decodificar las credenciales JSON desde la variable de entorno: {e}")
    exit()
except Exception as e:
    print(f"Error al autenticar con Google Sheets: {e}")
    exit()

# Abre la hoja de cálculo principal una sola vez al inicio
try:
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    print(f"Conexión a Google Spreadsheet exitosa: {spreadsheet.title}")
except gspread.exceptions.SpreadsheetNotFound:
    print(f"Error: No se encontró la hoja de cálculo con ID '{SPREADSHEET_ID}'. Verifique el ID.")
    exit()

# Abre las dos hojas/pestañas específicas
try:
    sheet_personal = spreadsheet.worksheet(SHEET_NAME_PERSONAL)
    print(f"Pestaña '{SHEET_NAME_PERSONAL}' conectada.")
except gspread.exceptions.WorksheetNotFound:
    print(f"Error: No se encontró la pestaña '{SHEET_NAME_PERSONAL}'. ¡Cree una pestaña con ese nombre exacto!")
    exit()

try:
    sheet_negocios = spreadsheet.worksheet(SHEET_NAME_NEGOCIOS)
    print(f"Pestaña '{SHEET_NAME_NEGOCIOS}' conectada.")
except gspread.exceptions.WorksheetNotFound:
    print(f"Error: No se encontró la pestaña '{SHEET_NAME_NEGOCIOS}'. ¡Cree una pestaña con ese nombre exacto!")
    exit()
except Exception as e:
    print(f"Error general al conectar con Google Sheets: {e}")
    exit()

# ───── FUNCIONES DE LÓGICA ─────
def guardar_en_sheet(sheet_object, data):
    """
    Guarda los datos del movimiento en la siguiente fila disponible de la hoja especificada.
    Los datos se insertarán en el orden: movimiento, descripcion, monto, fecha.
    """
    row_data = [
        data.get("movimiento", ""),
        data.get("descripcion", ""),
        data.get("monto", ""),
        data.get("fecha", "")
    ]
    try:
        sheet_object.append_row(row_data)
        print(f"Datos guardados en '{sheet_object.title}': {row_data}")
    except Exception as e:
        print(f"Error al guardar en Google Sheets (pestaña {sheet_object.title}): {e}")

def calcular_saldo_desde_movimientos(sheet_object):
    """
    Calcula el saldo actual sumando/restando todos los movimientos de la hoja especificada.
    Asume que 'Movimiento' está en columna A (índice 0) y 'Monto' en columna C (índice 2).
    """
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
        print(f"Error al calcular saldo desde movimientos para '{sheet_object.title}': {e}")
        return 0.0

def obtener_ultimos_movimientos(sheet_object, num_movimientos=10):
    """
    Obtiene los últimos 'num_movimientos' de la hoja especificada.
    """
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
            
            formatted_moves.append(f"• Fecha: {fecha} | Tipo: {movimiento.upper()} | Monto: {monto} | Descripción: {descripcion}")
        
        return formatted_moves
    except Exception as e:
        print(f"Error al obtener últimos movimientos para '{sheet_object.title}': {e}")
        return []

# ───── MANEJADORES DE BOT ─────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia la conversación y muestra el menú principal."""
    reply_keyboard = [["1", "2"], ["3", "4"]]
    await update.message.reply_text(
        "👋 Bienvenido. ¿Qué desea hacer?\n\n"
        "1️⃣ Registrar un nuevo movimiento\n"
        "2️⃣ Consultar saldo\n"
        "3️⃣ Finalizar sesión\n"
        "4️⃣ Ver historial de movimientos",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    context.user_data["temp_data"] = {}
    context.user_data["selected_sheet"] = None
    return MENU_PRINCIPAL

async def menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del menú principal."""
    opcion = update.message.text.strip()

    if opcion == "1": # Registrar movimiento
        reply_keyboard = [["1", "2"]]
        await update.message.reply_text(
            "📝 Por favor, seleccione la cuenta para el registro:\n"
            "1️⃣ Personal\n"
            "2️⃣ Negocio",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return TIPO_CUENTA

    elif opcion == "2": # Ver saldo
        reply_keyboard = [["1", "2"]]
        await update.message.reply_text(
            "📊 Por favor, seleccione la cuenta para consultar el saldo:\n"
            "1️⃣ Personal\n"
            "2️⃣ Negocio",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return VER_SALDO_SELECCION_CUENTA

    elif opcion == "3": # Salir
        await update.message.reply_text("👋 Sesión finalizada. Gracias por usar el gestor financiero.")
        return ConversationHandler.END
    
    elif opcion == "4": # Ver últimos movimientos
        reply_keyboard = [["1", "2"]]
        await update.message.reply_text(
            "🔎 Por favor, seleccione la cuenta para ver el historial:\n"
            "1️⃣ Personal\n"
            "2️⃣ Negocio",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return VER_ULTIMOS_MOVIMIENTOS_SELECCION_CUENTA

    else:
        await update.message.reply_text("❌ Opción inválida. Por favor, elija una de las opciones numéricas.")
        return MENU_PRINCIPAL

async def tipo_cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja la selección del tipo de cuenta (Personal/Negocio) para registrar un movimiento.
    Guarda la referencia a la hoja de Google Sheets seleccionada.
    """
    opcion = update.message.text.strip()
    
    selected_sheet_obj = None
    account_name = ""

    if opcion == "1":
        selected_sheet_obj = sheet_personal
        account_name = SHEET_NAME_PERSONAL
    elif opcion == "2":
        selected_sheet_obj = sheet_negocios
        account_name = SHEET_NAME_NEGOCIOS
    else:
        await update.message.reply_text("❌ Opción inválida. Por favor, elija 1 para Personal o 2 para Negocio.")
        return TIPO_CUENTA

    context.user_data["selected_sheet"] = selected_sheet_obj
    context.user_data.setdefault("temp_data", {})["account_name"] = account_name

    reply_keyboard = [["1", "2"]]
    await update.message.reply_text(
        "➡️ Indique el tipo de movimiento:\n"
        "1️⃣ Crédito (+)\n"
        "2️⃣ Débito (-)",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return TIPO_MOVIMIENTO

async def tipo_movimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pregunta por el tipo de movimiento (Crédito/Débito)."""
    opcion = update.message.text.strip()
    movimiento = "Crédito" if opcion == "1" else "Débito" if opcion == "2" else None

    if not movimiento:
        await update.message.reply_text("❌ Opción inválida. Por favor, elija 1 para Crédito o 2 para Débito.")
        return TIPO_MOVIMIENTO

    context.user_data.setdefault("temp_data", {})["movimiento"] = movimiento
    await update.message.reply_text("✍️ Por favor, ingrese una descripción para el movimiento:")
    return DESCRIPCION

async def descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Solicita la descripción del movimiento y luego el monto con opciones preestablecidas."""
    context.user_data.setdefault("temp_data", {})["descripcion"] = update.message.text
    
    # Define SOLO las opciones de monto preestablecidas para este paso
    opciones_monto = [["10000", "20000", "50000"]] # Los montos como strings para los botones

    await update.message.reply_text(
        "💲 Por favor, ingrese el monto (número entero sin decimales):\n"
        "O elija una opción rápida:", # Mensaje actualizado
        reply_markup=ReplyKeyboardMarkup(opciones_monto, one_time_keyboard=True, resize_keyboard=True) # Usamos solo opciones_monto
    )
    return MONTO

async def monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Solicita el monto del movimiento y valida que sea un número entero positivo.
    Ahora también acepta montos preestablecidos.
    """
    monto_str_input = update.message.text.strip()
    monto_valor = None
    
    # Opciones de monto preestablecidas como strings para comparación y para mostrar en caso de error
    predefined_amounts_str = ["10000", "20000", "50000"]
    opciones_monto_keyboard = [predefined_amounts_str] # Para reutilizar en el teclado de respuesta

    try:
        # Primero, intenta si la entrada es uno de los montos preestablecidos
        if monto_str_input in predefined_amounts_str:
            monto_valor = int(monto_str_input) # Si es preestablecido, ya sabemos que es un entero válido
        else:
            # Si no es preestablecido, intenta convertirlo a entero y validar
            monto_valor = int(monto_str_input)

        # Validar que sea positivo
        if monto_valor <= 0:
            await update.message.reply_text(
                "❌ Monto inválido. Debe ser un número entero positivo. Intente de nuevo:",
                reply_markup=ReplyKeyboardMarkup(opciones_monto_keyboard, one_time_keyboard=True, resize_keyboard=True)
            )
            return MONTO # Quédate en este estado
            
        context.user_data.setdefault("temp_data", {})["monto"] = monto_valor
    except ValueError:
        # Esto captura errores si el input no es un número entero (ej. texto, decimales)
        await update.message.reply_text(
            "❌ Monto inválido. Debe ser un número entero y sin decimales (ej. 100, 500). Intente de nuevo:",
            reply_markup=ReplyKeyboardMarkup(opciones_monto_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return MONTO # Quédate en este estado

    # Si el monto es válido (sea preestablecido o manual), procede a pedir la fecha
    # Aquí es donde se muestran SOLO las opciones de fecha
    reply_keyboard_fecha = [["Hoy", "Ayer", "Anteayer"]]
    await update.message.reply_text(
        "🗓️ Seleccione o ingrese la fecha del movimiento (YYYY-MM-DD):",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard_fecha, one_time_keyboard=True, resize_keyboard=True)
    )
    return FECHA

async def fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja la selección o entrada de la fecha del movimiento, guarda el movimiento,
    y muestra el saldo actualizado de la hoja.
    """
    fecha_str_input = update.message.text.strip().lower()
    fecha_a_guardar = ""
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
            reply_keyboard_fecha = [["Hoy", "Ayer", "Anteayer"]] # Definir de nuevo para el error
            await update.message.reply_text(
                "❌ Formato de fecha inválido. Por favor, elija una opción o ingrese la fecha en formato YYYY-MM-DD:",
                reply_markup=ReplyKeyboardMarkup(reply_keyboard_fecha, one_time_keyboard=True, resize_keyboard=True)
            )
            return FECHA

    user_temp_data = context.user_data.setdefault("temp_data", {})
    user_temp_data["fecha"] = fecha_a_guardar
    
    selected_sheet_obj = context.user_data.get("selected_sheet")
    account_name = user_temp_data.get("account_name", "la cuenta seleccionada") 

    if not selected_sheet_obj:
        await update.message.reply_text("❌ Error: No se seleccionó una cuenta. Por favor, reinicie con /start.")
        return ConversationHandler.END 

    guardar_en_sheet(selected_sheet_obj, user_temp_data)

    saldo_actual = calcular_saldo_desde_movimientos(selected_sheet_obj)
    
    if "temp_data" in context.user_data:
        del context.user_data["temp_data"] 
    if "selected_sheet" in context.user_data:
        del context.user_data["selected_sheet"]

    reply_keyboard = [["1", "2"], ["3", "4"]]
    await update.message.reply_text(
        f"✅ Movimiento registrado exitosamente en '{account_name}'.\n"
        f"💰 Su saldo actual en '{account_name}' es: ${saldo_actual:,.0f}\n\n"
        f"¿Qué desea hacer ahora?\n"
        "1️⃣ Registrar un nuevo movimiento\n"
        "2️⃣ Consultar saldo\n"
        "3️⃣ Finalizar sesión\n"
        "4️⃣ Ver historial de movimientos",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return MENU_PRINCIPAL

async def ver_saldo_seleccion_cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja la selección de cuenta solo para ver el saldo.
    """
    opcion = update.message.text.strip()
    
    selected_sheet_for_saldo = None
    account_name = ""

    if opcion == "1":
        selected_sheet_for_saldo = sheet_personal
        account_name = SHEET_NAME_PERSONAL
    elif opcion == "2":
        selected_sheet_for_saldo = sheet_negocios
        account_name = SHEET_NAME_NEGOCIOS
    else:
        await update.message.reply_text("❌ Opción inválida. Por favor, elija 1 para Personal o 2 para Negocio.")
        return VER_SALDO_SELECCION_CUENTA 

    if selected_sheet_for_saldo:
        saldo = calcular_saldo_desde_movimientos(selected_sheet_for_saldo)
        await update.message.reply_text(f"💰 Su saldo actual en '{account_name}' es: ${saldo:,.0f}")
    else:
        await update.message.reply_text("🚫 Hubo un error al seleccionar la cuenta. Por favor, intente de nuevo.")
    
    return await start(update, context)


async def ver_ultimos_movimientos_seleccion_cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja la selección de cuenta para ver los últimos movimientos y los muestra.
    """
    opcion = update.message.text.strip()
    
    selected_sheet_for_moves = None
    account_name = ""

    if opcion == "1":
        selected_sheet_for_moves = sheet_personal
        account_name = SHEET_NAME_PERSONAL
    elif opcion == "2":
        selected_sheet_for_moves = sheet_negocios
        account_name = SHEET_NAME_NEGOCIOS
    else:
        await update.message.reply_text("❌ Opción inválida. Por favor, elija 1 para Personal o 2 para Negocio.")
        return VER_ULTIMOS_MOVIMIENTOS_SELECCION_CUENTA

    if selected_sheet_for_moves:
        ultimos_movimientos = obtener_ultimos_movimientos(selected_sheet_for_moves, num_movimientos=10)
        
        if ultimos_movimientos:
            moves_text = "\n".join(ultimos_movimientos)
            await update.message.reply_text(
                f"📄 **Historial de Movimientos Recientes en '{account_name}':**\n\n"
                f"| Fecha       | Tipo     | Monto    | Descripción             |\n"
                f"|:------------|:---------|:---------|:------------------------|\n"
                f"{moves_text}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"No hay movimientos registrados en '{account_name}' aún.")
    else:
        await update.message.reply_text("🚫 Hubo un error al seleccionar la cuenta. Por favor, intente de nuevo.")
    
    return await start(update, context)


# ───── INICIAR EL BOT ─────
def main():
    """Configura y ejecuta el bot de Telegram."""
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, start) 
        ],
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
    
    print("Bot iniciando... Presione Ctrl+C para detener.")
    application.run_polling()

if __name__ == "__main__":
    main()
