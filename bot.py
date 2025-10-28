import discord
from discord.ext import commands
import aiohttp
import os
from dotenv import load_dotenv
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('discord_bot')

# Cargar variables de entorno
load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')

if not DISCORD_TOKEN or not WEBHOOK_URL:
    raise ValueError("DISCORD_TOKEN y WEBHOOK_URL deben estar configurados en el archivo .env")

# Configurar intents
intents = discord.Intents.default()
intents.message_content = True
intents.dm_messages = True
intents.guild_messages = True

# Crear bot
bot = commands.Bot(command_prefix='!', intents=intents)


async def send_to_webhook(message_text: str, user_id: str, username: str, attachments: list = None) -> dict:
    """
    Envía el mensaje al webhook y retorna la respuesta.
    
    Args:
        message_text: El texto del mensaje a enviar
        user_id: ID del usuario de Discord
        username: Nombre del usuario de Discord
        attachments: Lista de adjuntos con información de archivos
    
    Returns:
        dict: La respuesta del webhook
    """
    async with aiohttp.ClientSession() as session:
        payload = {
            "message": message_text,
            "user_id": user_id,
            "username": username,
            "platform": "discord"
        }
        
        # Agregar información de adjuntos si existen
        if attachments:
            payload["attachments"] = attachments
        
        try:
            async with session.post(WEBHOOK_URL, json=payload, timeout=60) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Respuesta del webhook recibida para usuario {username}")
                    return data
                else:
                    error_text = await response.text()
                    logger.error(f"Error del webhook: {response.status} - {error_text}")
                    return {
                        "error": f"Error del servidor: {response.status}",
                        "details": error_text
                    }
        except aiohttp.ClientError as e:
            logger.error(f"Error de conexión con el webhook: {e}")
            return {"error": "No se pudo conectar con el servidor"}
        except Exception as e:
            logger.error(f"Error inesperado: {e}")
            return {"error": f"Error inesperado: {str(e)}"}


async def process_message(message: discord.Message):
    """
    Procesa el mensaje del usuario, lo envía al webhook y responde.
    
    Args:
        message: El mensaje de Discord a procesar
    """
    # Evitar procesar mensajes del propio bot
    if message.author.bot:
        return
    
    user_message = message.content
    
    # Si el bot fue mencionado, remover la mención del texto
    if bot.user.mentioned_in(message):
        # Remover todas las formas posibles de mención
        user_message = user_message.replace(f'<@{bot.user.id}>', '').strip()
        user_message = user_message.replace(f'<@!{bot.user.id}>', '').strip()
        # Remover espacios extras
        user_message = ' '.join(user_message.split())
    
    # Procesar archivos adjuntos
    attachments_info = []
    if message.attachments:
        for attachment in message.attachments:
            attachment_data = {
                "filename": attachment.filename,
                "url": attachment.url,
                "size": attachment.size,
                "content_type": attachment.content_type
            }
            
            # Identificar el tipo de archivo
            if attachment.content_type:
                if attachment.content_type.startswith('audio/'):
                    attachment_data["type"] = "audio"
                    logger.info(f"Audio detectado: {attachment.filename}")
                elif attachment.content_type.startswith('image/'):
                    attachment_data["type"] = "image"
                    logger.info(f"Imagen detectada: {attachment.filename}")
                elif attachment.content_type.startswith('video/'):
                    attachment_data["type"] = "video"
                    logger.info(f"Video detectado: {attachment.filename}")
                else:
                    attachment_data["type"] = "file"
                    logger.info(f"Archivo detectado: {attachment.filename}")
            else:
                attachment_data["type"] = "file"
            
            attachments_info.append(attachment_data)
    
    # Si no hay texto ni archivos, solicitar al usuario que envíe algo
    if not user_message and not attachments_info:
        await message.channel.send("¡Hola! Por favor envíame un mensaje, archivo, audio o imagen.")
        return
    
    # Si solo hay archivos sin texto, usar un mensaje por defecto
    if not user_message and attachments_info:
        if attachments_info[0]["type"] == "audio":
            user_message = "[Audio enviado]"
        elif attachments_info[0]["type"] == "image":
            user_message = "[Imagen enviada]"
        elif attachments_info[0]["type"] == "video":
            user_message = "[Video enviado]"
        else:
            user_message = "[Archivo enviado]"
    
    # Mostrar indicador de escritura mientras espera respuesta
    async with message.channel.typing():
        # Enviar al webhook
        response_data = await send_to_webhook(
            user_message,
            str(message.author.id),
            message.author.name,
            attachments_info if attachments_info else None
        )
    
    # Procesar respuesta
    if "error" in response_data:
        error_msg = response_data.get("error", "Error desconocido")
        await message.channel.send(f"❌ Lo siento, hubo un error: {error_msg}")
        return
    
    # Manejar respuesta de n8n (puede ser lista o diccionario)
    response_text = None
    
    # Si es una lista, tomar el primer elemento
    if isinstance(response_data, list):
        if len(response_data) > 0:
            response_data = response_data[0]
        else:
            await message.channel.send("❌ Recibí una respuesta vacía del servidor.")
            return
    
    # Extraer el texto de la respuesta
    if isinstance(response_data, dict):
        response_text = (
            response_data.get("response") or 
            response_data.get("message") or 
            response_data.get("output") or
            response_data.get("text") or
            response_data.get("reply")
        )
    
    # Si aún no hay respuesta, convertir todo a string
    if not response_text:
        response_text = str(response_data)
    
    # Filtrar mensajes de sistema de n8n
    if response_text in ["Workflow started", "Workflow executed successfully"]:
        # No enviar estos mensajes, esperar la respuesta real
        logger.warning(f"Mensaje de sistema ignorado: {response_text}")
        return
    
    # Discord tiene un límite de 2000 caracteres por mensaje
    if len(response_text) > 2000:
        # Dividir en múltiples mensajes si es necesario
        chunks = [response_text[i:i+2000] for i in range(0, len(response_text), 2000)]
        for chunk in chunks:
            await message.channel.send(chunk)
    else:
        await message.channel.send(response_text)


@bot.event
async def on_ready():
    """Evento que se ejecuta cuando el bot está listo."""
    logger.info(f'Bot conectado como {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'Webhook configurado: {WEBHOOK_URL}')
    print(f'✅ Bot {bot.user.name} está listo!')
    print(f'📋 Para usar el bot:')
    print(f'   - Envía un DM directo al bot')
    print(f'   - Menciona al bot en un canal: @{bot.user.name} tu mensaje')
    print(f'   - Envía archivos, audios, imágenes o videos')
    print(f'   - Combina texto con archivos adjuntos')


@bot.event
async def on_message(message: discord.Message):
    """
    Evento que se ejecuta cuando se recibe un mensaje.
    """
    # Ignorar mensajes del propio bot
    if message.author.bot:
        return
    
    # Procesar DMs
    if isinstance(message.channel, discord.DMChannel):
        logger.info(f"DM recibido de {message.author.name}: {message.content}")
        await process_message(message)
        return
    
    # Procesar menciones en canales
    if bot.user.mentioned_in(message):
        logger.info(f"Mención en canal de {message.author.name}: {message.content}")
        await process_message(message)
        return
    
    # Procesar comandos (si los hay)
    await bot.process_commands(message)


@bot.command(name='ping')
async def ping(ctx):
    """Comando simple para verificar que el bot funciona."""
    await ctx.send(f'🏓 Pong! Latencia: {round(bot.latency * 1000)}ms')


@bot.command(name='info')
async def info_command(ctx):
    """Muestra información de ayuda."""
    help_text = """
    **Bot Mia - Ayuda**
    
    **Cómo usar:**
    • Envíame un mensaje directo (DM)
    • Menciónme en un canal: @Mia tu mensaje
    • Envía archivos, audios o imágenes
    
    **Comandos:**
    • `!ping` - Verifica la conexión del bot
    • `!info` - Muestra este mensaje de ayuda
    
    ¡Estoy lista para ayudarte! 😊
    """
    await ctx.send(help_text)


def main():
    """Función principal para iniciar el bot."""
    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        logger.error("❌ Token de Discord inválido. Verifica tu archivo .env")
    except Exception as e:
        logger.error(f"❌ Error al iniciar el bot: {e}")


if __name__ == '__main__':
    main()