import re
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

SHEET_NAME_PERSONAL = 'Personal-Cris' # Asegúrate que este nombre es correcto en tu Google Sheet
SHEET_NAME_NEGOCIOS = 'Negocios'      # Asegúrate que este nombre es correcto en tu Google Sheet

# ───── ESTADOS DE CONVERSACIÓN ─────
MENU_PRINCIPAL = 0
TIPO_CUENTA = 1
TIPO_MOVIMIENTO = 2
DESCRIPCION = 3
MONTO = 4
FECHA = 5
VER_SALDO_SELECCION_CUENTA = 6
VER_ULTIMOS_MOVIMIENTOS_SELECCION_CUENTA = 7

# ───── VALOR PARA VOLVER AL MENÚ ─────
VOLVER_AL_MENU_OPTION = "0"
FINALIZAR_SESION_OPTION = "5"

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
    print(f"Conexión exitosa a las hojas: '{SHEET_NAME_PERSONAL}' y '{SHEET_NAME_NEGOCIOS}'")
except gspread.exceptions.WorksheetNotFound as e:
    print(f"Error: Una de las hojas no se encontró. Asegúrese que los nombres '{SHEET_NAME_PERSONAL}' y '{SHEET_NAME_NEGOCIOS}' sean exactos. Detalle: {e}")
    exit()
except Exception as e:
    print(f"Error general al conectar con Google Sheets: {e}")
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
        print(f"Datos guardados en {sheet_object.title}: {row_data}")
    except Exception as e:
        print(f"Error al guardar en {sheet_object.title}: {e}")

def calcular_saldo_desde_movimientos(sheet_object):
    saldo_actual = 0.0
    try:
        all_data = sheet_object.get_all_values()
        if not all_data or len(all_data) < 2:  # No hay datos o solo el encabezado
            return 0.0
        # Empezar desde la segunda fila (índice 1) para omitir el encabezado
        for row_index, row in enumerate(all_data):
            if row_index == 0:
                continue # Saltar la primera fila (encabezado)
            
            # Asegurarse de que la fila tenga suficientes columnas
            if len(row) > 2:
                try:
                    movimiento_tipo = row[0].strip().lower()
                    # Eliminar comas para asegurar la correcta conversión a número
                    monto_str = row[2].strip().replace(',', '')
                    # Usar int(float()) para manejar montos que puedan estar como "100.0"
                    monto = int(float(monto_str))
                    
                    if movimiento_tipo == "crédito":
                        saldo_actual += monto
                    elif movimiento_tipo == "débito":
                        saldo_actual -= monto
                except (ValueError, IndexError):
                    # Ignorar filas con datos inválidos o faltantes
                    continue
        return saldo_actual
    except Exception as e:
        print(f"Error al calcular saldo: {e}")
        return 0.0

def obtener_ultimos_movimientos(sheet_object, num_movimientos=10):
    """
    Obtiene los últimos 'num_movimientos' de la hoja especificada.
    Devuelve una lista de listas, donde cada lista interna representa una fila
    con los datos formateados listos para ser alineados en el bloque <pre>.
    """
    try:
        all_data = sheet_object.get_all_values()
        if not all_data or len(all_data) < 2:
            return []
        
        # Obtener los últimos movimientos (sin el encabezado, y en orden cronológico inverso)
        recent_moves = all_data[1:][-num_movimientos:][::-1] # [::-1] para invertir el orden y ver los más recientes primero
        
        table_rows_raw = []
        for move in recent_moves:
            # Extraer y formatear cada pieza de dato
            movimiento = move[0].upper() if len(move) > 0 else "N/A"
            descripcion = move[1] if len(move) > 1 else "Sin descripción"
            
            monto_val_formatted = "0"
            if len(move) > 2 and move[2].strip():
                try:
                    # Formato de miles, sin el símbolo de dólar aún para calcular el ancho correctamente
                    monto_val_formatted = f"{int(float(move[2])):,}"
                except ValueError:
                    monto_val_formatted = "Error"
            
            fecha = move[3] if len(move) > 3 else "Fecha desconocida"
            
            # Añadir una lista con los valores de cada columna para esta fila
            table_rows_raw.append([fecha, movimiento, monto_val_formatted, descripcion])
        
        return table_rows_raw
    except Exception as e:
        print(f"Error al obtener últimos movimientos: {e}")
        return []

# Función auxiliar para escapar texto para MarkdownV2
def escape_markdown_v2(text: str) -> str:
    """Escapa caracteres especiales de MarkdownV2."""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(special_chars)}])', r'\\\1', text)

# ───── MANEJADORES DE CONVERSACIÓN ─────
async def salir_sesion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finaliza la conversación."""
    await update.message.reply_text("👋 Sesión finalizada\\. ¡Hasta pronto\\!", parse_mode='MarkdownV2')
    context.user_data.clear()
    return ConversationHandler.END

async def volver_al_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Regresa al menú principal desde cualquier estado, limpiando datos temporales."""
    context.user_data.pop("temp_data", None)
    context.user_data.pop("selected_sheet", None)
    
    await update.message.reply_text("🏠 Volviendo al menú principal\\.", parse_mode='MarkdownV2')
    return await start(update, context)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inicia la conversación y muestra el menú principal."""
    reply_keyboard = [
        ["1", "2"],
        ["3"],
        [FINALIZAR_SESION_OPTION]
    ]
    await update.message.reply_text(
        "👋 Bienvenido\\. ¿Qué desea hacer\\?\n\n"
        "1️⃣ Registrar un nuevo movimiento\n"
        "2️⃣ Consultar saldo\n"
        "3️⃣ Ver historial de movimientos\n"
        f"{FINALIZAR_SESION_OPTION}️⃣ Finalizar sesión",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode='MarkdownV2'
    )
    context.user_data["temp_data"] = {}
    context.user_data["selected_sheet"] = None
    return MENU_PRINCIPAL

async def menu_principal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Maneja la selección del menú principal."""
    opcion = update.message.text.strip()

    if opcion == FINALIZAR_SESION_OPTION:
        return await salir_sesion(update, context)
    elif opcion == "1":
        reply_keyboard = [["1", "2"], [VOLVER_AL_MENU_OPTION]]
        await update.message.reply_text(
            "📝 Por favor, seleccione la cuenta para el registro:\n"
            "1️⃣ Personal- Cris \n"
            "2️⃣ Negocio\n"
            f"{VOLVER_AL_MENU_OPTION}️⃣ Volver al menú",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return TIPO_CUENTA
    elif opcion == "2":
        reply_keyboard = [["1", "2"], [VOLVER_AL_MENU_OPTION]]
        await update.message.reply_text(
            "📊 Por favor, seleccione la cuenta para consultar el saldo:\n"
            "1️⃣ Personal-Cris\n"
            "2️⃣ Negocio\n"
            f"{VOLVER_AL_MENU_OPTION}️⃣ Volver al menú",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return VER_SALDO_SELECCION_CUENTA
    elif opcion == "3":
        reply_keyboard = [["1", "2"], [VOLVER_AL_MENU_OPTION]]
        await update.message.reply_text(
            "🔎 Por favor, seleccione la cuenta para ver el historial:\n"
            "1️⃣ Personal-Cris\n"
            "2️⃣ Negocio\n"
            f"{VOLVER_AL_MENU_OPTION}️⃣ Volver al menú",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return VER_ULTIMOS_MOVIMIENTOS_SELECCION_CUENTA
    else:
        await update.message.reply_text("❌ Opción inválida\\. Por favor, elija una de las opciones numéricas\\.", parse_mode='MarkdownV2')
        return MENU_PRINCIPAL

async def tipo_cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("❌ Opción inválida\\. Por favor, elija 1 para Personal o 2 para Negocio\\.", parse_mode='MarkdownV2')
        return TIPO_CUENTA

    context.user_data["selected_sheet"] = selected_sheet_obj
    context.user_data.setdefault("temp_data", {})["account_name"] = account_name

    reply_keyboard = [["1", "2"], [VOLVER_AL_MENU_OPTION]]
    await update.message.reply_text(
        "➡️ Indique el tipo de movimiento:\n"
        "1️⃣ Crédito \\(\\+\\)\n"
        "2️⃣ Débito \\(\\-\\)\n"
        f"{VOLVER_AL_MENU_OPTION}️⃣ Volver al menú",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode='MarkdownV2'
    )
    return TIPO_MOVIMIENTO

async def tipo_movimiento(update: Update, context: ContextTypes.DEFAULT_TYPE):
    opcion = update.message.text.strip()
        
    movimiento = "Crédito" if opcion == "1" else "Débito" if opcion == "2" else None

    if not movimiento:
        await update.message.reply_text("❌ Opción inválida\\. Por favor, elija 1 para Crédito o 2 para Débito\\.", parse_mode='MarkdownV2')
        return TIPO_MOVIMIENTO

    context.user_data.setdefault("temp_data", {})["movimiento"] = movimiento
    await update.message.reply_text(
        "✍️ Por favor, ingrese una descripción para el movimiento:\n"
        f"O escriba '{VOLVER_AL_MENU_OPTION}' para volver al menú\\.",
        parse_mode='MarkdownV2'
    )
    return DESCRIPCION

async def descripcion(update: Update, context: ContextTypes.DEFAULT_TYPE):
        
    context.user_data.setdefault("temp_data", {})["descripcion"] = update.message.text
    
    opciones_monto = [["10000", "20000", "50000"], [VOLVER_AL_MENU_OPTION]]

    await update.message.reply_text(
        "💲 Por favor, ingrese el monto \\(número entero sin decimales\\):\n"
        "O elija una opción rápida:\n"
        f"{VOLVER_AL_MENU_OPTION}️⃣ Volver al menú",
        reply_markup=ReplyKeyboardMarkup(opciones_monto, one_time_keyboard=True, resize_keyboard=True),
        parse_mode='MarkdownV2'
    )
    return MONTO

async def monto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    monto_str_input = update.message.text.strip()
        
    monto_valor = None
    
    predefined_amounts_str = ["10000", "20000", "50000"]
    opciones_monto_keyboard = [predefined_amounts_str, [VOLVER_AL_MENU_OPTION]]

    try:
        if monto_str_input in predefined_amounts_str:
            monto_valor = int(monto_str_input)
        else:
            cleaned_monto_str = monto_str_input.replace('$', '').replace(',', '')
            
            match = re.match(r'^-?\d+', cleaned_monto_str)
            if match:
                cleaned_monto_str = match.group(0)
            
            monto_valor = int(cleaned_monto_str)

        if monto_valor <= 0:
            await update.message.reply_text(
                "❌ Monto inválido\\. Debe ser un número entero positivo\\. Intente de nuevo:\n"
                f"O escriba '{VOLVER_AL_MENU_OPTION}' para volver al menú\\.",
                reply_markup=ReplyKeyboardMarkup(opciones_monto_keyboard, one_time_keyboard=True, resize_keyboard=True),
                parse_mode='MarkdownV2'
            )
            return MONTO
            
        context.user_data.setdefault("temp_data", {})["monto"] = monto_valor
    except ValueError:
        await update.message.reply_text(
            "❌ Monto inválido\\. Por favor, ingrese un número entero positivo sin decimales \\(ej\\. 100, 500, \\$2345, 2,345\\)\\. Intente de nuevo:\n"
            f"O escriba '{VOLVER_AL_MENU_OPTION}' para volver al menú\\.",
            reply_markup=ReplyKeyboardMarkup(opciones_monto_keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode='MarkdownV2'
        )
        return MONTO

    reply_keyboard_fecha = [["Hoy", "Ayer", "Anteayer"], [VOLVER_AL_MENU_OPTION]]
    await update.message.reply_text(
        "🗓️ Seleccione o ingrese la fecha del movimiento \\(YYYY\\-MM\\-DD\\):\n"
        f"{VOLVER_AL_MENU_OPTION}️⃣ Volver al menú",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard_fecha, one_time_keyboard=True, resize_keyboard=True),
        parse_mode='MarkdownV2'
    )
    return FECHA

async def fecha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fecha_str_input = update.message.text.strip()
        
    today = datetime.today()
    fecha_a_guardar = ""

    if fecha_str_input.lower() == "hoy":
        fecha_a_guardar = today.strftime('%Y-%m-%d')
    elif fecha_str_input.lower() == "ayer":
        fecha_a_guardar = (today - timedelta(days=1)).strftime('%Y-%m-%d')
    elif fecha_str_input.lower() == "anteayer":
        fecha_a_guardar = (today - timedelta(days=2)).strftime('%Y-%m-%d')
    else:
        try:
            datetime.strptime(fecha_str_input, '%Y-%m-%d')
            fecha_a_guardar = fecha_str_input
        except ValueError:
            reply_keyboard_fecha = [["Hoy", "Ayer", "Anteayer"], [VOLVER_AL_MENU_OPTION]]
            await update.message.reply_text(
                "❌ Formato de fecha inválido\\. Por favor, elija una opción o ingrese la fecha en formato YYYY\\-MM\\-DD:\n"
                f"O escriba '{VOLVER_AL_MENU_OPTION}' para volver al menú\\.",
                reply_markup=ReplyKeyboardMarkup(reply_keyboard_fecha, one_time_keyboard=True, resize_keyboard=True),
                parse_mode='MarkdownV2'
            )
            return FECHA

    user_temp_data = context.user_data.setdefault("temp_data", {})
    user_temp_data["fecha"] = fecha_a_guardar
    
    selected_sheet_obj = context.user_data.get("selected_sheet")
    account_name = user_temp_data.get("account_name", "la cuenta seleccionada") 

    if not selected_sheet_obj:
        await update.message.reply_text("❌ Error: No se seleccionó una cuenta\\. Por favor, reinicie con /start\\.", parse_mode='MarkdownV2')
        return ConversationHandler.END 

    guardar_en_sheet(selected_sheet_obj, user_temp_data)

    saldo_actual = calcular_saldo_desde_movimientos(selected_sheet_obj)
    
    context.user_data.pop("temp_data", None)
    context.user_data.pop("selected_sheet", None)

    reply_keyboard = [["1", "2"], ["3"], [FINALIZAR_SESION_OPTION]]
await update.message.reply_text(
    f"✅ Movimiento registrado exitosamente en *{escape_markdown_v2(account_name)}*.\n"
    f"💰 Su saldo actual en *{escape_markdown_v2(account_name)}* es: \\${saldo_actual:,.0f}\n\n\n\n"
    f"¿Qué desea hacer ahora?\n"
    "1️⃣ Registrar un nuevo movimiento\n"
    "2️⃣ Consultar saldo\n"
    "3️⃣ Ver historial de movimientos\n"
    f"{FINALIZAR_SESION_OPTION}️⃣ Finalizar sesión",
    reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True),
    parse_mode='MarkdownV2'
)

    return MENU_PRINCIPAL

async def ver_saldo_seleccion_cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        await update.message.reply_text("❌ Opción inválida\\. Por favor, elija 1 para Personal o 2 para Negocio\\.", parse_mode='MarkdownV2')
        return VER_SALDO_SELECCION_CUENTA 

    if selected_sheet_for_saldo:
        saldo = calcular_saldo_desde_movimientos(selected_sheet_for_saldo)
       await update.message.reply_text(f"💰 Su saldo actual en *{escape_markdown_v2(account_name)}* es: \\${saldo:,.0f}",
    parse_mode='MarkdownV2'
)

    else:
        await update.message.reply_text("🚫 Hubo un error al seleccionar la cuenta\\. Por favor, intente de nuevo\\.", parse_mode='MarkdownV2')
    
    return await start(update, context)

async def ver_ultimos_movimientos_seleccion_cuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Maneja la selección de cuenta para ver los últimos movimientos y los muestra en formato de texto pre-formateado.
    Esto asegura la alineación en la mayoría de los clientes de Telegram.
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
        await update.message.reply_text("❌ Opción inválida\\. Por favor, elija 1 para Personal o 2 para Negocio\\.", parse_mode='MarkdownV2')
        return VER_ULTIMOS_MOVIMIENTOS_SELECCION_CUENTA

    if selected_sheet_for_moves:
        ultimos_movimientos_data = obtener_ultimos_movimientos(selected_sheet_for_moves, num_movimientos=10)
        
        if ultimos_movimientos_data:
            headers = ["Fecha", "Tipo", "Monto", "Descripción"]
            
            max_widths = [len(h) for h in headers] 
            
            for row_data in ultimos_movimientos_data:
                fecha_raw = str(row_data[0]) if len(row_data) > 0 else ""
                tipo_raw = str(row_data[1]) if len(row_data) > 1 else ""
                monto_raw = "$" + str(row_data[2]) if len(row_data) > 2 else "" 
                descripcion_raw = str(row_data[3]) if len(row_data) > 3 else ""

                current_row_lengths = [len(fecha_raw), len(tipo_raw), len(monto_raw), len(descripcion_raw)]
                
                for i in range(len(max_widths)):
                    max_widths[i] = max(max_widths[i], current_row_lengths[i])

            formatted_header = (
                f"{headers[0].ljust(max_widths[0])}  "
                f"{headers[1].ljust(max_widths[1])}  "
                f"{headers[2].ljust(max_widths[2])}  "
                f"{headers[3].ljust(max_widths[3])}"
            )
            
            separator_line = (
                f"{'-' * max_widths[0]}  "
                f"{'-' * max_widths[1]}  "
                f"{'-' * max_widths[2]}  "
                f"{'-' * max_widths[3]}"
            )
            
            data_rows_formatted = []
            for row_data in ultimos_movimientos_data:
                fecha = str(row_data[0]) if len(row_data) > 0 else ""
                tipo = str(row_data[1]) if len(row_data) > 1 else ""
                monto = "$" + str(row_data[2]) if len(row_data) > 2 else ""
                descripcion = str(row_data[3]) if len(row_data) > 3 else ""
                
                formatted_row = (
                    f"{fecha.ljust(max_widths[0])}  "
                    f"{tipo.ljust(max_widths[1])}  "
                    f"{monto.ljust(max_widths[2])}  "
                    f"{descripcion.ljust(max_widths[3])}"
                )
                data_rows_formatted.append(formatted_row)

            moves_table_text = "\n".join([formatted_header, separator_line] + data_rows_formatted)

            escaped_account_name = escape_markdown_v2(account_name)

            await update.message.reply_text(
                f"📄 \\*\\*Historial de Movimientos Recientes en \\'{escaped_account_name}\\'\\:\\*\\*\n\n"
                f"```\n{moves_table_text}\n```",
                parse_mode='MarkdownV2' 
            )
        else:
            await update.message.reply_text(f"No hay movimientos registrados en \\'{escape_markdown_v2(account_name)}\\' aún\\.", parse_mode='MarkdownV2')
    else:
        await update.message.reply_text("🚫 Hubo un error al seleccionar la cuenta\\. Por favor, intente de nuevo\\.", parse_mode='MarkdownV2')
    
    return await start(update, context)

# ───── INICIAR EL BOT ─────
def main():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, start) 
        ],
        states={
            MENU_PRINCIPAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, menu_principal)
            ],
            TIPO_CUENTA: [
                MessageHandler(filters.Regex(f"^{re.escape(VOLVER_AL_MENU_OPTION)}$") & ~filters.COMMAND, volver_al_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, tipo_cuenta),
            ],
            TIPO_MOVIMIENTO: [
                MessageHandler(filters.Regex(f"^{re.escape(VOLVER_AL_MENU_OPTION)}$") & ~filters.COMMAND, volver_al_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, tipo_movimiento),
            ],
            DESCRIPCION: [
                MessageHandler(filters.Regex(f"^{re.escape(VOLVER_AL_MENU_OPTION)}$") & ~filters.COMMAND, volver_al_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, descripcion), # Se referencia la función 'descripcion' aquí
            ],
            MONTO: [
                MessageHandler(filters.Regex(f"^{re.escape(VOLVER_AL_MENU_OPTION)}$") & ~filters.COMMAND, volver_al_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, monto),
            ],
            FECHA: [
                MessageHandler(filters.Regex(f"^{re.escape(VOLVER_AL_MENU_OPTION)}$") & ~filters.COMMAND, volver_al_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, fecha),
            ],
            VER_SALDO_SELECCION_CUENTA: [
                MessageHandler(filters.Regex(f"^{re.escape(VOLVER_AL_MENU_OPTION)}$") & ~filters.COMMAND, volver_al_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ver_saldo_seleccion_cuenta),
            ],
            VER_ULTIMOS_MOVIMIENTOS_SELECCION_CUENTA: [
                MessageHandler(filters.Regex(f"^{re.escape(VOLVER_AL_MENU_OPTION)}$") & ~filters.COMMAND, volver_al_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ver_ultimos_movimientos_seleccion_cuenta),
            ],
        },
        fallbacks=[CommandHandler("start", start)]
    )

    application.add_handler(conv_handler)
    
    print("Bot iniciando... Presione Ctrl+C para detener.")
    application.run_polling()

if __name__ == "__main__":
    main()
