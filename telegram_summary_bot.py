import os
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import anthropic

# Configuración
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

# Cliente de Claude
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /start - Bienvenida al bot"""
    welcome_message = """
¡Hola! 👋 Soy tu bot de resúmenes de grupo.

Comandos disponibles:
/resumen [horas] - Resume los últimos mensajes (por defecto: últimas 24h)
/resumen_desde [hora] - Resume desde una hora específica (formato: HH:MM)
/help - Muestra esta ayuda

Ejemplo: /resumen 2 (resume las últimas 2 horas)
    """
    await update.message.reply_text(welcome_message)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /help"""
    await start(update, context)

async def resumen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Genera un resumen de los mensajes del grupo"""
    
    # Verificar que se ejecuta en un grupo
    if update.effective_chat.type not in ['group', 'supergroup']:
        await update.message.reply_text(
            "❌ Este comando solo funciona en grupos."
        )
        return
    
    # Obtener el número de horas (por defecto 24)
    horas = 24
    if context.args and context.args[0].isdigit():
        horas = int(context.args[0])
        if horas > 72:
            await update.message.reply_text(
                "⚠️ Máximo 72 horas. Usando 72 horas."
            )
            horas = 72
    
    await update.message.reply_text(
        f"📊 Generando resumen de las últimas {horas} hora(s)..."
    )
    
    # Calcular timestamp
    fecha_limite = datetime.now() - timedelta(hours=horas)
    
    try:
        # Obtener mensajes del grupo
        mensajes = await obtener_mensajes(update, context, fecha_limite)
        
        if not mensajes:
            await update.message.reply_text(
                f"No hay mensajes en las últimas {horas} hora(s)."
            )
            return
        
        # Generar resumen con Claude
        resumen_texto = await generar_resumen(mensajes, horas)
        
        # Enviar resumen
        await update.message.reply_text(
            f"📝 **Resumen de las últimas {horas} hora(s)**\n\n{resumen_texto}",
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
        
        # Crear datetime para hoy a esa hora
        ahora = datetime.now()
        fecha_desde = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
        
        # Si la hora es futura, usar ayer
        if fecha_desde > ahora:
            fecha_desde -= timedelta(days=1)
        
        horas_diff = (ahora - fecha_desde).total_seconds() / 3600
        
        await update.message.reply_text(
            f"📊 Generando resumen desde las {hora_str}..."
        )
        
        mensajes = await obtener_mensajes(update, context, fecha_desde)
        
        if not mensajes:
            await update.message.reply_text(
                f"No hay mensajes desde las {hora_str}."
            )
            return
        
        resumen_texto = await generar_resumen(mensajes, horas_diff)
        
        await update.message.reply_text(
            f"📝 **Resumen desde las {hora_str}**\n\n{resumen_texto}",
            parse_mode='Markdown'
        )
        
    except ValueError:
        await update.message.reply_text(
            "⚠️ Formato incorrecto. Usa: /resumen_desde HH:MM\nEjemplo: /resumen_desde 14:30"
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Error: {str(e)}"
        )

async def obtener_mensajes(update: Update, context: ContextTypes.DEFAULT_TYPE, fecha_limite: datetime):
    """Obtiene mensajes del grupo desde una fecha"""
    mensajes = []
    chat_id = update.effective_chat.id
    
    # Intentar obtener mensajes recientes
    # Nota: Telegram no permite leer historial completo sin ser admin
    # Esta es una limitación de la API
    
    # Para desarrollo, simulamos con los últimos mensajes disponibles
    # En producción, el bot debe almacenar mensajes en tiempo real
    
    try:
        # Obtener información del chat
        chat = await context.bot.get_chat(chat_id)
        
        # Por ahora, devolvemos un mensaje de ejemplo
        # En producción, necesitarías un sistema de almacenamiento
        return [{
            'usuario': 'Sistema',
            'mensaje': 'NOTA: Para obtener mensajes históricos, el bot necesita estar activo y guardar mensajes en tiempo real. Actualmente esto es una demo.',
            'timestamp': datetime.now()
        }]
        
    except Exception as e:
        print(f"Error obteniendo mensajes: {e}")
        return []

async def generar_resumen(mensajes: list, horas: float):
    """Genera un resumen usando Claude"""
    
    # Formatear mensajes para Claude
    conversacion = "\n".join([
        f"[{m['timestamp'].strftime('%H:%M')}] {m['usuario']}: {m['mensaje']}"
        for m in mensajes
    ])
    
    prompt = f"""Resume la siguiente conversación de un grupo de Telegram de las últimas {horas:.1f} horas.

Conversación:
{conversacion}

Por favor proporciona:
1. Un resumen conciso de los temas principales discutidos
2. Los participantes más activos
3. Puntos clave o decisiones importantes (si las hay)
4. Tono general de la conversación

Mantén el resumen claro y estructurado."""

    try:
        message = claude_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        
        return message.content[0].text
        
    except Exception as e:
        return f"No se pudo generar el resumen: {str(e)}"

def main():
    """Función principal"""
    
    if not TELEGRAM_TOKEN:
        print("❌ Error: Define TELEGRAM_BOT_TOKEN en las variables de entorno")
        return
    
    if not ANTHROPIC_API_KEY:
        print("❌ Error: Define ANTHROPIC_API_KEY en las variables de entorno")
        return
    
    # Crear aplicación
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Registrar comandos
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("resumen", resumen))
    application.add_handler(CommandHandler("resumen_desde", resumen_desde))
    
    # Iniciar bot
    print("🤖 Bot iniciado correctamente")
    application.run_polling()

if __name__ == '__main__':
    main()
