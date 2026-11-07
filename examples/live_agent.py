"""
Голосовой ИИ-бот в эфире Astranet на LiveKit Agents.

Нужно:
  * алиас ``live.rooms`` у бота (BotFather → права бота);
  * бот добавлен в сообщество и состоит в чате;
  * pip install requests "livekit-agents[openai]"
  * OPENAI_API_KEY в окружении (или замените модель на любой другой плагин).

Команды в чате:
  /voice — бот заходит в активный эфир чата, а если эфира нет, начинает голосовой;
  /bye   — бот выходит.

LiveKit Agents работает здесь в автономном режиме: комнату подключаем сами
токеном от Astranet и отдаём её в ``AgentSession.start(room=...)``. Режим
воркера (``cli.run_app``, диспатч агентов) требует API-ключ и секрет самого
LiveKit-сервера — у ботов их нет и не будет.
"""

import asyncio
import threading

from livekit.agents import Agent, AgentSession, utils
from livekit.plugins import openai

from AstranetPy import aliases
from AstranetBots import Bot

TOKEN = ""

bot = Bot(token=TOKEN, prefix="/")

# chatId -> (loop, stop_event)
running = {}


async def run_agent(account, join, stop: asyncio.Event):
    room = await join.connect()
    session = AgentSession(llm=openai.realtime.RealtimeModel(voice="alloy"))
    try:
        async with utils.http_context.open():
            await session.start(
                agent=Agent(instructions="Ты дружелюбный собеседник в голосовом чате. Отвечай коротко."),
                room=room,
            )
            await session.generate_reply(instructions="Поздоровайся с участниками.")
            disconnected = asyncio.Event()
            room.on("disconnected", lambda *_: disconnected.set())
            await asyncio.wait(
                [asyncio.ensure_future(stop.wait()), asyncio.ensure_future(disconnected.wait())],
                return_when=asyncio.FIRST_COMPLETED,
            )
    finally:
        await session.aclose()
        await room.disconnect()
        # Освободить место на сервере: без /leave эфир считает бота внутри.
        try:
            account.leave_live_room(join.chatId, join.roomId)
        except Exception:
            pass


def start_in_thread(chatId, account, join):
    loop = asyncio.new_event_loop()
    stop = asyncio.Event()

    def runner():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_agent(account, join, stop))
        finally:
            running.pop(chatId, None)
            loop.close()

    running[chatId] = (loop, stop)
    threading.Thread(target=runner, daemon=True).start()


@bot.message_handler(commands=["voice"], bot_has_alias=aliases.LIVE_ROOMS)
def voice(message):
    if message.chatId in running:
        message.reply("Я уже в эфире.")
        return
    account = message.account
    if account.get_live_room(message.chatId) is None:
        join = account.start_live_room(message.chatId, title="Голосовой чат с ботом")
    else:
        join = account.join_live_room(message.chatId)
    start_in_thread(message.chatId, account, join)
    message.reply("Захожу в эфир 🎙")


@bot.message_handler(commands=["bye"])
def bye(message):
    entry = running.get(message.chatId)
    if entry is None:
        message.reply("Меня нет в эфире.")
        return
    loop, stop = entry
    loop.call_soon_threadsafe(stop.set)
    message.reply("Выхожу 👋")


if __name__ == "__main__":
    bot.polling()
