# 🤖 Bot de Telegram para Resúmenes de Grupos

Bot inteligente para Telegram que genera resúmenes automáticos de conversaciones grupales utilizando ChatGPT de OpenAI.

## 📋 Descripción

Este bot permite a los usuarios de grupos de Telegram obtener resúmenes concisos de las conversaciones recientes. Utiliza la API de OpenAI (GPT-4o-mini) para generar resúmenes inteligentes que incluyen:

- Temas principales discutidos
- Participantes más activos
- Puntos clave y decisiones importantes
- Tono general de la conversación

## ✨ Características

- 💾 **Base de datos SQLite** - Guarda mensajes automáticamente en tiempo real
- 📊 Resúmenes de conversaciones por rango de horas (hasta 1 semana)
- ⏰ Resúmenes desde una hora específica del día
- 📈 Estadísticas de participación y mensajes guardados
- 🔐 Comandos de administrador para gestionar la base de datos
- 🤖 Integración con ChatGPT (GPT-4o-mini) - económico y eficiente
- 🌐 Servidor web integrado para deployment en Render
- 💬 Funciona exclusivamente en grupos de Telegram
- 🔒 Manejo seguro de credenciales mediante variables de entorno

## 🚀 Comandos Disponibles

| Comando | Descripción | Ejemplo |
|---------|-------------|---------|
| `/start` | Muestra mensaje de bienvenida y ayuda | `/start` |
| `/help` | Muestra la ayuda con todos los comandos | `/help` |
| `/resumen [horas]` | Resume los últimos mensajes (por defecto 24h, máximo 168h) | `/resumen 3` |
| `/resumen_desde [hora]` | Resume desde una hora específica (formato HH:MM) | `/resumen_desde 14:30` |
| `/stats` | Muestra estadísticas de mensajes y usuarios activos | `/stats` |
| `/borrar_todo` | 🔐 Admin: Borra todos los mensajes guardados | `/borrar_todo` |
| `/borrar_rango [desde] [hasta]` | 🔐 Admin: Borra mensajes entre dos fechas | `/borrar_rango 2024-12-01 2024-12-10` |

## 📦 Requisitos

- Python 3.11+
- Token de Bot de Telegram (obtener de [@BotFather](https://t.me/botfather))
- API Key de OpenAI

### Dependencias Python

```bash
python-telegram-bot==21.0
openai==1.54.0
```

## 🔧 Instalación

1. **Clonar el repositorio**
```bash
git clone https://github.com/OconnelDan/Telgram_bot_Resumen.git
cd Telgram_bot_Resumen
```

2. **Instalar dependencias**
```bash
pip install -r requirements.txt
```

3. **Configurar variables de entorno**

**Windows (PowerShell):**
```powershell
$env:TELEGRAM_BOT_TOKEN="tu_token_de_telegram"
$env:OPENAI_API_KEY="tu_api_key_de_openai"
```

**Linux/Mac:**
```bash
export TELEGRAM_BOT_TOKEN="tu_token_de_telegram"
export OPENAI_API_KEY="tu_api_key_de_openai"
```

4. **Ejecutar el bot**
```bash
python telegram_summary_bot2.py
```

## 🔑 Obtener Credenciales

### Token de Telegram Bot

1. Abre Telegram y busca [@BotFather](https://t.me/botfather)
2. Envía el comando `/newbot`
3. Sigue las instrucciones para nombrar tu bot
4. Copia el token que te proporciona

### API Key de OpenAI

1. Visita [platform.openai.com](https://platform.openai.com/)
2. Crea una cuenta o inicia sesión
3. Ve a la sección "API Keys"
4. Genera una nueva API key
5. Añade créditos a tu cuenta para poder usar la API

## 💡 Uso

1. Agrega el bot a un grupo de Telegram
2. Otorga permisos de administrador (recomendado para acceso completo)
3. Usa los comandos disponibles para generar resúmenes

**Ejemplo de uso:**
```
/resumen 3
```
Genera un resumen de las últimas 3 horas de conversación.

```
/resumen_desde 09:00
```
Genera un resumen desde las 9:00 AM hasta ahora.

## 🚀 Deployment en Render

Este bot está optimizado para ejecutarse en [Render](https://render.com) de forma gratuita:

1. Ve a [render.com](https://render.com) e inicia sesión
2. Click en **"New +"** → **"Background Worker"**
3. Conecta tu repositorio: `OconnelDan/Telgram_bot_Resumen`
4. Configura:
   - **Name**: `telegram-bot-resumenes`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python telegram_summary_bot2.py`
5. En **Environment Variables**, agrega:
   - `TELEGRAM_BOT_TOKEN` = tu token de @BotFather
   - `OPENAI_API_KEY` = tu API key de OpenAI
   - `PORT` = 10000 (opcional, se asigna automáticamente)
6. Click en **"Create Background Worker"**

✅ El bot quedará ejecutándose 24/7. El servidor web integrado mantiene el servicio activo.

## ⚠️ Consideraciones

- **Almacenamiento**: El bot guarda mensajes automáticamente desde que se une al grupo
- **Historial**: No puede acceder a mensajes anteriores a su incorporación
- **Base de datos**: SQLite local (se reinicia si el contenedor de Render se reinicia)
- **Máximo de horas**: El comando `/resumen` acepta hasta 168 horas (1 semana)
- **Límite de tokens**: Se analizan máximo los últimos 200 mensajes por resumen

## 🛠️ Mejoras Futuras

- [ ] Base de datos persistente (PostgreSQL/MongoDB)
- [ ] Soporte para exportar resúmenes en PDF
- [ ] Configuración de idiomas personalizados
- [ ] Resúmenes programados automáticos (diarios/semanales)
- [ ] Análisis de sentimiento de conversaciones
- [ ] Gráficas de actividad por usuario y horario
- [ ] Comandos personalizables por grupo
- [ ] Soporte multi-idioma con detección automática

## 📝 Estructura del Código

```
telegram_summary_bot2.py
├── Configuración (tokens y API keys)
├── Base de datos SQLite
│   ├── inicializar_db() - Crea tablas
│   ├── guardar_mensaje_handler() - Guarda mensajes automáticamente
│   └── obtener_mensajes_db() - Consulta mensajes
├── Servidor web (Health Check para Render)
│   ├── HealthHandler - Responde en puerto 10000
│   └── run_health_server() - Mantiene bot activo
├── Comandos del bot
│   ├── /start - Bienvenida
│   ├── /help - Ayuda
│   ├── /resumen - Resumen por horas
│   ├── /resumen_desde - Resumen desde hora específica
│   ├── /stats - Estadísticas del grupo
│   ├── /borrar_todo - Borra todos los mensajes (admin)
│   └── /borrar_rango - Borra mensajes por rango (admin)
├── generar_resumen() - Integración con ChatGPT (OpenAI)
└── main() - Inicialización del bot
```

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:

1. Haz fork del proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📄 Licencia

Este proyecto es de código abierto y está disponible bajo la licencia MIT.

## 👤 Autor

**OconnelDan**

- GitHub: [@OconnelDan](https://github.com/OconnelDan)

## 🙏 Agradecimientos

- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) - Framework para bots de Telegram
- [OpenAI](https://openai.com/) - API de ChatGPT para generar resúmenes inteligentes
- [Render](https://render.com/) - Plataforma de hosting gratuita para el bot

---

⭐ Si este proyecto te fue útil, considera darle una estrella en GitHub
