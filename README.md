# 🤖 Bot de Telegram para Resúmenes de Grupos

Bot inteligente para Telegram que genera resúmenes automáticos de conversaciones grupales utilizando Claude AI de Anthropic.

## 📋 Descripción

Este bot permite a los usuarios de grupos de Telegram obtener resúmenes concisos de las conversaciones recientes. Utiliza la API de Claude (modelo Sonnet 4) para generar resúmenes inteligentes que incluyen:

- Temas principales discutidos
- Participantes más activos
- Puntos clave y decisiones importantes
- Tono general de la conversación

## ✨ Características

- 📊 Resúmenes de conversaciones por rango de horas
- ⏰ Resúmenes desde una hora específica del día
- 🤖 Integración con Claude AI (Sonnet 4)
- 💬 Funciona exclusivamente en grupos de Telegram
- 🔒 Manejo seguro de credenciales mediante variables de entorno

## 🚀 Comandos Disponibles

| Comando | Descripción | Ejemplo |
|---------|-------------|---------|
| `/start` | Muestra mensaje de bienvenida y ayuda | `/start` |
| `/help` | Muestra la ayuda con todos los comandos | `/help` |
| `/resumen [horas]` | Resume los últimos mensajes (por defecto 24h, máximo 72h) | `/resumen 2` |
| `/resumen_desde [hora]` | Resume desde una hora específica (formato HH:MM) | `/resumen_desde 14:30` |

## 📦 Requisitos

- Python 3.8+
- Token de Bot de Telegram (obtener de [@BotFather](https://t.me/botfather))
- API Key de Anthropic Claude

### Dependencias Python

```bash
python-telegram-bot
anthropic
```

## 🔧 Instalación

1. **Clonar el repositorio**
```bash
git clone https://github.com/OconnelDan/Telgram_bot_Resumen.git
cd Telgram_bot_Resumen
```

2. **Instalar dependencias**
```bash
pip install python-telegram-bot anthropic
```

3. **Configurar variables de entorno**

**Windows (PowerShell):**
```powershell
$env:TELEGRAM_BOT_TOKEN="tu_token_de_telegram"
$env:ANTHROPIC_API_KEY="tu_api_key_de_anthropic"
```

**Linux/Mac:**
```bash
export TELEGRAM_BOT_TOKEN="tu_token_de_telegram"
export ANTHROPIC_API_KEY="tu_api_key_de_anthropic"
```

4. **Ejecutar el bot**
```bash
python telegram_summary_bot.py
```

## 🔑 Obtener Credenciales

### Token de Telegram Bot

1. Abre Telegram y busca [@BotFather](https://t.me/botfather)
2. Envía el comando `/newbot`
3. Sigue las instrucciones para nombrar tu bot
4. Copia el token que te proporciona

### API Key de Anthropic

1. Visita [console.anthropic.com](https://console.anthropic.com/)
2. Crea una cuenta o inicia sesión
3. Ve a la sección "API Keys"
4. Genera una nueva API key

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

## ⚠️ Limitaciones Actuales

- **Almacenamiento de mensajes**: Por limitaciones de la API de Telegram, el bot necesita estar activo en tiempo real para almacenar mensajes. La versión actual incluye un sistema de demostración.
- **Historial**: No puede acceder a mensajes anteriores a su incorporación al grupo sin permisos especiales.
- **Máximo de horas**: El comando `/resumen` acepta un máximo de 72 horas.

## 🛠️ Mejoras Futuras

- [ ] Sistema de base de datos para almacenar mensajes en tiempo real
- [ ] Soporte para exportar resúmenes en PDF
- [ ] Configuración de idiomas personalizados
- [ ] Resúmenes programados automáticos
- [ ] Análisis de sentimiento de conversaciones
- [ ] Estadísticas detalladas por usuario

## 📝 Estructura del Código

```
telegram_summary_bot.py
├── Configuración (tokens y API keys)
├── Comandos del bot
│   ├── /start - Bienvenida
│   ├── /help - Ayuda
│   ├── /resumen - Resumen por horas
│   └── /resumen_desde - Resumen desde hora específica
├── obtener_mensajes() - Obtención de mensajes del grupo
├── generar_resumen() - Integración con Claude AI
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
- [Anthropic Claude](https://www.anthropic.com/) - API de inteligencia artificial para generar resúmenes

---

⭐ Si este proyecto te fue útil, considera darle una estrella en GitHub
