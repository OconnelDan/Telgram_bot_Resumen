import os
import sqlite3
import requests
import xml.etree.ElementTree as ET
import random
from datetime import datetime, timedelta, time
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    ContextTypes,
    filters
)
from telegram.error import BadRequest
from openai import OpenAI

# Configuración
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
BGG_API_TOKEN = os.environ.get('BGG_API_TOKEN')

# 🎲 BGG API Configuration
# Desde 2025, la XML API2 de BoardGameGeek requiere:
# - Token de aplicación en Authorization: Bearer <token>
# - Dominio sin www: https://boardgamegeek.com (no www.boardgamegeek.com)
BGG_API_BASE = "https://boardgamegeek.com/xmlapi2"

def bgg_headers() -> dict:
    """
    Cabeceras estándar para llamar a la XML API2 de BoardGameGeek.
    Incluye el token de aplicación en Authorization si está definido.
    """
    headers = {
        "User-Agent": "TelegramBGGBot/1.0 (Telegram Summary Bot)",
        "Accept": "application/xml",
    }
    if BGG_API_TOKEN:
        headers["Authorization"] = f"Bearer {BGG_API_TOKEN}"
    return headers

# 🔐 CONTROL DE ACCESO: Lista de IDs de grupos permitidos
# Para obtener el ID de un grupo, agrega el bot y usa /chatid
# Deja la lista vacía [] para permitir todos los grupos
GRUPOS_PERMITIDOS = [
    -1001660210142,  # BoardGames "La Sagra"
]

# Cliente de OpenAI
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Base de datos
DB_NAME = 'telegram_messages.db'

# Servidor web para Render (mantiene el bot activo)
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<h1>Bot de Telegram activo!</h1><p>El bot esta funcionando correctamente.</p>')
    
    def log_message(self, format, *args):
        pass  # Silenciar logs del servidor

def run_health_server():
    """Servidor HTTP para que Render mantenga el bot activo"""
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🌐 Servidor web iniciado en puerto {port}")
    server.serve_forever()

def inicializar_db():
    """Crea la base de datos y tablas necesarias"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Tabla de mensajes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mensajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            message_id INTEGER,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            texto TEXT,
            timestamp DATETIME,
            UNIQUE(chat_id, message_id)
        )
    ''')
    
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_chat_timestamp 
        ON mensajes(chat_id, timestamp)
    ''')
    
    # Tabla de preguntas automáticas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS preguntas_historial (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            pregunta_id INTEGER,
            timestamp DATETIME,
            UNIQUE(chat_id, pregunta_id, timestamp)
        )
    ''')
    
    # Tabla de caché de juegos BGG
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bgg_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_name TEXT,
            bgg_id INTEGER,
            image_url TEXT,
            min_players INTEGER,
            max_players INTEGER,
            best_players TEXT,
            playtime INTEGER,
            weight REAL,
            year_published INTEGER,
            rank INTEGER,
            bgg_link TEXT,
            timestamp DATETIME,
            UNIQUE(game_name)
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada")

# ============================
# ERROR HANDLER
# ============================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Maneja errores globales del bot"""
    error_message = str(context.error)
    
    # Ignorar errores comunes cuando el bot se despierta
    if "Message to be replied not found" in error_message:
        print("⚠️ Mensaje antiguo no encontrado (bot despertó de inactividad)")
        return
    
    if "Message is not modified" in error_message:
        print("⚠️ Mensaje no modificado (mismo contenido)")
        return
    
    # Log otros errores para debugging
    print(f"❌ Error capturado: {error_message}")
    if update:
        print(f"📍 Update: {update}")

# ============================
# CONTROL DE ACCESO
# ============================

def verificar_acceso(chat_id: int) -> bool:
    """Verifica si el grupo tiene permiso para usar el bot"""
    # Si la lista está vacía, permitir todos los grupos
    if not GRUPOS_PERMITIDOS:
        return True
    
    # Verificar si el chat_id está en la lista de permitidos
    return chat_id in GRUPOS_PERMITIDOS

async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando para obtener el ID del chat actual"""
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    chat_title = update.effective_chat.title or "Chat privado"
    
    mensaje = f"""🔍 <b>Información del Chat</b>

📱 <b>ID del Chat:</b> <code>{chat_id}</code>
📂 <b>Tipo:</b> {chat_type}
📝 <b>Título:</b> {chat_title}

💡 Copia este ID para agregarlo a GRUPOS_PERMITIDOS"""
    
    await update.message.reply_text(mensaje, parse_mode='HTML')

# ============================
# SISTEMA DE PREGUNTAS AUTOMÁTICAS
# ============================

PREGUNTAS_JUEGOS = [
    {"dias": [0, 1], "pregunta": "¿Qué te gustaría jugar esta semana? 🎲"},
    {"dias": [2, 3], "pregunta": "¿Qué jugarás este fin de semana? 🎯"},
    {"dias": [4], "pregunta": "¿Qué tenéis preparado para este finde? 🃏"},
    {"dias": [5, 6], "pregunta": "¿Qué estáis jugando hoy? 🎮"},
    {"dias": None, "pregunta": "¿Cuál es para ti la mejor feria de juegos de mesa? 🏆"},
    {"dias": None, "pregunta": "¿Qué partida te dejó mejor recuerdo y por qué? 💭"},
    {"dias": None, "pregunta": "Si pudieras jugar solo a un juego el resto de tu vida, ¿cuál sería? 🎲"},
    {"dias": None, "pregunta": "¿Cuál es el juego más sobrevalorado en tu opinión? 🤔"},
    {"dias": None, "pregunta": "¿Cuál es el juego más infravalorado que conoces? 💎"},
    {"dias": None, "pregunta": "¿Prefieres juegos cooperativos o competitivos? ¿Por qué? 🤝⚔️"},
    {"dias": None, "pregunta": "¿Cuál fue el último juego que descubriste y te sorprendió? ✨"},
    {"dias": None, "pregunta": "¿Qué expansión de un juego consideras imprescindible? 📦"},
    {"dias": None, "pregunta": "¿Cuál es tu juego favorito para 2 jugadores? 👥"},
    {"dias": None, "pregunta": "¿Qué juego te gustaría probar pero aún no has jugado? 🆕"},
    {"dias": None, "pregunta": "¿Cuál es el juego más difícil de explicar que conoces? 📚"},
    {"dias": None, "pregunta": "¿Tienes alguna anécdota divertida de una partida? 😂"},
    {"dias": None, "pregunta": "¿Qué mecánica de juego te gusta más? 🔧"},
    {"dias": None, "pregunta": "¿Cuál es tu juego de mesa más antiguo? 🕰️"},
    {"dias": None, "pregunta": "¿Qué diseñador de juegos admiras más? 🎨"},
    {"dias": None, "pregunta": "¿Party games o juegos estratégicos? 🎉🧠"},
]

async def puede_enviar_pregunta(chat_id: int, pregunta_id: int) -> bool:
    """Verifica si ha pasado 1 semana desde la última vez que se hizo esta pregunta"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    una_semana_atras = datetime.now() - timedelta(days=7)
    
    cursor.execute('''
        SELECT timestamp FROM preguntas_historial
        WHERE chat_id = ? AND pregunta_id = ?
        ORDER BY timestamp DESC LIMIT 1
    ''', (chat_id, pregunta_id))
    
    resultado = cursor.fetchone()
    conn.close()
    
    if not resultado:
        return True  # Primera vez que se hace esta pregunta
    
    ultima_vez = datetime.fromisoformat(resultado[0])
    return datetime.now() > (ultima_vez + timedelta(days=7))

async def enviar_pregunta_automatica(application: Application):
    """Envía una pregunta automática al grupo"""
    if not GRUPOS_PERMITIDOS:
        return
    
    for chat_id in GRUPOS_PERMITIDOS:
        try:
            dia_semana = datetime.now().weekday()  # 0=Lunes, 6=Domingo
            
            # Filtrar preguntas disponibles para hoy
            preguntas_disponibles = [
                (i, p) for i, p in enumerate(PREGUNTAS_JUEGOS)
                if p["dias"] is None or dia_semana in p["dias"]
            ]
            
            # Filtrar por cooldown de 1 semana
            preguntas_validas = []
            for idx, pregunta in preguntas_disponibles:
                if await puede_enviar_pregunta(chat_id, idx):
                    preguntas_validas.append((idx, pregunta))
            
            if not preguntas_validas:
                print(f"⏳ No hay preguntas disponibles para chat {chat_id}")
                continue
            
            # Elegir pregunta aleatoria
            pregunta_id, pregunta_data = random.choice(preguntas_validas)
            
            # Enviar pregunta
            mensaje = f"💬 <b>Pregunta del día</b>\n\n{pregunta_data['pregunta']}"
            await application.bot.send_message(
                chat_id=chat_id,
                text=mensaje,
                parse_mode='HTML'
            )
            
            # Registrar en historial
            conn = sqlite3.connect(DB_NAME)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO preguntas_historial (chat_id, pregunta_id, timestamp)
                VALUES (?, ?, ?)
            ''', (chat_id, pregunta_id, datetime.now()))
            conn.commit()
            conn.close()
            
            print(f"✅ Pregunta enviada a chat {chat_id}: {pregunta_data['pregunta']}")
            
        except Exception as e:
            print(f"❌ Error enviando pregunta a {chat_id}: {e}")

async def guardar_mensaje_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda todos los mensajes del grupo en la base de datos"""
    
    # Solo guardar mensajes de grupos
    if update.effective_chat.type not in ['group', 'supergroup']:
        return
    
    # 🔐 Verificar acceso del grupo
    if not verificar_acceso(update.effective_chat.id):
        return
    
    # Ignorar mensajes sin texto
    if not update.message or not update.message.text:
        return
    
    # Ignorar comandos del bot
    if update.message.text.startswith('/'):
        return
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        user = update.effective_user
        username = user.username or 'sin_usuario'
        first_name = user.first_name or 'Usuario'
        
        cursor.execute('''
            INSERT OR IGNORE INTO mensajes 
            (chat_id, message_id, user_id, username, first_name, texto, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            update.effective_chat.id,
            update.message.message_id,
            user.id,
            username,
            first_name,
            update.message.text,
            datetime.now()
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        print(f"Error guardando mensaje: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Bienvenida al bot"""
    
    # 🔐 Verificar acceso del grupo
    if update.effective_chat.type in ['group', 'supergroup']:
        if not verificar_acceso(update.effective_chat.id):
            await update.message.reply_text(
                "⛔ Este grupo no tiene acceso autorizado a este bot.",
                parse_mode='HTML'
            )
            return
    
    # Verificar si es admin para mostrar comandos adicionales
    is_admin = False
    if update.effective_chat.type in ['group', 'supergroup']:
        is_admin = await es_admin(update, context)
    
    welcome_message = """🤖 <b>Bot de Resúmenes de Grupo</b>

Estoy guardando todos los mensajes de este grupo para poder hacer resúmenes.

<b>Comandos disponibles:</b>
/resumen [horas] - Resume las últimas N horas (por defecto: 24h)
/resumen_desde HH:MM - Resume desde una hora específica
/stats - Muestra estadísticas de mensajes guardados
/help - Muestra esta ayuda

<b>Ejemplos:</b>
• /resumen - Resume últimas 24 horas
• /resumen 3 - Resume últimas 3 horas
• /resumen_desde 14:30 - Resume desde las 14:30"""
    
    if is_admin:
        welcome_message += """

<b>Comandos de Admin:</b>
🔐 /borrar_todo - Borra TODOS los mensajes guardados
🔐 /borrar_rango YYYY-MM-DD YYYY-MM-DD - Borra mensajes entre dos fechas

<b>Ejemplos:</b>
• /borrar_todo - Borra todo
• /borrar_rango 2024-12-01 2024-12-10 - Borra del 1 al 10 dic"""
    
    await update.message.reply_text(welcome_message, parse_mode='HTML')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /help"""
    # 🔐 Verificar acceso del grupo
    if update.effective_chat.type in ['group', 'supergroup']:
        if not verificar_acceso(update.effective_chat.id):
            return
    
    await start(update, context)

async def es_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifica si el usuario es administrador del grupo"""
    try:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        member = await context.bot.get_chat_member(chat_id, user_id)
        return member.status in ['creator', 'administrator']
    except Exception as e:
        print(f"Error verificando admin: {e}")
        return False

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Muestra estadísticas de mensajes guardados"""
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Este comando solo funciona en grupos."
        )
        return
    
    # 🔐 Verificar acceso del grupo
    if not verificar_acceso(update.effective_chat.id):
        await update.message.reply_text(
            "⛔ Este grupo no tiene acceso autorizado a este bot.",
            parse_mode='HTML'
        )
        return
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        chat_id = update.effective_chat.id
        
        # Total de mensajes
        cursor.execute(
            'SELECT COUNT(*) FROM mensajes WHERE chat_id = ?',
            (chat_id,)
        )
        total = cursor.fetchone()[0]
        
        # Mensaje más antiguo
        cursor.execute(
            'SELECT timestamp FROM mensajes WHERE chat_id = ? ORDER BY timestamp ASC LIMIT 1',
            (chat_id,)
        )
        result = cursor.fetchone()
        primer_mensaje = result[0] if result else None
        
        # Usuarios más activos
        cursor.execute('''
            SELECT first_name, username, COUNT(*) as count 
            FROM mensajes 
            WHERE chat_id = ? 
            GROUP BY user_id 
            ORDER BY count DESC 
            LIMIT 5
        ''', (chat_id,))
        
        top_users = cursor.fetchall()
        
        conn.close()
        
        # Formatear respuesta
        if total == 0:
            await update.message.reply_text(
                "📊 Aún no tengo mensajes guardados de este grupo.\n"
                "¡Empezaré a guardar desde ahora!"
            )
            return
        
        dias_guardando = "recién"
        if primer_mensaje:
            primer = datetime.fromisoformat(primer_mensaje)
            dias = (datetime.now() - primer).days
            if dias > 0:
                dias_guardando = f"{dias} día(s)"
            else:
                horas = (datetime.now() - primer).seconds // 3600
                dias_guardando = f"{horas} hora(s)"
        
        stats_text = f"""
📊 **Estadísticas del Grupo**

💬 Total de mensajes: {total:,}
📅 Guardando desde hace: {dias_guardando}

👥 **Top 5 usuarios más activos:**
"""
        
        for i, (nombre, username, count) in enumerate(top_users, 1):
            user_display = f"@{username}" if username != 'sin_usuario' else nombre
            stats_text += f"\n{i}. {user_display}: {count:,} mensajes"
        
        await update.message.reply_text(stats_text, parse_mode='Markdown')
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def borrar_todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Borra TODOS los mensajes del grupo (solo admin)"""
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Este comando solo funciona en grupos."
        )
        return
    
    # 🔐 Verificar acceso del grupo
    if not verificar_acceso(update.effective_chat.id):
        await update.message.reply_text(
            "⛔ Este grupo no tiene acceso autorizado a este bot.",
            parse_mode='HTML'
        )
        return
    
    # Verificar si es admin
    if not await es_admin(update, context):
        await update.message.reply_text(
            "🚫 Solo los administradores pueden borrar mensajes."
        )
        return
    
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        chat_id = update.effective_chat.id
        
        # Contar mensajes antes de borrar
        cursor.execute(
            'SELECT COUNT(*) FROM mensajes WHERE chat_id = ?',
            (chat_id,)
        )
        total = cursor.fetchone()[0]
        
        if total == 0:
            await update.message.reply_text(
                "ℹ️ No hay mensajes guardados para borrar."
            )
            conn.close()
            return
        
        # Borrar todos los mensajes del grupo
        cursor.execute(
            'DELETE FROM mensajes WHERE chat_id = ?',
            (chat_id,)
        )
        
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"🗑️ **Mensajes borrados exitosamente**\n\n"
            f"Se eliminaron {total:,} mensajes de la base de datos.\n"
            f"El bot comenzará a guardar mensajes nuevamente desde ahora.",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def borrar_rango(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Borra mensajes entre dos fechas (solo admin)"""
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Este comando solo funciona en grupos."
        )
        return
    
    # 🔐 Verificar acceso del grupo
    if not verificar_acceso(update.effective_chat.id):
        await update.message.reply_text(
            "⛔ Este grupo no tiene acceso autorizado a este bot.",
            parse_mode='HTML'
        )
        return
    
    # Verificar si es admin
    if not await es_admin(update, context):
        await update.message.reply_text(
            "🚫 Solo los administradores pueden borrar mensajes."
        )
        return
    
    # Verificar argumentos
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ Uso: /borrar_rango YYYY-MM-DD YYYY-MM-DD\n\n"
            "Ejemplos:\n"
            "• `/borrar_rango 2024-01-01 2024-01-31` - Borra enero\n"
            "• `/borrar_rango 2024-12-01 2024-12-10` - Borra del 1 al 10 dic",
            parse_mode='Markdown'
        )
        return
    
    try:
        fecha_desde_str = context.args[0]
        fecha_hasta_str = context.args[1]
        
        # Validar y parsear fechas
        fecha_desde = datetime.strptime(fecha_desde_str, '%Y-%m-%d')
        fecha_hasta = datetime.strptime(fecha_hasta_str, '%Y-%m-%d')
        
        # Ajustar hasta el final del día
        fecha_hasta = fecha_hasta.replace(hour=23, minute=59, second=59)
        
        if fecha_desde > fecha_hasta:
            await update.message.reply_text(
                "⚠️ La fecha de inicio debe ser anterior a la fecha final."
            )
            return
        
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        chat_id = update.effective_chat.id
        
        # Contar mensajes en ese rango
        cursor.execute('''
            SELECT COUNT(*) FROM mensajes 
            WHERE chat_id = ? 
            AND timestamp >= ? 
            AND timestamp <= ?
        ''', (chat_id, fecha_desde, fecha_hasta))
        
        total = cursor.fetchone()[0]
        
        if total == 0:
            await update.message.reply_text(
                f"ℹ️ No hay mensajes entre {fecha_desde_str} y {fecha_hasta_str}."
            )
            conn.close()
            return
        
        # Borrar mensajes en el rango
        cursor.execute('''
            DELETE FROM mensajes 
            WHERE chat_id = ? 
            AND timestamp >= ? 
            AND timestamp <= ?
        ''', (chat_id, fecha_desde, fecha_hasta))
        
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"🗑️ **Mensajes borrados exitosamente**\n\n"
            f"Se eliminaron {total:,} mensajes entre:\n"
            f"📅 Desde: {fecha_desde_str}\n"
            f"📅 Hasta: {fecha_hasta_str}",
            parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text(
            "⚠️ Formato de fecha incorrecto. Usa: YYYY-MM-DD\n"
            "Ejemplo: 2024-12-10"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera un resumen de los mensajes del grupo"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    print(f"📝 /resumen ejecutado por @{user.username or user.first_name} en chat {chat_id}")
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        print(f"❌ /resumen: No es un grupo (tipo: {update.effective_chat.type})")
        await update.message.reply_text(
            "❌ Este comando solo funciona en grupos."
        )
        return
    
    # 🔐 Verificar acceso del grupo
    if not verificar_acceso(update.effective_chat.id):
        print(f"🚫 /resumen: Acceso denegado para chat {chat_id}")
        await update.message.reply_text(
            "⛔ Este grupo no tiene acceso autorizado a este bot.",
            parse_mode='HTML'
        )
        return
    
    # Obtener el número de horas (por defecto 24)
    horas = 24
    if context.args and context.args[0].isdigit():
        horas = int(context.args[0])
        if horas > 168:  # Máximo 1 semana
            await update.message.reply_text(
                "⚠️ Máximo 168 horas (1 semana). Usando 168 horas."
            )
            horas = 168
    
    await update.message.reply_text(
        f"📊 Analizando mensajes de las últimas {horas} hora(s)..."
    )
    
    # Calcular timestamp
    fecha_limite = datetime.now() - timedelta(hours=horas)
    
    try:
        mensajes = obtener_mensajes_db(
            update.effective_chat.id, 
            fecha_limite
        )
        
        if not mensajes:
            await update.message.reply_text(
                f"😕 No hay mensajes guardados de las últimas {horas} hora(s).\n\n"
                "Recuerda: solo puedo resumir mensajes desde que entré al grupo."
            )
            return
        
        # Generar resumen con Claude
        resumen_texto = await generar_resumen(mensajes, horas)
        
        # Enviar resumen
        await update.message.reply_text(
            f"📝 **Resumen de las últimas {horas} hora(s)**\n"
            f"_({len(mensajes)} mensajes analizados)_\n\n"
            f"{resumen_texto}",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error al generar resumen: {str(e)}"
        )

async def resumen_desde(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera resumen desde una hora específica"""
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Este comando solo funciona en grupos."
        )
        return
    
    # 🔐 Verificar acceso del grupo
    if not verificar_acceso(update.effective_chat.id):
        await update.message.reply_text(
            "⛔ Este grupo no tiene acceso autorizado a este bot.",
            parse_mode='HTML'
        )
        return
    
    if not context.args:
        await update.message.reply_text(
            "⚠️ Uso: /resumen_desde HH:MM\nEjemplo: /resumen_desde 14:30"
        )
        return
    
    try:
        hora_str = context.args[0]
        hora, minuto = map(int, hora_str.split(':'))
        
        # Validar hora
        if hora < 0 or hora > 23 or minuto < 0 or minuto > 59:
            raise ValueError("Hora inválida")
        
        # Crear datetime para hoy a esa hora
        ahora = datetime.now()
        fecha_desde = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        
        # Si la hora es futura, usar ayer
        if fecha_desde > ahora:
            fecha_desde -= timedelta(days=1)
        
        horas_diff = (ahora - fecha_desde).total_seconds() / 3600
        
        await update.message.reply_text(
            f"📊 Analizando mensajes desde las {hora_str}..."
        )
        
        mensajes = obtener_mensajes_db(
            update.effective_chat.id,
            fecha_desde
        )
        
        if not mensajes:
            await update.message.reply_text(
                f"😕 No hay mensajes guardados desde las {hora_str}."
            )
            return
        
        resumen_texto = await generar_resumen(mensajes, horas_diff)
        
        await update.message.reply_text(
            f"📝 **Resumen desde las {hora_str}**\n"
            f"_({len(mensajes)} mensajes analizados)_\n\n"
            f"{resumen_texto}",
            parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text(
            "⚠️ Formato incorrecto. Usa: /resumen_desde HH:MM\n"
            "Ejemplo: /resumen_desde 14:30"
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}"
        )

def obtener_mensajes_db(chat_id: int, fecha_limite: datetime):
    """Obtiene mensajes de la base de datos desde una fecha"""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT username, first_name, texto, timestamp
            FROM mensajes
            WHERE chat_id = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        ''', (chat_id, fecha_limite))
        
        mensajes = []
        for username, first_name, texto, timestamp in cursor.fetchall():
            user_display = f"@{username}" if username != 'sin_usuario' else first_name
            mensajes.append({
                'usuario': user_display,
                'mensaje': texto,
                'timestamp': datetime.fromisoformat(timestamp)
            })
        
        conn.close()
        return mensajes
        
    except Exception as e:
        print(f"Error obteniendo mensajes: {e}")
        return []

async def generar_resumen(mensajes: list, horas: float):
    """Genera un resumen usando ChatGPT de OpenAI"""
    
    # Limitar a los últimos 200 mensajes para no exceder tokens
    mensajes_recientes = mensajes[-200:] if len(mensajes) > 200 else mensajes
    
    # Formatear mensajes para ChatGPT
    conversacion = "\n".join([
        f"[{m['timestamp'].strftime('%H:%M')}] {m['usuario']}: {m['mensaje']}"
        for m in mensajes_recientes
    ])
    
    prompt = f"""Resume la siguiente conversación de un grupo de Telegram de las últimas {horas:.1f} horas ({len(mensajes)} mensajes totales).

Conversación:
{conversacion}

Por favor proporciona un resumen estructurado con:
1. **Temas principales**: Los tópicos más discutidos
2. **Participantes activos**: Quién participó más en la conversación
3. **Puntos clave**: Decisiones, acuerdos, o información importante
4. **Tono**: El ambiente general de la conversación

Mantén el resumen conciso pero informativo."""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",  # Modelo económico y rápido
            messages=[
                {"role": "system", "content": "Eres un asistente que resume conversaciones de grupos de forma clara y estructurada."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,
            temperature=0.7
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        return f"❌ No se pudo generar el resumen: {str(e)}"

# ============================
# INTEGRACIÓN BGG API
# ============================

def limpiar_html(texto_html: str) -> str:
    """Limpia tags HTML de un texto"""
    import re
    # Eliminar tags HTML
    texto = re.sub(r'<[^>]+>', '', texto_html)
    # Decodificar entidades HTML comunes
    texto = texto.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    texto = texto.replace('&#10;', '\n').replace('&rsquo;', "'").replace('&mdash;', '—')
    return texto.strip()

async def resumir_descripcion_bgg(descripcion: str) -> str:
    """Resume la descripción de un juego usando OpenAI"""
    try:
        # Limpiar HTML
        descripcion_limpia = limpiar_html(descripcion)
        
        # Si es muy corta, devolverla tal cual
        if len(descripcion_limpia) < 200:
            return descripcion_limpia
        
        prompt = f"""Resume esta descripción de un juego de mesa en MÁXIMO 2-3 frases cortas (unos 150 caracteres). Debe ser conciso y captar la esencia del juego.

Descripción original:
{descripcion_limpia[:1000]}

Resume:"""
        
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un experto en juegos de mesa que resume descripciones de forma clara y concisa."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.7
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        print(f"⚠️ Error resumiendo descripción: {e}")
        # Si falla, devolver los primeros 200 caracteres limpios
        return limpiar_html(descripcion)[:200] + "..."

async def buscar_juego_bgg(nombre_juego: str) -> dict:
    """Busca un juego en BoardGameGeek API"""
    print(f"🔍 BGG: Buscando '{nombre_juego}'...")
    try:
        # Verificar caché primero
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Crear tabla actualizada si no existe
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bgg_cache_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_name TEXT,
                bgg_id INTEGER,
                image_url TEXT,
                min_players INTEGER,
                max_players INTEGER,
                best_players TEXT,
                playtime INTEGER,
                weight REAL,
                year_published INTEGER,
                rank INTEGER,
                bgg_link TEXT,
                description TEXT,
                mechanics TEXT,
                timestamp DATETIME,
                UNIQUE(game_name)
            )
        ''')
        
        cursor.execute('''
            SELECT * FROM bgg_cache_v2
            WHERE LOWER(game_name) = LOWER(?)
            AND timestamp > ?
        ''', (nombre_juego, datetime.now() - timedelta(days=30)))
        
        cached = cursor.fetchone()
        conn.close()
        
        if cached:
            print(f"✅ BGG: Encontrado en caché (ID: {cached[2]})")
            return {
                'bgg_id': cached[2],
                'image_url': cached[3],
                'min_players': cached[4],
                'max_players': cached[5],
                'best_players': cached[6],
                'playtime': cached[7],
                'weight': cached[8],
                'year': cached[9],
                'rank': cached[10],
                'link': cached[11],
                'description': cached[12],
                'mechanics': cached[13],
                'from_cache': True
            }
        
        # Buscar en BGG API
        search_url = f"{BGG_API_BASE}/search"
        params = {
            "query": nombre_juego,
            "type": "boardgame",
        }
        print(f"🌐 BGG: URL búsqueda: {search_url}?query={nombre_juego}")
        
        response = requests.get(
            search_url,
            params=params,
            headers=bgg_headers(),
            timeout=10,
        )
        
        print(f"📡 BGG: Status Code búsqueda: {response.status_code}")
        
        # Manejo de código 401: token inválido o ausente
        if response.status_code == 401:
            print("❌ BGG: 401 Unauthorized en búsqueda. Revisa el token BGG_API_TOKEN y el dominio (sin www).")
            return None
        
        # Manejo de código 202: BGG pone la respuesta en cola cuando está ocupado
        # Reintentamos unas pocas veces con backoff simple
        if response.status_code == 202:
            print("⏳ BGG: Respuesta en cola (202), reintentando...")
            for intento in range(3):
                import time
                time.sleep(2)
                response = requests.get(
                    search_url,
                    params=params,
                    headers=bgg_headers(),
                    timeout=10,
                )
                print(f"📡 BGG: Reintento búsqueda {intento+1}, status: {response.status_code}")
                if response.status_code == 200:
                    break
            if response.status_code != 200:
                print("❌ BGG: No se obtuvo respuesta 200 tras reintentos en búsqueda.")
                return None
        
        if response.status_code != 200:
            print(f"❌ BGG: Error en búsqueda (status {response.status_code})")
            return None
        
        root = ET.fromstring(response.content)
        items = root.findall('.//item')
        
        print(f"📊 BGG: Encontrados {len(items)} resultados")
        if not items:
            print(f"❌ BGG: No se encontraron juegos para '{nombre_juego}'")
            return None
        
        # Tomar el primer resultado
        bgg_id = items[0].get('id')
        game_name = items[0].find('name').get('value') if items[0].find('name') is not None else nombre_juego
        print(f"✅ BGG: Primer resultado - ID: {bgg_id}, Nombre: {game_name}")
        
        # Obtener detalles del juego
        details_url = f"{BGG_API_BASE}/thing"
        details_params = {
            "id": bgg_id,
            "stats": 1,
        }
        details_response = requests.get(
            details_url,
            params=details_params,
            headers=bgg_headers(),
            timeout=10,
        )
        print(f"📡 BGG: Status Code detalles: {details_response.status_code}")
        
        if details_response.status_code == 401:
            print("❌ BGG: 401 Unauthorized en detalles. Problema de token o dominio.")
            return None
        
        if details_response.status_code == 202:
            print("⏳ BGG: Respuesta en cola (202), reintentando detalles...")
            for intento in range(3):
                import time
                time.sleep(2)
                details_response = requests.get(
                    details_url,
                    params=details_params,
                    headers=bgg_headers(),
                    timeout=10,
                )
                print(f"📡 BGG: Reintento detalles {intento+1}, status: {details_response.status_code}")
                if details_response.status_code == 200:
                    break
            if details_response.status_code != 200:
                print("❌ BGG: No se obtuvo respuesta 200 tras reintentos en detalles.")
                return None
        
        if details_response.status_code != 200:
            print(f"❌ BGG: Error en detalles (status {details_response.status_code})")
            return None
        
        details_root = ET.fromstring(details_response.content)
        item = details_root.find('.//item')
        
        if not item:
            return None
        
        # Extraer información básica
        name = item.find('.//name[@type="primary"]')
        image = item.find('.//image')
        min_players = item.find('.//minplayers')
        max_players = item.find('.//maxplayers')
        playtime = item.find('.//playingtime')
        year = item.find('.//yearpublished')
        
        # 🆕 Descripción
        description_elem = item.find('.//description')
        description_raw = description_elem.text if description_elem is not None else ""
        description_summary = await resumir_descripcion_bgg(description_raw) if description_raw else "Sin descripción disponible"
        
        # 🆕 Mecánicas
        mechanics_list = []
        for link in item.findall('.//link[@type="boardgamemechanic"]'):
            mechanic_name = link.get('value')
            if mechanic_name:
                mechanics_list.append(mechanic_name)
        mechanics_str = ", ".join(mechanics_list[:5]) if mechanics_list else "N/A"  # Máximo 5 mecánicas
        
        # Polls para mejor número de jugadores
        best_players_list = []
        poll = item.find('.//poll[@name="suggested_numplayers"]')
        if poll is not None:
            for result in poll.findall('.//results'):
                num = result.get('numplayers')
                best_votes = 0
                for r in result.findall('.//result'):
                    if r.get('value') == 'Best':
                        best_votes = int(r.get('numvotes', 0))
                if best_votes > 0:
                    best_players_list.append((num, best_votes))
        
        best_players_list.sort(key=lambda x: x[1], reverse=True)
        best_players = ', '.join([x[0] for x in best_players_list[:3]]) if best_players_list else "N/A"
        
        # Peso/complejidad
        weight_elem = item.find('.//averageweight')
        weight = float(weight_elem.get('value', 0)) if weight_elem is not None else 0
        
        # Ranking
        rank_elem = item.find('.//rank[@type="subtype"]')
        rank = int(rank_elem.get('value', 0)) if rank_elem is not None and rank_elem.get('value') != 'Not Ranked' else None
        
        game_data = {
            'bgg_id': int(bgg_id),
            'image_url': image.text if image is not None else None,
            'min_players': int(min_players.get('value', 0)) if min_players is not None else 0,
            'max_players': int(max_players.get('value', 0)) if max_players is not None else 0,
            'best_players': best_players,
            'playtime': int(playtime.get('value', 0)) if playtime is not None else 0,
            'weight': round(weight, 2),
            'year': int(year.get('value', 0)) if year is not None else 0,
            'rank': rank,
            'link': f"https://boardgamegeek.com/boardgame/{bgg_id}",
            'description': description_summary,
            'mechanics': mechanics_str,
            'from_cache': False
        }
        
        # Guardar en caché
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO bgg_cache_v2 
            (game_name, bgg_id, image_url, min_players, max_players, best_players, 
             playtime, weight, year_published, rank, bgg_link, description, mechanics, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (nombre_juego, game_data['bgg_id'], game_data['image_url'], 
              game_data['min_players'], game_data['max_players'], game_data['best_players'],
              game_data['playtime'], game_data['weight'], game_data['year'], 
              game_data['rank'], game_data['link'], game_data['description'], 
              game_data['mechanics'], datetime.now()))
        conn.commit()
        conn.close()
        
        return game_data
        
    except Exception as e:
        print(f"❌ BGG ERROR COMPLETO: {type(e).__name__}: {str(e)}")
        import traceback
        print(f"📍 BGG Traceback: {traceback.format_exc()}")
        return None

async def datos_juego(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /datos - Busca información de un juego en BGG"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    print(f"🎮 /datos ejecutado por @{user.username or user.first_name} en chat {chat_id}")
    
    # Verificar acceso del grupo
    if update.effective_chat.type in ['group', 'supergroup']:
        if not verificar_acceso(update.effective_chat.id):
            print(f"🚫 /datos: Acceso denegado para chat {chat_id}")
            return
    
    if not context.args:
        print(f"⚠️ /datos: Sin argumentos")
        await update.message.reply_text(
            "⚠️ <b>Uso:</b> /datos <i>nombre del juego</i>\n\n"
            "<b>Ejemplos:</b>\n"
            "• /datos Catan\n"
            "• /datos Ark Nova\n"
            "• /datos Spirit Island",
            parse_mode='HTML'
        )
        return
    
    nombre_juego = ' '.join(context.args)
    print(f"🎲 /datos: Buscando '{nombre_juego}'")
    
    await update.message.reply_text(
        f"🔍 Buscando <b>{nombre_juego}</b> en BoardGameGeek...",
        parse_mode='HTML'
    )
    
    juego = await buscar_juego_bgg(nombre_juego)
    print(f"📦 /datos: Resultado búsqueda = {juego is not None}")
    
    if not juego:
        await update.message.reply_text(
            f"😕 No se encontró el juego <b>{nombre_juego}</b>\n\n"
            "💡 <i>Intenta con el nombre exacto o en inglés</i>",
            parse_mode='HTML'
        )
        return
    
    # Construir mensaje
    mensaje = f"🎲 <b>{nombre_juego.title()}</b>\n\n"
    
    # 🆕 Descripción
    if juego.get('description') and juego['description'] != "Sin descripción disponible":
        mensaje += f"<i>{juego['description']}</i>\n\n"
    
    mensaje += f"👥 <b>Jugadores:</b> {juego['min_players']}-{juego['max_players']}\n"
    
    if juego['best_players'] != "N/A":
        mensaje += f"   🏆 <i>Óptimo con: {juego['best_players']}</i>\n"
    
    mensaje += f"⏱️ <b>Duración:</b> {juego['playtime']} min\n"
    mensaje += f"⚖️ <b>Complejidad:</b> {juego['weight']}/5\n"
    
    if juego['year']:
        mensaje += f"📅 <b>Año:</b> {juego['year']}\n"
    
    if juego['rank']:
        mensaje += f"🏆 <b>Ranking BGG:</b> #{juego['rank']}\n"
    
    # 🆕 Mecánicas
    if juego.get('mechanics') and juego['mechanics'] != "N/A":
        mensaje += f"\n🔧 <b>Mecánicas:</b> {juego['mechanics']}\n"
    
    mensaje += f"\n📖 <a href='{juego['link']}'>Ver en BoardGameGeek</a>"
    
    if juego.get('from_cache'):
        mensaje += "\n\n💾 <i>(Datos en caché)</i>"
    
    try:
        # Enviar imagen si existe
        if juego['image_url']:
            await update.message.reply_photo(
                photo=juego['image_url'],
                caption=mensaje,
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(mensaje, parse_mode='HTML', disable_web_page_preview=False)
    except Exception as e:
        # Si falla la imagen, enviar solo texto
        await update.message.reply_text(mensaje, parse_mode='HTML', disable_web_page_preview=False)

def main():
    """Función principal"""
    
    if not TELEGRAM_TOKEN:
        print("❌ Error: Define TELEGRAM_BOT_TOKEN en las variables de entorno")
        return
    
    if not OPENAI_API_KEY:
        print("❌ Error: Define OPENAI_API_KEY en las variables de entorno")
        return
    
    # Inicializar base de datos
    inicializar_db()
    
    # Iniciar servidor web en background (para Render)
    Thread(target=run_health_server, daemon=True).start()
    
    # Crear aplicación
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Registrar comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("chatid", chatid))
    application.add_handler(CommandHandler("datos", datos_juego))  # 🆕 Comando BGG
    application.add_handler(CommandHandler("resumen", resumen))
    application.add_handler(CommandHandler("resumen_desde", resumen_desde))
    application.add_handler(CommandHandler("stats", stats))
    
    # Comandos de admin
    application.add_handler(CommandHandler("borrar_todo", borrar_todo))
    application.add_handler(CommandHandler("borrar_rango", borrar_rango))
    
    # 🆕 Error handler global
    application.add_error_handler(error_handler)
    
    # Handler para guardar TODOS los mensajes
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            guardar_mensaje_handler
        )
    )
    
    # 🆕 PREGUNTAS AUTOMÁTICAS DESACTIVADAS TEMPORALMENTE
    # (Conflicto con Python 3.13 en Render - se reactivará cuando se solucione)
    # job_queue = application.job_queue
    # for hora in [11, 15, 19]:
    #     job_queue.run_daily(
    #         enviar_pregunta_automatica,
    #         time=time(hour=hora, minute=random.randint(0, 59)),
    #         days=(0, 1, 2, 3, 4, 5, 6),
    #         data=application,
    #         name=f'pregunta_diaria_{hora}'
    #     )
    # print("⏰ Jobs de preguntas automáticas programados")
    
    # Iniciar bot
    print("🤖 Bot iniciado correctamente")
    print("💾 Guardando todos los mensajes de los grupos...")
    print("🎲 Integración BGG API activa")
    application.run_polling()

if __name__ == '__main__':
    main()