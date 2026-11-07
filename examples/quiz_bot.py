from AstranetPy import aliases
from AstranetBots import Bot, InlineKeyboard, Button

TOKEN = ""

bot = Bot(token=TOKEN, prefix="/")

QUESTIONS = [
    {"q": "Столица Австралии?",            "options": ["Сидней", "Канберра", "Мельбурн"], "answer": 1},
    {"q": "Сколько будет 2 + 2 * 2?",      "options": ["8", "6", "4"],                    "answer": 1},
    {"q": "На чём написан бэкенд Astranet?", "options": ["Python", "Go", "Rust"],          "answer": 1},
    {"q": "Что заменяет вебсокеты у ботов?", "options": ["SSE", "Long-poll", "gRPC"],      "answer": 0},
]

sessions = {}


def question_view(uid):
    s = sessions[uid]
    q = QUESTIONS[s["q"]]
    kb = InlineKeyboard()
    for i, opt in enumerate(q["options"]):
        kb.row(Button(opt, callback_data=f"ans:{i}"))
    return f"❓ Вопрос {s['q'] + 1}/{len(QUESTIONS)}\n\n{q['q']}", kb


@bot.message_handler(commands=["quiz", "start"])
def start_quiz(message):
    sessions[message.author.userId] = {"q": 0, "score": 0}
    text, kb = question_view(message.author.userId)
    message.reply(text, keyboard=kb)


@bot.message_handler(commands=["rights"])
def rights(message):
    if message.comId:
        view = bot.get_aliases(message.comId)
        text = "Мои права здесь: " + (", ".join(view["aliases"]) or "никаких")
        if view.get("pendingApproval"):
            text += "\n⏳ Ждут одобрения лидеров: " + ", ".join(view["pendingApproval"])
    else:
        text = "Глобально активно: " + (", ".join(bot.aliases) or "ничего")
    message.reply(text)

@bot.message_handler(commands=["cleanup"], bot_has_alias=aliases.MODERATION_DELETE)
def cleanup(message):
    message.delete()  # стереть сообщение участника — привилегированное право
    message.respond("🧹 Убрал.")


@bot.callback_query_handler(func=lambda q: q.data.startswith("ans:"))
def on_answer(query):
    s = sessions.get(query.fromUid)
    if s is None:
        query.edit("Сессия истекла. Набери /quiz заново.")
        return

    chosen = int(query.data.split(":")[1])
    q = QUESTIONS[s["q"]]
    if chosen == q["answer"]:
        s["score"] += 1
        head = "✅ Верно!"
    else:
        head = f"❌ Неверно. Правильный ответ: {q['options'][q['answer']]}"

    if s["q"] == len(QUESTIONS) - 1:
        kb = InlineKeyboard().row(Button("🔄 Заново", callback_data="restart"))
        query.edit(f"{head}\n\n🏁 Итог: {s['score']}/{len(QUESTIONS)}", keyboard=kb)
    else:
        kb = InlineKeyboard().row(Button("➡️ Дальше", callback_data="next"))
        query.edit(f"{head}\n\nСчёт: {s['score']}/{len(QUESTIONS)}", keyboard=kb)


@bot.callback_query_handler(func=lambda q: q.data == "next")
def on_next(query):
    s = sessions.get(query.fromUid)
    if s is None:
        query.edit("Сессия истекла. Набери /quiz заново.")
        return
    s["q"] += 1
    text, kb = question_view(query.fromUid)
    query.edit(text, keyboard=kb)


@bot.callback_query_handler(func=lambda q: q.data == "restart")
def on_restart(query):
    sessions[query.fromUid] = {"q": 0, "score": 0}
    text, kb = question_view(query.fromUid)
    query.edit(text, keyboard=kb)


# ── События о самом боте (кэш прав уже обновлён к моменту вызова) ──────────

@bot.aliases_changed_handler()
def rights_changed(payload):
    # ndcId 0 — владелец пересобрал набор в BotFather, иначе — админы
    # сообщества payload["ndcId"] изменили overrides.
    where = "BotFather" if not payload.get("ndcId") else f"x{payload['ndcId']}"
    print(f"🔧 Права изменены ({where}): активно {', '.join(payload.get('aliases') or []) or 'ничего'}")


@bot.community_joined_handler()
def greet_community(payload):
    print(f"➕ Добавили в «{payload.get('name') or payload['ndcId']}» "
          f"(x{payload['ndcId']}): {', '.join(payload.get('aliases') or []) or 'ничего'}")
    if payload.get("pendingApproval"):
        print("   ⏳ попросите лидеров одобрить:", ", ".join(payload["pendingApproval"]))


@bot.community_removed_handler()
def left_community(payload):
    print(f"➖ Убрали из x{payload['ndcId']}")


@bot.on_startup
def show_rights():
    # Полная карта прав одним вызовом: все сообщества + что активно в каждом.
    # bot-login этого намеренно не отдаёт; карта — GET /g/s/bot/me/aliases.
    overview = bot.get_aliases()
    print(f"Запущен @{bot.nickname}; сообществ: {len(overview['communities'])}")
    for com in overview["communities"]:
        line = f"  x{com['ndcId']} «{com['name'] or '?'}»: {', '.join(com['aliases']) or '—'}"
        if com["pendingApproval"]:
            line += f" | ждут одобрения: {', '.join(com['pendingApproval'])}"
        print(line)


if __name__ == "__main__":
    bot.polling()
