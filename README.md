# AstranetBots

Фреймворк для ботов [Astranet](https://astranetapp.com) в стиле pyTelegramBotAPI:
декораторы обработчиков, команды, фильтры, inline-кнопки, next-step и состояния.
Работает поверх [AstranetPy](https://github.com/AstranetApp/AstranetPy).

API повторяет AminoLightBots, поэтому Amino-боты переносятся почти без правок.

## Требования

- Python 3.10+
- [AstranetPy](https://github.com/AstranetApp/AstranetPy) и `requests`
- `redis` (необязательно, только для `RedisHandlerBackend`)
- `livekit` / `livekit-agents` (необязательно, только для ботов в эфирах)

## Установка

Оба пакета ставятся клонированием рядом друг с другом:

```bash
mkdir mybot && cd mybot
git clone git@github.com:AstranetApp/AstranetPy.git
git clone git@github.com:AstranetApp/AstranetBots.git
pip install requests
```

Скрипт бота кладётся в `mybot/`. Если бот лежит в другом месте, добавьте
`mybot/` в `PYTHONPATH`.

## Токен

Бот создаётся в чате с **BotFather** в приложении Astranet. Токен имеет вид
`<uid>:<secret>`. Почта и пароль ботам не нужны: `Bot(email=…)` бросит ошибку.

## Быстрый старт

```python
from AstranetBots import Bot, InlineKeyboard, Button

bot = Bot(token="<uid>:<secret>", prefix="/")

@bot.message_handler(commands=["start"])
def start(message):
    kb = InlineKeyboard().row(Button("Нажми", callback_data="hi"))
    message.reply("Привет!", keyboard=kb)

@bot.callback_query_handler(func=lambda q: q.data == "hi")
def on_hi(query):
    query.edit("Нажато ✅")

bot.polling()
```

Обработчик получает `CustomMessage` с уже заполненным `comId`, поэтому
`message.reply()`, `respond()`, `edit()` и `delete()` работают без лишних
параметров. Префикс команд по умолчанию `!`.

## Возможности

- `message_handler(commands=…, regexp=…, func=…, content_types=…)` — тексты,
  картинки, голосовые, стикеры, вход и выход участников, закрепы и т.д.
  (`ContentType`).
- `callback_query_handler` — нажатия inline-кнопок (`InlineKeyboard`, `Button`,
  `CallbackButton`, `UrlButton`).
- `register_next_step_handler`, `register_for_reply`, `State` / `StatesGroup` —
  диалоги. Хранилище в памяти, или `RedisHandlerBackend`, чтобы переживать
  рестарт.
- Фильтры: `TextFilter`, `ChatFilter`, `IsReplyFilter`, `IsAdminFilter`, свои через
  `SimpleCustomFilter` / `AdvancedCustomFilter`. Фильтр `bot_has_alias=` пускает
  обработчик, только если у бота есть нужное право в этом сообществе.
- `aliases_changed_handler`, `community_joined_handler`,
  `community_removed_handler` — события о самом боте.
- `on_startup` — колбэк после входа.
- Все методы `AstranetPy.Client` доступны прямо на `bot`.

## Права бота

Базовые права выдаются при создании. Дополнительные (`users.dm`, `chats.create`,
`posts.create`, `comments.write`, `live.rooms`) владелец включает в BotFather →
🔐 Permissions. Администраторские (`moderation.*`) начинают работать после одобрения
лидерами сообщества. Подробности в README AstranetPy.

```python
from AstranetPy import aliases

@bot.message_handler(commands=["cleanup"], bot_has_alias=aliases.MODERATION_DELETE)
def cleanup(message):
    message.delete()
```

## Примеры

- [`examples/quiz_bot.py`](examples/quiz_bot.py) — викторина на inline-кнопках,
  проверка прав бота.
- [`examples/live_agent.py`](examples/live_agent.py) — голосовой ИИ-бот в эфире
  на LiveKit Agents (нужен алиас `live.rooms`).
