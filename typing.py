"""
Convenience wrappers handed to bot handlers.

``CustomMessage`` enriches the low-level ``objects.Message`` with the bound
client and the community it arrived in, so handlers can act without repeating
``comId``/``chatId`` plumbing::

    @bot.message_handler(commands=["ping"])
    def _(message):
        message.reply("pong")

``CallbackQuery`` is the analogous wrapper for inline-keyboard taps.
"""

from typing import BinaryIO
from AstranetPy import Client
from AstranetPy.lib.util.objects import Message


class CustomMessage(Message):
    """A received message bound to its client + community."""

    def __init__(self, data: dict, client: Client, comId: int, content_type: str):
        super().__init__(data)
        self.client = client
        self.comId = comId
        self.content_type = content_type

    @property
    def account(self):
        "The scope object (Client or SubClient) for this message's community."
        return self.client.get_account(self.comId)

    # Amino compat: AminoLightBots handed handlers a `.sub_client`.
    @property
    def sub_client(self):
        return self.account

    # -- replies / sends ---------------------------------------------------

    def reply(self, message: str = None, **kwargs) -> "CustomMessage":
        "Send a message that quotes this one."
        sent = self.account.send_message(
            self.chatId, message, replyTo=self.messageId, **kwargs
        )
        return self._wrap(sent)

    def respond(self, message: str = None, **kwargs) -> "CustomMessage":
        "Send a message to the same chat without quoting."
        sent = self.account.send_message(self.chatId, message, **kwargs)
        return self._wrap(sent)

    def reply_image(self, file: BinaryIO, **kwargs) -> "CustomMessage":
        sent = self.account.send_image(
            self.chatId, file, replyTo=self.messageId, **kwargs
        )
        return self._wrap(sent)

    def reply_voice(self, file: BinaryIO, **kwargs) -> "CustomMessage":
        sent = self.account.send_voice(
            self.chatId, file, replyTo=self.messageId, **kwargs
        )
        return self._wrap(sent)

    def reply_sticker(self, stickerId: str, **kwargs) -> "CustomMessage":
        sent = self.account.send_sticker(
            self.chatId, stickerId, replyTo=self.messageId, **kwargs
        )
        return self._wrap(sent)

    # -- edit / delete -----------------------------------------------------

    def edit(self, content: str = None, keyboard=None, **kwargs) -> "CustomMessage":
        "Edit this message (text and/or inline keyboard)."
        edited = self.account.edit_message(
            self.chatId, self.messageId,
            content=content, keyboard=keyboard, **kwargs
        )
        return self._wrap(edited)

    def delete(self) -> int:
        return self.account.delete_message(self.chatId, self.messageId)

    def _wrap(self, msg: Message) -> "CustomMessage":
        return CustomMessage(msg.json, self.client, self.comId, self.content_type)


class CallbackQuery:
    """An inline-keyboard tap. ``data`` is the button's callbackData."""

    __slots__ = ("json", "client", "chatId", "messageId", "comId", "fromUid", "data")

    def __init__(self, payload: dict, client):
        self.json = payload
        self.client = client
        self.chatId = payload.get("threadId")
        self.messageId = payload.get("messageId")
        self.comId = payload.get("ndcId")
        self.fromUid = payload.get("fromUid")
        self.data = payload.get("callback_data", payload.get("callbackData"))

    @property
    def account(self):
        "The scope object (Client or SubClient) for this query's community."
        return self.client.get_account(self.comId)

    def edit(self, content: str = None, keyboard=None, **kwargs) -> CustomMessage:
        "Edit the message the button is attached to (the usual response)."
        edited = self.account.edit_message(
            self.chatId, self.messageId,
            content=content, keyboard=keyboard, **kwargs
        )
        return CustomMessage(edited.json, self.client, self.comId, "edited")

    def respond(self, message: str = None, **kwargs) -> CustomMessage:
        "Send a new message to the chat the button lives in."
        sent = self.account.send_message(self.chatId, message, **kwargs)
        return CustomMessage(sent.json, self.client, self.comId, "text")
