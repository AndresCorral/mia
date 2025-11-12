"""
Bot de Discord con integración a Flipt Feature Flags
Versión optimizada con mejores prácticas de Python
"""

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv

# ============================================================================
# CONFIGURACIÓN DE LOGGING
# ============================================================================

logger = logging.getLogger("discord_bot")
logger.setLevel(logging.INFO)

# Handler para consola
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# Handler para archivo
file_handler = logging.FileHandler("bot.log", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)

# Formato
formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

console_handler.setFormatter(formatter)
file_handler.setFormatter(formatter)

logger.addHandler(console_handler)
logger.addHandler(file_handler)


# ============================================================================
# CONFIGURACIÓN Y VALIDACIÓN DE VARIABLES DE ENTORNO
# ============================================================================

def load_config() -> Dict[str, str]:
    """
    Carga y valida las variables de entorno necesarias.
    
    Returns:
        Dict con la configuración validada
        
    Raises:
        EnvironmentError: Si falta alguna variable requerida
    """
    load_dotenv()
    
    # Variables requeridas
    required_vars = ["DISCORD_TOKEN", "WEBHOOK_URL"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        raise EnvironmentError(
            f"Faltan variables de entorno requeridas: {', '.join(missing_vars)}\n"
            f"Verifica tu archivo .env"
        )
    
    config = {
        "discord_token": os.getenv("DISCORD_TOKEN", ""),
        "webhook_url": os.getenv("WEBHOOK_URL", ""),
        "flipt_url": os.getenv("FLIPT_URL", "https://flipt-production-ff4a.up.railway.app"),
        "flipt_namespace": os.getenv("FLIPT_NAMESPACE", "default"),
        "flipt_flag_key": os.getenv("FLIPT_FLAG_KEY", "mia"),
    }
    
    # No loguear tokens sensibles
    logger.info("Configuración cargada exitosamente")
    logger.info(f"Flipt URL: {config['flipt_url']}")
    logger.info(f"Flipt Flag: {config['flipt_flag_key']}")
    
    return config


# Cargar configuración
try:
    CONFIG = load_config()
except EnvironmentError as e:
    logger.error(f"Error de configuración: {e}")
    sys.exit(1)


# ============================================================================
# CONSTANTES
# ============================================================================

DISCORD_MESSAGE_LIMIT = 2000
WEBHOOK_TIMEOUT = 60
SYSTEM_MESSAGES = {"Workflow started", "Workflow executed successfully"}


# ============================================================================
# INICIALIZACIÓN DEL BOT
# ============================================================================

intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guild_messages = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Variable global para sesión HTTP persistente
http_session: Optional[aiohttp.ClientSession] = None


# ============================================================================
# UTILIDADES
# ============================================================================

def classify_attachment(attachment: discord.Attachment) -> Dict[str, Any]:
    """
    Clasifica un adjunto de Discord por tipo.
    
    Args:
        attachment: Adjunto de Discord
        
    Returns:
        Diccionario con información del adjunto
    """
    content_type = attachment.content_type or ""
    
    type_map = {
        "audio/": "audio",
        "image/": "image",
        "video/": "video",
    }
    
    detected_type = next(
        (value for key, value in type_map.items() if content_type.startswith(key)),
        "file"
    )
    
    return {
        "filename": attachment.filename,
        "url": attachment.url,
        "size": attachment.size,
        "content_type": content_type,
        "type": detected_type,
    }


def extract_response_text(data: Any) -> str:
    """
    Extrae el texto de respuesta de diferentes formatos de webhook.
    
    Args:
        data: Respuesta del webhook (puede ser dict, list, etc)
        
    Returns:
        Texto extraído o representación string
    """
    # Si es una lista, tomar el primer elemento
    if isinstance(data, list):
        if not data:
            return ""
        data = data[0]
    
    # Si es un diccionario, buscar campos conocidos
    if isinstance(data, dict):
        response_keys = ["response", "message", "output", "text", "reply"]
        for key in response_keys:
            if key in data and data[key]:
                return str(data[key])
    
    # Fallback: convertir a string
    return str(data)


def clean_mention_from_message(message: discord.Message, bot_user: discord.ClientUser) -> str:
    """
    Limpia las menciones del bot del texto del mensaje.
    
    Args:
        message: Mensaje de Discord
        bot_user: Usuario del bot
        
    Returns:
        Texto limpio sin menciones
    """
    text = message.content
    
    # Remover todas las formas de mención
    text = text.replace(f'<@{bot_user.id}>', '').strip()
    text = text.replace(f'<@!{bot_user.id}>', '').strip()
    
    # Remover espacios extras
    return ' '.join(text.split())


# ============================================================================
# FEATURE FLAGS (FLIPT)
# ============================================================================

async def is_bot_enabled(user_id: str) -> bool:
    """
    Verifica si el bot está habilitado usando Flipt feature flags vía API REST.
    
    Args:
        user_id: ID del usuario para contexto de evaluación
    
    Returns:
        True si el bot está habilitado, False si está deshabilitado
    """
    logger.info(f"🔍 Verificando feature flag para usuario {user_id}...")
    
    if not http_session:
        logger.warning("⚠️ Sesión HTTP no disponible - usando fallback (habilitado)")
        return True
    
    try:
        # Primero obtenemos el estado del flag
        url = f"{CONFIG['flipt_url']}/api/v1/namespaces/{CONFIG['flipt_namespace']}/flags/{CONFIG['flipt_flag_key']}"
        
        logger.debug(f"📡 Consultando Flipt API: {url}")
        
        async with http_session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=5)
        ) as response:
            if response.status == 200:
                data = await response.json()
                
                # Verificar si el flag está habilitado
                enabled = data.get("enabled", True)
                
                logger.info(f"✅ Flipt respondió - Flag '{CONFIG['flipt_flag_key']}': {enabled}")
                
                return enabled
            else:
                error_text = await response.text()
                logger.error(f"❌ Flipt respondió con status {response.status}: {error_text}")
                logger.warning("⚠️ Usando fallback - Bot habilitado por defecto")
                return True
                
    except asyncio.TimeoutError:
        logger.error("❌ Timeout al consultar Flipt")
        logger.warning("⚠️ Usando fallback - Bot habilitado por defecto")
        return True
    except aiohttp.ClientError as e:
        logger.error(f"❌ Error de conexión con Flipt: {e}")
        logger.warning("⚠️ Usando fallback - Bot habilitado por defecto")
        return True
    except Exception as e:
        logger.error(f"❌ Error al consultar Flipt: {type(e).__name__}: {e}")
        logger.warning("⚠️ Usando fallback - Bot habilitado por defecto")
        return True


# ============================================================================
# COMUNICACIÓN CON WEBHOOK
# ============================================================================

async def send_to_webhook(
    message_text: str,
    user_id: str,
    username: str,
    message: discord.Message,
    attachments: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Envía el mensaje al webhook y retorna la respuesta.
    
    Args:
        message_text: El texto del mensaje a enviar
        user_id: ID del usuario de Discord
        username: Nombre del usuario de Discord
        message: Objeto completo del mensaje de Discord
        attachments: Lista de adjuntos con información de archivos
    
    Returns:
        Respuesta del webhook como diccionario
    """
    if not http_session:
        logger.error("Sesión HTTP no inicializada")
        return {"error": "Sesión HTTP no disponible"}
    
    # Construir metadata completa de Discord
    metadata = {
        # Información del mensaje
        "message_id": str(message.id),
        "created_at": message.created_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
        
        # Información del usuario
        "user": {
            "id": str(message.author.id),
            "username": message.author.name,
            "discriminator": message.author.discriminator,
            "display_name": message.author.display_name,
            "bot": message.author.bot,
            "avatar_url": str(message.author.avatar.url) if message.author.avatar else None,
        },
        
        # Información del canal
        "channel": {
            "id": str(message.channel.id),
            "type": str(message.channel.type),
            "name": getattr(message.channel, 'name', None),
        },
        
        # Información del servidor (si no es DM)
        "guild": None,
        
        # IDs de sesión/conversación
        "conversation_id": str(message.channel.id),  # El channel_id sirve como conversation_id
        "thread_id": str(message.channel.id),  # Para mantener conversaciones
    }
    
    # Agregar información del servidor si no es DM
    if message.guild:
        metadata["guild"] = {
            "id": str(message.guild.id),
            "name": message.guild.name,
            "icon_url": str(message.guild.icon.url) if message.guild.icon else None,
        }
        
        # Si el usuario es miembro del servidor, agregar info adicional
        if isinstance(message.author, discord.Member):
            metadata["user"]["roles"] = [str(role.id) for role in message.author.roles]
            metadata["user"]["joined_at"] = message.author.joined_at.isoformat() if message.author.joined_at else None
            metadata["user"]["nickname"] = message.author.nick
    
    # Construir payload
    payload = {
        "message": message_text,
        "user_id": user_id,
        "username": username,
        "platform": "discord",
        "metadata": metadata,
    }
    
    if attachments:
        payload["attachments"] = attachments
    
    try:
        async with http_session.post(
            CONFIG["webhook_url"],
            json=payload,
            timeout=aiohttp.ClientTimeout(total=WEBHOOK_TIMEOUT)
        ) as response:
            if response.status == 200:
                data = await response.json()
                logger.info(f"✅ Respuesta del webhook recibida para {username}")
                return data
            else:
                error_text = await response.text()
                logger.error(f"❌ Error del webhook: {response.status} - {error_text}")
                return {
                    "error": f"Error del servidor: {response.status}",
                    "details": error_text
                }
                
    except aiohttp.ClientConnectorError as e:
        logger.error(f"❌ Error de conexión con el webhook: {e}")
        return {"error": "No se pudo conectar con el servidor"}
    except asyncio.TimeoutError:
        logger.error("❌ Timeout al conectar con el webhook")
        return {"error": "El servidor tardó demasiado en responder"}
    except aiohttp.ClientError as e:
        logger.error(f"❌ Error HTTP: {type(e).__name__}: {e}")
        return {"error": f"Error de red: {type(e).__name__}"}
    except Exception as e:
        logger.error(f"❌ Error inesperado: {type(e).__name__}: {e}")
        return {"error": f"Error inesperado: {type(e).__name__}"}


# ============================================================================
# PROCESAMIENTO DE MENSAJES
# ============================================================================

async def validate_and_prepare_message(
    message: discord.Message
) -> Optional[tuple[str, List[Dict[str, Any]]]]:
    """
    Valida y prepara el mensaje para ser enviado.
    
    Args:
        message: Mensaje de Discord
        
    Returns:
        Tupla (texto, adjuntos) o None si el mensaje es inválido
    """
    user_message = message.content
    
    # Limpiar menciones si existen
    if bot.user and bot.user.mentioned_in(message):
        user_message = clean_mention_from_message(message, bot.user)
    
    # Procesar archivos adjuntos
    attachments_info = []
    if message.attachments:
        for attachment in message.attachments:
            attachment_data = classify_attachment(attachment)
            attachments_info.append(attachment_data)
            logger.info(f"📎 {attachment_data['type'].title()} detectado: {attachment.filename}")
    
    # Validar que haya contenido
    if not user_message and not attachments_info:
        return None
    
    # Si solo hay archivos sin texto, usar mensaje por defecto
    if not user_message and attachments_info:
        type_map = {
            "audio": "[Audio enviado]",
            "image": "[Imagen enviada]",
            "video": "[Video enviado]",
            "file": "[Archivo enviado]"
        }
        user_message = type_map.get(attachments_info[0]["type"], "[Archivo enviado]")
    
    return user_message, attachments_info


async def send_chunked_response(channel: discord.abc.Messageable, text: str) -> None:
    """
    Envía una respuesta, dividiéndola en chunks si excede el límite de Discord.
    
    Args:
        channel: Canal donde enviar la respuesta
        text: Texto a enviar
    """
    if len(text) <= DISCORD_MESSAGE_LIMIT:
        await channel.send(text)
        return
    
    # Dividir en chunks
    chunks = [
        text[i:i + DISCORD_MESSAGE_LIMIT]
        for i in range(0, len(text), DISCORD_MESSAGE_LIMIT)
    ]
    
    for chunk in chunks:
        await channel.send(chunk)
        await asyncio.sleep(0.5)  # Evitar rate limiting


async def handle_webhook_response(
    response_data: Dict[str, Any],
    channel: discord.abc.Messageable
) -> None:
    """
    Procesa y envía la respuesta del webhook al usuario.
    
    Args:
        response_data: Respuesta del webhook
        channel: Canal donde enviar la respuesta
    """
    # Verificar errores
    if "error" in response_data:
        error_msg = response_data.get("error", "Error desconocido")
        await channel.send(f"❌ Lo siento, hubo un error: {error_msg}")
        return
    
    # Extraer texto de respuesta
    response_text = extract_response_text(response_data)
    
    if not response_text:
        await channel.send("❌ Recibí una respuesta vacía del servidor.")
        return
    
    # Filtrar mensajes de sistema
    if response_text in SYSTEM_MESSAGES:
        logger.warning(f"Mensaje de sistema ignorado: {response_text}")
        return
    
    # Enviar respuesta
    await send_chunked_response(channel, response_text)


async def process_message(message: discord.Message) -> None:
    """
    Procesa el mensaje del usuario, lo envía al webhook y responde.
    
    Args:
        message: El mensaje de Discord a procesar
    """
    # Evitar procesar mensajes del propio bot
    if message.author.bot:
        return
    
    logger.info(f"📨 Procesando mensaje de {message.author.name} (ID: {message.author.id})")
    
    # Verificar si el bot está habilitado
    bot_enabled = await is_bot_enabled(str(message.author.id))
    
    if not bot_enabled:
        logger.info(f"🔴 Bot DESHABILITADO para {message.author.name}")
        await message.channel.send(
            "🔴 El bot está temporalmente deshabilitado. Por favor, intenta más tarde."
        )
        return
    
    logger.info("🟢 Bot HABILITADO - procesando mensaje")
    
    # Validar y preparar mensaje
    prepared = await validate_and_prepare_message(message)
    
    if not prepared:
        await message.channel.send(
            "¡Hola! Por favor envíame un mensaje, archivo, audio o imagen."
        )
        return
    
    user_message, attachments_info = prepared
    
    # Mostrar indicador de escritura mientras espera respuesta
    async with message.channel.typing():
        # Enviar al webhook con el objeto message completo
        response_data = await send_to_webhook(
            user_message,
            str(message.author.id),
            message.author.name,
            message,  # ← Pasar el objeto message completo
            attachments_info if attachments_info else None
        )
    
    # Manejar respuesta
    await handle_webhook_response(response_data, message.channel)


# ============================================================================
# EVENTOS DEL BOT
# ============================================================================

@bot.event
async def on_ready() -> None:
    """Evento que se ejecuta cuando el bot está listo."""
    global http_session
    
    # Inicializar sesión HTTP persistente
    http_session = aiohttp.ClientSession()
    logger.info("✅ Sesión HTTP inicializada")
    
    # Log de información del bot
    logger.info(f"🤖 Bot conectado como {bot.user.name} (ID: {bot.user.id})")
    logger.info(f"🎛️ Feature flags: Flipt @ {CONFIG['flipt_url']}")
    logger.info(f"🚩 Flag key: {CONFIG['flipt_flag_key']}")
    
    logger.info("=" * 60)
    logger.info("✅ Bot iniciado correctamente")
    logger.info("📋 Instrucciones de uso:")
    logger.info("   • Envía un DM directo al bot (responde siempre)")
    logger.info(f"   • Menciona al bot en un canal: @{bot.user.name} tu mensaje")
    logger.info("   • Envía archivos, audios, imágenes o videos")
    logger.info("=" * 60)


@bot.event
async def on_close() -> None:
    """Evento que se ejecuta cuando el bot se cierra."""
    global http_session
    
    logger.info("🛑 Cerrando bot...")
    
    # Cerrar sesión HTTP
    if http_session:
        await http_session.close()
        logger.info("✅ Sesión HTTP cerrada")
    
    logger.info("👋 Bot cerrado correctamente")


@bot.event
async def on_message(message: discord.Message) -> None:
    """
    Evento que se ejecuta cuando se recibe un mensaje.
    
    SOLO responde en:
    1. Mensajes directos (DM) - SIEMPRE
    2. Menciones DIRECTAS al bot en canales - SOLO @Mia (NO @everyone, NO @here)
    
    Args:
        message: Mensaje recibido
    """
    # Ignorar mensajes del propio bot
    if message.author.bot:
        return
    
    # Procesar DMs - SIEMPRE responder
    if isinstance(message.channel, discord.DMChannel):
        logger.info(f"💬 DM recibido de {message.author.name}")
        await process_message(message)
        return
    
    # Procesar menciones DIRECTAS en canales (NO @everyone, NO @here)
    if bot.user and bot.user in message.mentions:
        # Verificar que no sea solo @everyone o @here
        if not message.mention_everyone:
            logger.info(f"🏷️ Mención directa en canal de {message.author.name}")
            await process_message(message)
            return
    
    # Para cualquier otro mensaje en canales, procesar comandos pero NO responder
    await bot.process_commands(message)


# ============================================================================
# COMANDOS DEL BOT
# ============================================================================

@bot.command(name='ping')
@commands.cooldown(1, 5, commands.BucketType.user)
async def ping(ctx: commands.Context) -> None:
    """Verifica la latencia del bot."""
    latency_ms = round(bot.latency * 1000)
    await ctx.send(f'🏓 Pong! Latencia: {latency_ms}ms')


@bot.command(name='info')
@commands.cooldown(1, 10, commands.BucketType.user)
async def info_command(ctx: commands.Context) -> None:
    """Muestra información de ayuda."""
    help_text = """
**Bot Mia - Ayuda**

**Cómo usar:**
- Envíame un mensaje directo (DM) - respondo siempre
- Menciónme en un canal: @Mia tu mensaje - solo respondo si me mencionas
- Envía archivos, audios o imágenes

**Comandos:**
- `!ping` - Verifica la conexión del bot
- `!info` - Muestra este mensaje de ayuda
- `!status` - Verifica si el bot está habilitado

¡Estoy lista para ayudarte! 😊
    """
    await ctx.send(help_text)


@bot.command(name='status')
@commands.cooldown(1, 5, commands.BucketType.user)
async def status_command(ctx: commands.Context) -> None:
    """Verifica el estado del bot y feature flags."""
    user_id = str(ctx.author.id)
    logger.info(f"🔍 Comando !status ejecutado por {ctx.author.name}")
    
    is_enabled = await is_bot_enabled(user_id)
    
    if is_enabled:
        await ctx.send("🟢 Bot habilitado y funcionando correctamente")
    else:
        await ctx.send("🔴 Bot temporalmente deshabilitado")


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError) -> None:
    """Maneja errores de comandos."""
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.send(
            f"⏳ Espera {error.retry_after:.1f} segundos antes de usar este comando nuevamente."
        )
    elif isinstance(error, commands.CommandNotFound):
        # Ignorar comandos no encontrados
        pass
    else:
        logger.error(f"Error en comando: {type(error).__name__}: {error}")
        await ctx.send("❌ Ocurrió un error al ejecutar el comando.")


# ============================================================================
# FUNCIÓN PRINCIPAL
# ============================================================================

def main() -> None:
    """Función principal para iniciar el bot."""
    try:
        logger.info("🚀 Iniciando bot...")
        bot.run(CONFIG["discord_token"])
    except discord.LoginFailure:
        logger.error("❌ Token de Discord inválido. Verifica tu archivo .env")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("⌨️ Interrupción del usuario detectada")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ Error fatal: {type(e).__name__}: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()