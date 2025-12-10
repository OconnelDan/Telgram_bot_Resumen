import os
import sqlite3
from datetime import datetime, timedelta
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
from openai import OpenAI

# Configuración
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

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
    
    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada")

async def guardar_mensaje_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Guarda todos los mensajes del grupo en la base de datos"""
    
    # Solo guardar mensajes de grupos
    if update.effective_chat.type not in ['group', 'supergroup']:
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
    
    # Verificar si es admin para mostrar comandos adicionales
    is_admin = False
    if update.effective_chat.type in ['group', 'supergroup']:
        is_admin = await es_admin(update, context)
    
    welcome_message = """🤖 *Bot de Resúmenes de Grupo*

Estoy guardando todos los mensajes de este grupo para poder hacer resúmenes.

*Comandos disponibles:*
/resumen \[horas\] \- Resume las últimas N horas (por defecto: 24h)
/resumen\_desde HH:MM \- Resume desde una hora específica
/stats \- Muestra estadísticas de mensajes guardados
/help \- Muestra esta ayuda

*Ejemplos:*
• /resumen \- Resume últimas 24 horas
• /resumen 3 \- Resume últimas 3 horas
• /resumen\_desde 14:30 \- Resume desde las 14:30"""
    
    if is_admin:
        welcome_message += """

*Comandos de Admin:*
🔐 /borrar\_todo \- Borra TODOS los mensajes guardados
🔐 /borrar\_rango YYYY\-MM\-DD YYYY\-MM\-DD \- Borra mensajes entre dos fechas

*Ejemplos:*
• /borrar\_todo \- Borra todo
• /borrar\_rango 2024\-12\-01 2024\-12\-10 \- Borra del 1 al 10 dic"""
    
    await update.message.reply_text(welcome_message, parse_mode='MarkdownV2')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /help"""
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
    
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Este comando solo funciona en grupos."
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
    application.add_handler(CommandHandler("resumen", resumen))
    application.add_handler(CommandHandler("resumen_desde", resumen_desde))
    application.add_handler(CommandHandler("stats", stats))
    
    # Comandos de admin
    application.add_handler(CommandHandler("borrar_todo", borrar_todo))
    application.add_handler(CommandHandler("borrar_rango", borrar_rango))
    
    # Handler para guardar TODOS los mensajes
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            guardar_mensaje_handler
        )
    )
    
    # Iniciar bot
    print("🤖 Bot iniciado correctamente")
    print("💾 Guardando todos los mensajes de los grupos...")
    application.run_polling()

if __name__ == '__main__':
    main()