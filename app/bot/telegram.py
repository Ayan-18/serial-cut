from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.application.queue_control import get_queue_state, set_queue_paused
from app.bot.callbacks import handle_candidate_callback, is_user_allowed
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.database import session_scope
from app.models.entities import ClipCandidate, Episode, Season
from app.workers.queue import queue_snapshot


def _format_candidate(candidate: ClipCandidate) -> str:
    return (
        f"#{candidate.id} · {candidate.title}\n"
        f"{candidate.start_time:.1f}–{candidate.end_time:.1f} сек · score {candidate.score}/100 · "
        f"{candidate.moment_type} · {candidate.status}\n"
        f"{candidate.description}"
    )


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
            f"очередь {state}, queued={snapshot.queued}, running={snapshot.running}, failed={snapshot.failed}.\n"
            "Команды: /episodes, /candidates <id серии>, /preview <id кандидата>, /pause, /resume.\n"
            "Панель: http://127.0.0.1:8090"
        )

    async def episodes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update):
            return
        with session_scope() as session:
            seasons = session.scalars(select(Season).order_by(Season.id)).all()
            lines: list[str] = []
            for season in seasons:
                lines.append(f"▪ {season.title}")
                for episode in sorted(season.episodes, key=lambda item: item.id):
                    lines.append(f"   /candidates {episode.id} — {episode.file_name} ({episode.stage})")
        text = "\n".join(lines) if lines else "Сезоны ещё не импортированы — добавьте их в панели."
        await update.effective_message.reply_text(text[:4096])

    async def _send_candidates(message, session, episode_id: int) -> None:
        episode = session.get(Episode, episode_id)
        if episode is None:
            await message.reply_text("Серия не найдена")
            return
        candidates = session.scalars(
            select(ClipCandidate)
            .where(ClipCandidate.episode_id == episode_id)
            .order_by(ClipCandidate.score.desc())
            .limit(8)
        ).all()
        if not candidates:
            await message.reply_text(f"{episode.file_name}: кандидатов пока нет.")
            return
        await message.reply_text(f"{episode.file_name}: топ {len(candidates)} кандидатов")
        for candidate in candidates:
            await message.reply_text(_format_candidate(candidate), reply_markup=candidate_keyboard(candidate.id))

    async def candidates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update):
            return
        if not context.args or not context.args[0].isdigit():
            await update.effective_message.reply_text("Укажите id серии: /candidates 3 (список — /episodes)")
            return
        with session_scope() as session:
            await _send_candidates(update.effective_message, session, int(context.args[0]))

    async def preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not allowed(update):
            return
        if not context.args or not context.args[0].isdigit():
            await update.effective_message.reply_text("Укажите id кандидата: /preview 12")
            return
        candidate_id = int(context.args[0])
        with session_scope() as session:
            candidate = session.get(ClipCandidate, candidate_id)
            if candidate is None:
                await update.effective_message.reply_text("Кандидат не найден")
                return
            text = f"{_format_candidate(candidate)}\n\n{candidate.rationale}"
            thumbnail = candidate.thumbnail_path
        keyboard = candidate_keyboard(candidate_id)
        if thumbnail and Path(thumbnail).exists():
            with Path(thumbnail).open("rb") as handle:
                await update.effective_message.reply_photo(handle, caption=text[:1024], reply_markup=keyboard)
        else:
            await update.effective_message.reply_text(text, reply_markup=keyboard)

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
        action, raw_id = (query.data or "").split(":", 1)
        if action == "cands":
            with session_scope() as session:
                await _send_candidates(query.message, session, int(raw_id))
            return
        with session_scope() as session:
            result = handle_candidate_callback(
                session,
                settings,
                idempotency_key=f"{query.id}:{query.data}",
                action=action,
                candidate_id=int(raw_id),
            )
        await query.message.reply_text(result.message)

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", status))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("episodes", episodes))
    application.add_handler(CommandHandler("candidates", candidates))
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
            [InlineKeyboardButton("Рендер с субтитрами", callback_data=f"render:{candidate_id}")],
        ]
    )
