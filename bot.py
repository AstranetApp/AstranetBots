import re
import sys
import logging

from time import sleep
from threading import Thread
from typing import Callable, Optional, List

from AstranetPy import Client
from AstranetPy.lib.util import objects

from AstranetBots import util
from AstranetBots.util import ContentType
from AstranetBots.typing import CustomMessage, CallbackQuery
from AstranetBots.handler_backends import MemoryHandlerBackend, ContinueHandling
from AstranetBots.custom_filters import SimpleCustomFilter, AdvancedCustomFilter


logger = logging.getLogger('AstranetBot')
formatter = logging.Formatter(
    '%(asctime)s (%(filename)s:%(lineno)d %(threadName)s) %(levelname)s - %(name)s: "%(message)s"'
)
console_output_handler = logging.StreamHandler(sys.stderr)
console_output_handler.setFormatter(formatter)
logger.addHandler(console_output_handler)
logger.setLevel(logging.ERROR)


# SSE chat-event name -> ContentType delivered to message handlers.
_EVENT_CONTENT_TYPES = {
    "on_text_message":            ContentType.TEXT,
    "on_image_message":           ContentType.IMAGE,
    "on_voice_message":           ContentType.VOICE,
    "on_video_message":           ContentType.VIDEO,
    "on_sticker_message":         ContentType.STICKER,
    "on_delete_message":          ContentType.DELETE,
    "on_message_edited":          ContentType.EDITED,
    "on_group_member_join":       ContentType.MEMBER_JOIN,
    "on_group_member_leave":      ContentType.MEMBER_LEAVE,
    "on_message_pinned":          ContentType.PINNED,
    "on_message_unpinned":        ContentType.UNPINNED,
    "on_chat_view_only_enabled":  ContentType.VIEW_ONLY_ENABLED,
    "on_chat_view_only_disabled": ContentType.VIEW_ONLY_DISABLED,
}


class Handler:
    "Container for (next-step | reply | user) handler callbacks."

    def __init__(self, callback, *args, **kwargs):
        self.callback = callback
        self.args = args
        self.kwargs = kwargs

    def __getitem__(self, item):
        return getattr(self, item)


class Bot(Client):
    """
    High-level Astranet bot.

    Authenticates with a bot token and consumes events over SSE. Operates inside
    communities — handlers receive a :class:`CustomMessage` carrying its
    ``comId``, so replies need no extra plumbing.
    """

    def __init__(self, token: str = None, *, threaded: bool = True,
                 num_threads: int = 2, ignore_myself: bool = True,
                 prefix: str = "!", base_url: str = None, debug: bool = False,
                 email: str = None, password: str = None):
        if email or password:
            raise ValueError(
                "Astranet bots authenticate with a token, not email/password. "
                "Create a bot via BotFather and pass Bot(token='<uid>:<secret>').")
        if not token:
            raise ValueError("a bot token is required")

        if base_url:
            super().__init__(token, base_url=base_url, debug=debug)
        else:
            super().__init__(token, debug=debug)

        self.next_step_backend = MemoryHandlerBackend()
        self.reply_backend = MemoryHandlerBackend()
        self.user_backend = MemoryHandlerBackend()

        self.custom_filters = {}
        self.prefix = prefix
        self.ignore_myself = ignore_myself

        self.message_handlers = []
        self.callback_query_handlers = []
        # Handlers for events about the bot itself (permissions / membership),
        # keyed by SSE event name — see aliases_changed_handler & friends.
        self.bot_event_handlers = {
            "aliases_changed":   [],
            "community_joined":  [],
            "community_removed": [],
        }

        self.threaded = threaded
        if self.threaded:
            self.worker_pool = util.ThreadPool(num_threads=num_threads)

        self.startup_handler = None
        # get_account / _sub_clients are inherited from Client.

        # Amino compat: AminoLightBots tracked joined voice chats here. Filled
        # by SubClient.start_live_room / join_live_room and cleared by
        # leave_live_room / end_live_room (alias live.rooms, AstranetPy.live).
        self.active_live_chats = set()

    # ======================================================================
    # Handler registration backends (next-step / reply / per-user)
    # ======================================================================

    def clear_step_handler_by_chat_id(self, chat_id: str) -> None:
        self.next_step_backend.clear_handlers(chat_id)

    def clear_reply_handlers_by_message_id(self, message_id: str) -> None:
        self.reply_backend.clear_handlers(message_id)

    def register_for_reply(self, message: objects.Message, callback: Callable, *args, **kwargs) -> None:
        self.register_for_reply_by_message_id(message.messageId, callback, *args, **kwargs)

    def register_for_reply_by_message_id(self, message_id: str, callback: Callable, *args, **kwargs) -> None:
        self.reply_backend.register_handler(message_id, Handler(callback, *args, **kwargs))

    def register_next_step_handler(self, message: objects.Message, callback: Callable, *args, **kwargs) -> None:
        self.register_next_step_handler_by_chat_id(message.chatId, callback, *args, **kwargs)

    def register_next_step_handler_by_chat_id(self, chat_id: str, callback: Callable, *args, **kwargs) -> None:
        self.next_step_backend.register_handler(chat_id, Handler(callback, *args, **kwargs))

    def register_next_step_for_user(self, message: objects.Message, callback: Callable, *args, **kwargs) -> None:
        self.register_for_user_id(message.author.userId, callback, *args, **kwargs)

    def register_for_user_id(self, user_id: str, callback: Callable, *args, **kwargs) -> None:
        self.user_backend.register_handler(user_id, Handler(callback, *args, **kwargs))

    # ======================================================================
    # Decorators
    # ======================================================================

    @staticmethod
    def check_commands_input(commands, method_name):
        if not isinstance(commands, list) or not all(isinstance(item, str) for item in commands):
            logger.error(f"{method_name}: 'commands' must be a list of strings.")

    @staticmethod
    def check_regexp_input(regexp, method_name):
        if not isinstance(regexp, str):
            logger.error(f"{method_name}: 'regexp' must be a string.")

    @staticmethod
    def _build_handler_dict(handler, **filters):
        return {
            'function': handler,
            'filters': {ftype: fvalue for ftype, fvalue in filters.items() if fvalue is not None},
        }

    def message_handler(self, commands: Optional[List[str]] = None,
                        regexp: Optional[str] = None, func: Optional[Callable] = None,
                        content_types: Optional[List[str]] = None, **kwargs):
        """
        Register a handler for incoming messages. Receives a
        :class:`CustomMessage`. Handlers run in registration order; return a
        ``ContinueHandling()`` to fall through to the next match.
        """
        if content_types is None:
            content_types = ["text"]

        if commands is not None:
            self.check_commands_input(commands, "message_handler")
            if isinstance(commands, str):
                commands = [commands]
        if regexp is not None:
            self.check_regexp_input(regexp, "message_handler")
        if isinstance(content_types, str):
            content_types = [content_types]

        def decorator(handler):
            self.add_message_handler(self._build_handler_dict(
                handler, content_types=content_types, commands=commands,
                regexp=regexp, func=func, **kwargs))
            return handler
        return decorator

    def add_message_handler(self, handler_dict):
        self.message_handlers.append(handler_dict)

    def callback_query_handler(self, func: Optional[Callable] = None, **kwargs):
        """
        Register a handler for inline-keyboard taps. Receives a
        :class:`CallbackQuery`. ``func`` is an optional predicate over the query.
        """
        def decorator(handler):
            self.callback_query_handlers.append(self._build_handler_dict(handler, func=func, **kwargs))
            return handler
        return decorator

    def on_startup(self, callback: Callable = None):
        "Register a callback fired once, right after the first successful login."
        def decorator(handler):
            self.startup_handler = handler
            return handler
        if callback:
            self.startup_handler = callback
            return callback
        return decorator

    def _bot_event_handler(self, event_name, func):
        def decorator(handler):
            self.bot_event_handlers[event_name].append(
                self._build_handler_dict(handler, func=func))
            return handler
        return decorator

    def aliases_changed_handler(self, func: Optional[Callable] = None):
        """
        Register a handler for permission changes: a community admin flipped
        this bot's aliases (payload carries the community's ``ndcId`` with the
        fresh ``aliases`` / ``disabled`` / ``pendingApproval``), or the owner
        edited the requested set in BotFather (``ndcId`` 0). The client's alias
        cache is already updated when the handler runs, so
        ``bot.has_alias(key, comId=...)`` reflects the new state.
        Receives the raw payload dict.
        """
        return self._bot_event_handler("aliases_changed", func)

    def community_joined_handler(self, func: Optional[Callable] = None):
        """
        Register a handler fired when the bot is invited into a community.
        Payload: ``{"ndcId", "name", "icon", "aliases", "pendingApproval"}`` —
        e.g. greet the community or ask its leaders to approve pending powers.
        """
        return self._bot_event_handler("community_joined", func)

    def community_removed_handler(self, func: Optional[Callable] = None):
        "Register a handler fired when the bot is removed from a community (payload: ``{\"ndcId\"}``)."
        return self._bot_event_handler("community_removed", func)

    # ======================================================================
    # Filtering
    # ======================================================================

    def add_custom_filter(self, custom_filter):
        "Register a SimpleCustomFilter / AdvancedCustomFilter by its .key."
        self.custom_filters[custom_filter.key] = custom_filter

    def _test_filter(self, message_filter, filter_value, message):
        if message_filter == 'content_types':
            return message.content_type in filter_value
        if message_filter == 'regexp':
            return message.content is not None and re.search(filter_value, message.content, re.IGNORECASE)
        if message_filter == 'commands':
            if message.content is None:
                return False
            return util.extract_command(self.prefix, message.content.lower()) in filter_value
        if message_filter == 'func':
            return filter_value(message)
        if message_filter == 'bot_has_alias':
            # Gate the handler on the BOT's own permission in the message's
            # community, e.g. message_handler(commands=['ban'],
            # bot_has_alias=aliases.MODERATION_KICK) — so a moderation command
            # silently no-ops where admins haven't granted the power instead
            # of dying on a 403 mid-action. Accepts one key or a list (all
            # required). Fail-closed on transport errors: a permission we
            # can't verify is a permission we don't have.
            keys = [filter_value] if isinstance(filter_value, str) else filter_value
            try:
                return all(
                    self.has_alias(k, comId=getattr(message, "comId", 0) or 0)
                    for k in keys
                )
            except Exception as e:  # noqa: BLE001 — network/API errors
                logger.error("bot_has_alias filter: %s", e)
                return False
        if self.custom_filters and message_filter in self.custom_filters:
            return self._check_filter(message_filter, filter_value, message)
        return False

    def _check_filter(self, message_filter, filter_value, message):
        f = self.custom_filters.get(message_filter)
        if not f:
            return False
        if isinstance(f, SimpleCustomFilter):
            return filter_value == f.check(message)
        if isinstance(f, AdvancedCustomFilter):
            return f.check(message, filter_value)
        logger.error("Custom filter must be SimpleCustomFilter or AdvancedCustomFilter.")
        return False

    def _test_handler(self, handler, message):
        for message_filter, filter_value in handler['filters'].items():
            if filter_value is None:
                continue
            if not self._test_filter(message_filter, filter_value, message):
                return False
        return True

    # ======================================================================
    # Dispatch
    # ======================================================================

    def _notify_next_handlers(self, message):
        handlers = self.next_step_backend.get_handlers(message.chatId)
        if handlers:
            for handler in handlers:
                self._exec_task(handler["callback"], message, *handler["args"], **handler["kwargs"])

    def _notify_reply_handlers(self, message):
        reply = getattr(message, "replyMessage", None)
        if not reply:
            return
        reply_id = reply.get("messageId") if isinstance(reply, dict) else getattr(reply, "messageId", None)
        if not reply_id:
            return
        handlers = self.reply_backend.get_handlers(reply_id)
        if handlers:
            for handler in handlers:
                self._exec_task(handler["callback"], message, *handler["args"], **handler["kwargs"])

    def _notify_user_handlers(self, message):
        handlers = self.user_backend.get_handlers(message.author.userId)
        if handlers:
            for handler in handlers:
                self._exec_task(handler["callback"], message, *handler["args"], **handler["kwargs"])

    def _run_handlers(self, message, handlers):
        for handler in handlers:
            if self._test_handler(handler, message):
                result = handler['function'](message)
                if not isinstance(result, ContinueHandling):
                    break

    def process_new_message(self, message):
        self._notify_next_handlers(message)
        self._notify_user_handlers(message)
        self._notify_reply_handlers(message)
        if self.message_handlers:
            self._exec_task(self._run_handlers, message, self.message_handlers)

    def process_new_updates(self, event, content_type: ContentType):
        "Turn a low-level chat Event into a CustomMessage and dispatch it."
        message_data = event.message.json
        author = (message_data or {}).get("author") or {}
        if self.ignore_myself and self.uid and self.uid == author.get("uid"):
            return
        custom_message = CustomMessage(message_data, self, event.comId, content_type.value)
        self.process_new_message(custom_message)

    def process_callback_query(self, payload: dict):
        if self.ignore_myself and self.uid and self.uid == payload.get("fromUid"):
            return
        query = CallbackQuery(payload, self)
        self._exec_task(self._run_handlers, query, self.callback_query_handlers)

    def process_bot_event(self, event_name: str, payload: dict):
        """
        Dispatch a bot-state event (aliases_changed / community_joined /
        community_removed) to its registered handlers. The alias cache is
        already synced by the client layer before this runs.
        """
        for handler in self.bot_event_handlers.get(event_name, []):
            predicate = handler['filters'].get('func')
            if predicate is not None and not predicate(payload):
                continue
            self._exec_task(handler['function'], payload)

    def _exec_task(self, task, *args, **kwargs):
        if self.threaded:
            self.worker_pool.put(task, *args, **kwargs)
        else:
            task(*args, **kwargs)

    # ======================================================================
    # Wiring + run loop
    # ======================================================================

    def _register_sse_handlers(self):
        for event_name, content_type in _EVENT_CONTENT_TYPES.items():
            # Bind both loop variables as defaults to avoid late-binding capture.
            self.event(event_name)(
                lambda e, ct=content_type: self.process_new_updates(e, ct)
            )
        self.event("on_callback_query")(self.process_callback_query)
        for name in ("aliases_changed", "community_joined", "community_removed"):
            self.event("on_" + name)(
                lambda payload, n=name: self.process_bot_event(n, payload)
            )

    def polling(self, block: bool = True):
        """
        Log in (token introspection), wire up SSE handlers and start receiving.
        Blocks the calling thread by default; pass ``block=False`` to return
        immediately (the SSE reader runs in a background daemon thread).
        """
        self._register_sse_handlers()
        self.get_me()  # validates token + starts the SSE stream

        if self.startup_handler:
            self._exec_task(self.startup_handler)

        if not block:
            return
        try:
            while True:
                sleep(3600)
        except KeyboardInterrupt:
            self.stop_sse()

    # Backwards-friendly alias.
    run = polling

    # ======================================================================
    # Amino compat (AminoLightBots surface)
    # ======================================================================

    def start_websocket_handling(self):
        """
        Amino-compat: AminoLightBots' entry point. Astranet has no websocket —
        this wires the SSE handlers and returns immediately (the old method was
        non-blocking too; ported bots keep their own ``while True`` loop).
        """
        self.polling(block=False)

    @property
    def api(self) -> str:
        "Amino-compat: the API base URL (old bots build raw URLs off ``bot.api``)."
        return self.session.base_url

    def parse_headers(self, data=None, type=None) -> dict:
        """
        Amino-compat: request headers. Astranet needs no signatures — this is
        just the session's standing headers (Authorization included).
        """
        return dict(self.session.headers)

    def send(self, data):
        """
        Amino-compat stub: raw websocket actions (t=112/200/304…) don't exist
        on Astranet (bots receive over SSE and act over REST). Logged and
        dropped so ported call sites don't crash.
        """
        logger.warning("Bot.send(): raw websocket actions are not supported on Astranet; dropped: %.120s", data)
