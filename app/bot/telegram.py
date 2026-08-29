from __future__ import annotations

from app.bot.callbacks import handle_candidate_callback, is_user_allowed
from app.application.queue_control import get_queue_state, set_queue_paused
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.database import session_scope
from app.models.entities import ClipCandidate
from app.workers.queue import queue_snapshot


def run_telegram_bot(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("SERIALCUTS_TELEGRAM_BOT_TOKEN не задан")
    if not settings.telegram_allowed_user_ids:
        raise RuntimeError("SERIALCUTS_TELEGRAM_ALLOWED_USER_IDS пуст: Telegram-доступ должен быть whitelist-only")

    from telegram import Update
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

    def allowed(update: Update) -> bool:
        user = update.effective_user
        return user is not None and is_user_allowed(user.id, settings.telegram_allowed_user_ids)

    async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update):
            return
        with session_scope() as session:
            snapshot = queue_snapshot(session)
            state = get_queue_state(session)
        await update.effective_message.reply_text(
            "SerialCuts локально: "
            f"очередь {state}, queued={snapshot.queued}, running={snapshot.running}, failed={snapshot.failed}. "
            "Панель: http://127.0.0.1:8090"
        )

    async def preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update):
            return
        if not context.args:
            await update.effective_message.reply_text("Укажите id кандидата: /preview 12")
            return
        candidate_id = int(context.args[0])
        with session_scope() as session:
            candidate = session.get(ClipCandidate, candidate_id)
            if candidate is None:
                await update.effective_message.reply_text("Кандидат не найден")
                return
            message = (
                f"{candidate.title}\n"
                f"{candidate.start_time:.1f}-{candidate.end_time:.1f} сек, score {candidate.score}/100\n"
                f"{candidate.description}\n\n{candidate.rationale}"
            )
        await update.effective_message.reply_text(message, reply_markup=candidate_keyboard(candidate_id))

    async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update):
            return
        with session_scope() as session:
            set_queue_paused(session, True)
        await update.effective_message.reply_text("Очередь поставлена на паузу")

    async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update):
            return
        with session_scope() as session:
            set_queue_paused(session, False)
        await update.effective_message.reply_text("Очередь продолжена")

    async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user = update.effective_user
        if query is None or user is None or not is_user_allowed(user.id, settings.telegram_allowed_user_ids):
            return
        await query.answer()
        action, raw_candidate_id = (query.data or "").split(":", 1)
        with session_scope() as session:
            result = handle_candidate_callback(
                session,
                settings,
                idempotency_key=f"{query.id}:{query.data}",
                action=action,
                candidate_id=int(raw_candidate_id),
            )
        await query.edit_message_text(result.message)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", status))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("preview", preview))
    application.add_handler(CommandHandler("pause", pause))
    application.add_handler(CommandHandler("resume", resume))
    application.add_handler(CallbackQueryHandler(callback))
    application.run_polling()


def candidate_keyboard(candidate_id: int):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Принять", callback_data=f"approve:{candidate_id}"),
                InlineKeyboardButton("Отклонить", callback_data=f"reject:{candidate_id}"),
            ],
            [InlineKeyboardButton("Экспортировать", callback_data=f"export:{candidate_id}")],
        ]
    )
