"""Sovereign — Channels: Telegram adapter.

Connects to Telegram using python-telegram-bot (PTB).
Handles inline button callbacks for the ApprovalGate.

Features:
- Approval prompts use InlineKeyboard (✅ Approve / ❌ Reject buttons)
- All incoming messages sanitized before reaching agent
- Callback query handler wires user button clicks to ApprovalGate.resolve()
- Graceful reconnect on network errors
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

from ..models import IncomingMessage
from .base import Button, ChannelAdapter

log = logging.getLogger("sovereign.channels.telegram")


class TelegramAdapter(ChannelAdapter):
    """Telegram channel adapter using python-telegram-bot.

    Install: pip install python-telegram-bot>=20.0

    Usage:
        adapter = TelegramAdapter(bot_token="...", allowed_user_ids={12345})
        await adapter.connect()
        async for msg in adapter.receive():
            response = await agent.handle(msg)
            await adapter.send(msg.user_id, response)
    """

    platform_name = "telegram"

    def __init__(
        self,
        bot_token: str,
        allowed_user_ids: Optional[set[int]] = None,
        agent_resolve_fn=None,  # fn(action_id, response) — wired in by daemon
    ) -> None:
        self._token = bot_token
        self._allowed = allowed_user_ids  # None = all users (insecure without auth)
        self._resolve_fn = agent_resolve_fn
        self._application = None
        self._message_queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()

    async def connect(self) -> None:
        try:
            from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
            from telegram import Update
        except ImportError:
            raise RuntimeError(
                "python-telegram-bot is required: pip install python-telegram-bot"
            )

        self._application = (
            Application.builder().token(self._token).build()
        )

        app = self._application

        # Route all private text messages
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._on_message,
        ))

        # Route photo messages — the organism can see
        app.add_handler(MessageHandler(
            filters.PHOTO,
            self._on_photo,
        ))

        # Route voice messages — the organism can hear
        app.add_handler(MessageHandler(
            filters.VOICE,
            self._on_voice,
        ))

        # Route inline button callbacks (approval gate responses)
        app.add_handler(CallbackQueryHandler(self._on_callback))

        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram adapter connected")

    async def disconnect(self) -> None:
        if self._application:
            await self._application.updater.stop()
            await self._application.stop()
            await self._application.shutdown()
            log.info("Telegram adapter disconnected")

    async def receive(self) -> AsyncIterator[IncomingMessage]:
        """Yield sanitized messages as they arrive."""
        while True:
            msg = await self._message_queue.get()
            yield msg

    async def send(
        self,
        user_id: str,
        text: str,
        buttons: Optional[list[Button]] = None,
    ) -> None:
        if not self._application:
            log.error("Telegram: cannot send — not connected")
            return

        bot = self._application.bot

        # Only use Markdown for approval prompts (buttons). Plain responses sent
        # as raw text to avoid Telegram entity-parse errors on backticks/asterisks.
        kwargs: dict = {"chat_id": int(user_id), "text": text[:4096]}

        if buttons:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [[
                InlineKeyboardButton(b.label, callback_data=b.callback_data)
                for b in buttons
            ]]
            kwargs["reply_markup"] = InlineKeyboardMarkup(keyboard)
            kwargs["parse_mode"] = "Markdown"

        try:
            await bot.send_message(**kwargs)
        except Exception as e:
            # Fallback: strip parse_mode if entity parsing failed
            log.warning("Telegram send failed (%s) — retrying without parse_mode", e)
            try:
                kwargs.pop("parse_mode", None)
                await bot.send_message(**kwargs)
            except Exception as e2:
                log.error("Telegram send failed on retry: %s", e2)

    async def send_approval_prompt(
        self,
        user_id: str,
        text: str,
        action_id: str,
    ) -> None:
        """Send an approval prompt with ✅/❌ inline buttons."""
        approve_btn = Button(label="✅ Approve", callback_data=f"approve:{action_id}")
        reject_btn  = Button(label="❌ Reject",  callback_data=f"reject:{action_id}")
        await self.send(user_id, text, buttons=[approve_btn, reject_btn])

    # ── Internal handlers ──────────────────────────────────────────────────────

    async def _on_message(self, update, context) -> None:
        """Handle incoming text message."""
        if not update.message or not update.message.text:
            return

        user_id = str(update.effective_user.id)

        # Auth check: only allow known users if whitelist configured
        if self._allowed and int(user_id) not in self._allowed:
            log.warning("Unauthorized Telegram user: %s", user_id)
            await update.message.reply_text(
                "⛔ You are not authorized to use this agent."
            )
            return

        raw_text = update.message.text
        msg = self.build_message(user_id, raw_text)
        await self._message_queue.put(msg)

    async def _on_photo(self, update, context) -> None:
        """Handle incoming photo — download and queue with image bytes."""
        if not update.message or not update.message.photo:
            return

        user_id = str(update.effective_user.id)

        if self._allowed and int(user_id) not in self._allowed:
            log.warning("Unauthorized Telegram user (photo): %s", user_id)
            return

        # Get highest resolution photo
        photo = update.message.photo[-1]
        caption = update.message.caption or ""

        try:
            file = await context.bot.get_file(photo.file_id)
            image_bytes = await file.download_as_bytearray()
            log.info("Photo received from %s (%d bytes, caption=%r)",
                     user_id, len(image_bytes), caption[:50])
        except Exception as e:
            log.error("Failed to download photo: %s", e)
            await update.message.reply_text(
                "I tried to look at that image but couldn't download it. Try again?"
            )
            return

        # Build message with image metadata
        text = caption or "[User sent a photo]"
        msg = self.build_message(user_id, text)
        msg.metadata = {
            "image_bytes": bytes(image_bytes),
            "has_image": True,
            "caption": caption,
        }
        await self._message_queue.put(msg)

    async def _on_voice(self, update, context) -> None:
        """Handle incoming voice message — download OGG and queue with audio bytes."""
        if not update.message or not update.message.voice:
            return

        user_id = str(update.effective_user.id)

        if self._allowed and int(user_id) not in self._allowed:
            log.warning("Unauthorized Telegram user (voice): %s", user_id)
            return

        voice = update.message.voice
        try:
            file = await context.bot.get_file(voice.file_id)
            audio_bytes = bytes(await file.download_as_bytearray())
            log.info(
                "Voice message from %s (%d bytes, duration=%ds)",
                user_id, len(audio_bytes), voice.duration,
            )
        except Exception as exc:
            log.error("Failed to download voice message: %s", exc)
            await update.message.reply_text(
                "I tried to listen but couldn't download the audio. Try again?"
            )
            return

        # Queue as a message with audio metadata — agent will transcribe
        msg = self.build_message(user_id, "[voice message]")
        msg.metadata = {
            "audio_bytes": audio_bytes,
            "audio_format": "ogg",
            "audio_duration": voice.duration,
            "has_audio": True,
        }
        await self._message_queue.put(msg)

    async def send_voice(self, user_id: str, audio_bytes: bytes) -> None:
        """Send a voice note to the user."""
        if not self._application or not audio_bytes:
            return
        import io
        try:
            await self._application.bot.send_voice(
                chat_id=int(user_id),
                voice=io.BytesIO(audio_bytes),
            )
        except Exception as exc:
            log.warning("send_voice failed: %s", exc)

    async def _on_callback(self, update, context) -> None:
        """Handle inline button answer — route to approval gate resolver."""
        query = update.callback_query
        if not query or not query.data:
            return

        await query.answer()  # dismiss the loading spinner
        data = query.data  # "approve:action_id" or "reject:action_id"

        try:
            decision, action_id = data.split(":", 1)
        except ValueError:
            return

        user_response = "y" if decision == "approve" else "n"

        if self._resolve_fn:
            self._resolve_fn(action_id, user_response)

        icon = "✅ Approved" if user_response == "y" else "❌ Rejected"
        try:
            await query.edit_message_text(f"{icon} — action `{action_id}`")
        except Exception:
            pass
