"""
Inline keyboards for Astranet bots.

A keyboard is a 2-D list of buttons that rides along in a message's
``extensions.inlineKeyboard``. Two button kinds are supported server-side:

  * **callback** — tapping it sends ``callbackData`` back to the bot as a
    ``callback_query`` event (handle with ``@bot.callback_query_handler``).
  * **url** — opens a link; the bot is not notified.

Build one fluently::

    from AstranetBots import InlineKeyboard, Button

    kb = (InlineKeyboard()
          .row(Button("👍 Yes", callback_data="yes"),
               Button("👎 No",  callback_data="no"))
          .row(Button("Open site", url="https://astranetapp.com")))

    bot.send_message(comId, chatId, "Pick one:", keyboard=kb)

The client accepts either an ``InlineKeyboard`` (via ``to_keyboard()``) or a raw
2-D list of button dicts.
"""

# callbackData has a 256-char server limit (chat/callback_handler.go).
MAX_CALLBACK_DATA = 256


class Button:
    "A single inline button — give it ``callback_data`` OR ``url``."

    __slots__ = ("text", "callback_data", "url")

    def __init__(self, text: str, callback_data: str = None, url: str = None):
        if callback_data is None and url is None:
            raise ValueError("Button needs callback_data or url")
        if callback_data is not None and url is not None:
            raise ValueError("Button takes callback_data OR url, not both")
        if callback_data is not None and len(callback_data) > MAX_CALLBACK_DATA:
            raise ValueError(f"callback_data exceeds {MAX_CALLBACK_DATA} chars")
        self.text = text
        self.callback_data = callback_data
        self.url = url

    def to_dict(self) -> dict:
        d = {"text": self.text}
        if self.callback_data is not None:
            d["callback_data"] = self.callback_data
        else:
            d["url"] = self.url
        return d


def CallbackButton(text: str, callback_data: str) -> Button:
    "Shorthand for a callback button."
    return Button(text, callback_data=callback_data)


def UrlButton(text: str, url: str) -> Button:
    "Shorthand for a URL button."
    return Button(text, url=url)


class InlineKeyboard:
    "Fluent builder for a 2-D inline keyboard."

    def __init__(self, *rows):
        self._rows = []
        for r in rows:
            self.row(*r)

    def row(self, *buttons) -> "InlineKeyboard":
        "Append a row of buttons (Button objects or raw dicts)."
        if buttons:
            self._rows.append(list(buttons))
        return self

    # Telegram-style alias.
    add = row

    def to_keyboard(self) -> list:
        """
        Serialize to the Telegram-style bare 2-D array stored in
        ``extensions.inlineKeyboard``: ``[[button, ...], ...]``.
        """
        return [
            [b.to_dict() if isinstance(b, Button) else b for b in row]
            for row in self._rows
        ]
