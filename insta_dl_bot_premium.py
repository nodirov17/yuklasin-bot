#!/usr/bin/env python3
"""
insta_dl_bot_premium.py
VideoDownloader Pro v3.2 — Premium dizayn (compact buttons, Uzbek, @yuklasin_bot)
Qo'llab-quvvatlanadi: Instagram, YouTube, Facebook, TikTok, Twitter/X
"""

import os
import sys
import tempfile
import asyncio
import logging
import requests
from pathlib import Path
from datetime import datetime

# --- Telegram / yt-dlp imports ---
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application,
        CommandHandler,
        MessageHandler,
        CallbackQueryHandler,
        filters,
        ContextTypes
    )
    from telegram.constants import ParseMode, ChatAction
except ImportError:
    print("❌ python-telegram-bot kutubxonasi topilmadi!")
    print("O'rnatish: pip install python-telegram-bot==20.7 --upgrade")
    sys.exit(1)

try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("❌ yt-dlp kutubxonasi topilmadi!")
    print("O'rnatish: pip install yt-dlp --upgrade")
    sys.exit(1)

# ===========================
# LOGGING
# ===========================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"), logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ===========================
# CONFIG
# ===========================
import os
TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_FILE_SIZE_LIMIT = 50 * 1024 * 1024  # 50 MB
BOT_USERNAME = "@yuklasin_bot"

PLATFORMS = {
    "instagram": {"domains": ["instagram.com", "instagr.am"], "emoji": "📸", "name": "Instagram"},
    "youtube": {"domains": ["youtube.com", "youtu.be", "m.youtube.com"], "emoji": "🎬", "name": "YouTube"},
    "facebook": {"domains": ["facebook.com", "fb.com", "fb.watch", "m.facebook.com"], "emoji": "📘", "name": "Facebook"},
    "tiktok": {"domains": ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"], "emoji": "🎵", "name": "TikTok"},
    "twitter": {"domains": ["twitter.com", "x.com", "t.co"], "emoji": "🐦", "name": "Twitter/X"},
}

stats = {"total": 0, "success": 0, "fail": 0, "start": datetime.now()}

# ===========================
# HELPERS
# ===========================

def get_platform(url: str):
    url = (url or "").lower()
    for k, p in PLATFORMS.items():
        if any(d in url for d in p["domains"]):
            return {"key": k, **p}
    return None

def format_size(n):
    try:
        n = int(n)
    except Exception:
        try:
            n = float(n)
        except Exception:
            n = 0
    for u in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def format_time(seconds):
    try:
        s = int(round(float(seconds or 0)))
    except Exception:
        s = 0
    if s < 0:
        s = 0
    m, sec = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"

def sanitize(name: str):
    if not name:
        return "video"
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip()[:180]

# Progress helper class (updates status message from yt-dlp progress_hook)
class DownloadProgress:
    def __init__(self, status_msg, platform_info, loop):
        self.status_msg = status_msg
        self.platform_info = platform_info
        self.loop = loop
        self.last_update = 0

    def update_sync(self, d):
        # called by yt-dlp in a thread
        try:
            if d.get('status') != 'downloading':
                return
            now = self.loop.time()
            if now - self.last_update < 1.2:  # throttle updates
                return
            self.last_update = now

            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            speed = d.get('speed', 0)

            percent = 0
            if total and downloaded:
                percent = min(int(downloaded / total * 100), 100)

            # simple emoji progress bar (10 blocks)
            filled = int(percent / 10)
            bar = "🔵" * filled + "◻️" * (10 - filled)
            speed_str = format_size(speed) + "/s" if speed else "—"

            text = (
                f"{self.platform_info['emoji']} <b>{self.platform_info['name']}</b>\n\n"
                f"<code>{bar}</code> <b>{percent}%</b>\n"
                f"📥 {format_size(downloaded)} / {format_size(total)}\n"
                f"⚡ Tezlik: {speed_str}\n"
                f"⏳ Yuklanmoqda..."
            )

            asyncio.run_coroutine_threadsafe(
                self.status_msg.edit_text(text, parse_mode=ParseMode.HTML),
                self.loop
            )
        except Exception as e:
            logger.debug(f"Progress update error: {e}")

# ===========================
# CORE: download_video
# ===========================

async def download_video(url: str, dest_dir: str, status_msg, platform_info: dict):
    loop = asyncio.get_running_loop()
    progress = DownloadProgress(status_msg, platform_info, loop)

    # base options
    ydl_opts = {
        "outtmpl": os.path.join(dest_dir, "%(title).200s.%(ext)s"),
        "format": "best[ext=mp4]/best",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": url
        },
        "progress_hooks": [progress.update_sync],
    }

    key = platform_info["key"]
    # platform-specific tweaks
    if key == "youtube":
        ydl_opts["format"] = "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    elif key == "instagram":
        ydl_opts["format"] = "best"
        ydl_opts["extractor_args"] = {"instagram": {"preferred_login": ["guest"]}}
    elif key == "facebook":
        ydl_opts["format"] = "best"
        ydl_opts["geo_bypass"] = True
    elif key == "tiktok":
        ydl_opts["format"] = "best[ext=mp4]/best"
        ydl_opts["geo_bypass"] = True
    elif key == "twitter":
        ydl_opts["format"] = "best"
        ydl_opts["geo_bypass"] = True

    def _sync_download():
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if "entries" in info:
                info = info["entries"][0]
            return info

    try:
        info = await loop.run_in_executor(None, _sync_download)
        if not info:
            raise RuntimeError("Video ma'lumotlari olinmadi")

        title = info.get("title", "video")
        ext = info.get("ext", "mp4")
        duration = info.get("duration", 0)
        thumbnail = info.get("thumbnail")
        uploader = info.get("uploader") or info.get("uploader_id") or ""
        view_count = info.get("view_count", 0)

        # find downloaded file (most recent)
        video_files = list(Path(dest_dir).glob(f"*.{ext}"))
        if not video_files:
            video_files = list(Path(dest_dir).glob("*.*"))
        if not video_files:
            raise RuntimeError("Yuklangan fayl topilmadi")

        video_path = max(video_files, key=lambda p: p.stat().st_ctime)

        return {
            "path": str(video_path),
            "title": sanitize(title),
            "size": video_path.stat().st_size,
            "duration": int(round(duration)) if duration else 0,
            "thumbnail": thumbnail,
            "uploader": uploader,
            "views": view_count,
            "ext": ext
        }

    except Exception as exc:
        logger.exception("Download error")
        raise

# ===========================
# UI: premium messages & buttons
# ===========================

def compact_main_keyboard():
    # Compact: 2 buttons per row
    kb = [
        [InlineKeyboardButton("📸 Instagram", callback_data="info_instagram"),
         InlineKeyboardButton("🎬 YouTube", callback_data="info_youtube")],
        [InlineKeyboardButton("📘 Facebook", callback_data="info_facebook"),
         InlineKeyboardButton("🎵 TikTok", callback_data="info_tiktok")],
        [InlineKeyboardButton("🐦 Twitter/X", callback_data="info_twitter"),
         InlineKeyboardButton("❓ Yordam", callback_data="help")],
        [InlineKeyboardButton("📊 Statistika", callback_data="stats"),
         InlineKeyboardButton("🔗 Bot havolasi", url=f"https://t.me/{BOT_USERNAME.strip('@')}")]
    ]
    return InlineKeyboardMarkup(kb)

START_TEXT = (
    "<b>✨ Yuklasin Bot — Premium</b>\n\n"
    "🎯 Tez, silliq va ishonchli: Instagram, YouTube, Facebook, TikTok, Twitter/X\n\n"
    "📲 Havolani yuboring — men videoni yuklab, sizga yuboraman.\n\n"
    f"<i>Bot: {BOT_USERNAME}</i>"
)

def premium_success_card(result: dict, platform_info: dict):
    title = result.get("title", "video")
    size = format_size(result.get("size", 0))
    duration = format_time(result.get("duration", 0))
    uploader = result.get("uploader", "")
    views = result.get("views", 0)
    platform_line = f"{platform_info['emoji']} <b>{platform_info['name']}</b>"

    text = (
        f"✅ <b>Yuklandi — Premium</b>\n\n"
        f"🎬 <b>{title}</b>\n"
        f"📦 {size}   ⏱ {duration}\n"
    )
    if uploader:
        text += f"👤 {uploader}\n"
    if views:
        try:
            v = int(views)
            text += f"👁 {v:,} ta ko‘rish\n"
        except Exception:
            text += f"👁 {views}\n"
    text += f"\n{platform_line}\n\n<i>© {BOT_USERNAME} orqali</i>"
    return text

def premium_error_card(message: str):
    return f"❌ <b>Xatolik</b>\n\n<code>{message}</code>\n\n💡 Havolani tekshiring yoki ommaviy videoni yuboring."

# ===========================
# Handlers
# ===========================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT, parse_mode=ParseMode.HTML, reply_markup=compact_main_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ <b>Qanday ishlatish</b>\n\n"
        "1) Video havolasini yuboring.\n"
        "2) Men yuklab, premium kartada yuboraman.\n\n"
        "⚠️ Cheklov: Telegram fayl limiti – 50 MB.\n"
        "🔒 Mualliflik huquqini hurmat qiling."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=compact_main_keyboard())

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.now() - stats["start"]
    total_seconds = int(uptime.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    success_rate = (stats["success"] / stats["total"] * 100) if stats["total"] else 0.0
    text = (
        "📊 <b>Statistika (Premium)</b>\n\n"
        f"⏱ Ish vaqti: {hours} soat {minutes} daqiqa\n"
        f"📥 Jami: {stats['total']}\n"
        f"✅ Muvaffaqiyatli: {stats['success']}\n"
        f"❌ Xato: {stats['fail']}\n"
        f"📈 Muvaffaqiyat: {success_rate:.1f}%"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=compact_main_keyboard())

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = (update.message.text or "").strip()
    platform_info = get_platform(url)
    if not platform_info:
        await update.message.reply_text(
            premium_error_card("Noma'lum platforma yoki noto'g'ri havola."),
            parse_mode=ParseMode.HTML,
            reply_markup=compact_main_keyboard()
        )
        return

    stats["total"] += 1

    # send initial "card" with sleek look
    init_text = (
        f"{platform_info['emoji']} <b>{platform_info['name']}</b>\n\n"
        "⏳ Tayyorlanmoqda — iltimos kuting..."
    )
    status_msg = await update.message.reply_text(init_text, parse_mode=ParseMode.HTML)

    # typing/upload action
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_VIDEO)

    with tempfile.TemporaryDirectory(prefix="video_dl_") as tmpdir:
        try:
            result = await download_video(url, tmpdir, status_msg, platform_info)

            # check size
            if result["size"] > TELEGRAM_FILE_SIZE_LIMIT:
                stats["fail"] += 1
                await status_msg.edit_text(
                    premium_error_card(f"Fayl juda katta: {format_size(result['size'])} (Telegram limiti {format_size(TELEGRAM_FILE_SIZE_LIMIT)})"),
                    parse_mode=ParseMode.HTML,
                    reply_markup=compact_main_keyboard()
                )
                return

            # try download thumbnail
            thumb_path = None
            if result.get("thumbnail"):
                try:
                    r = requests.get(result["thumbnail"], timeout=10)
                    if r.status_code == 200:
                        thumb_path = os.path.join(tmpdir, "thumb.jpg")
                        with open(thumb_path, "wb") as f:
                            f.write(r.content)
                except Exception:
                    thumb_path = None

            # build caption (premium style)
            caption = premium_success_card(result, platform_info)

            # send video
            await status_msg.edit_text("✅ Tayyor! Yuborilmoqda...", parse_mode=ParseMode.HTML)
            with open(result["path"], "rb") as video_file:
                thumb_file = open(thumb_path, "rb") if thumb_path else None
                try:
                    await update.message.reply_video(
                        video=video_file,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                        thumbnail=thumb_file,
                        supports_streaming=True,
                        duration=result.get("duration")
                    )
                except Exception:
                    # fallback to document
                    video_file.seek(0)
                    await update.message.reply_document(document=video_file, caption=caption, parse_mode=ParseMode.HTML)
                finally:
                    if thumb_file:
                        thumb_file.close()

            stats["success"] += 1
            await status_msg.delete()

        except Exception as e:
            logger.exception("Yuklashda xato")
            stats["fail"] += 1
            err_msg = str(e)
            if len(err_msg) > 350:
                err_msg = err_msg[:350] + "..."
            await status_msg.edit_text(premium_error_card(err_msg), parse_mode=ParseMode.HTML, reply_markup=compact_main_keyboard())

# Callback button handler
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "help":
        await q.edit_message_text(
            "❓ <b>Yordam (Premium)</b>\n\n"
            "Havolani yuboring — men videoni yuklab beraman.\n\n"
            "Agar video maxfiy/cheklangan bo'lsa, yuklab bo'lmasligi mumkin.",
            parse_mode=ParseMode.HTML,
            reply_markup=compact_main_keyboard()
        )
    elif q.data == "stats":
        uptime = datetime.now() - stats["start"]
        total_seconds = int(uptime.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        rate = (stats["success"] / stats["total"] * 100) if stats["total"] else 0.0
        await q.edit_message_text(
            "📊 <b>Statistika (Premium)</b>\n\n"
            f"⏱ Ish vaqti: {hours} soat {minutes} daqiqa\n"
            f"📥 Jami: {stats['total']}\n"
            f"✅ {stats['success']}   ❌ {stats['fail']}\n"
            f"📈 {rate:.1f}%",
            parse_mode=ParseMode.HTML,
            reply_markup=compact_main_keyboard()
        )
    elif q.data.startswith("info_"):
        p = q.data.split("_", 1)[1]
        pinfo = PLATFORMS.get(p, {})
        example = pinfo.get("domains", ["example.com"])[0] + "/..."
        await q.edit_message_text(
            f"{pinfo.get('emoji','📹')} <b>{pinfo.get('name','Platform')}</b>\n\n"
            f"<b>Misol havola:</b>\n<code>{example}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=compact_main_keyboard()
        )

# generic error handler
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Update caused error")
    try:
        if update and getattr(update, "effective_message", None):
            await update.effective_message.reply_text(
                "❌ <b>Kutilmagan xatolik yuz berdi.</b>\nIltimos qayta urinib ko'ring.",
                parse_mode=ParseMode.HTML,
                reply_markup=compact_main_keyboard()
            )
    except Exception:
        logger.exception("Error handler failed")

# ===========================
# MAIN
# ===========================

def main():
    if not TELEGRAM_BOT_TOKEN or "YOUR" in TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN to'g'ri kiritilmagan!")
        print("❌ TELEGRAM_BOT_TOKEN to'g'ri kiritilmagan!")
        return

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .connection_pool_size(8)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)

    logger.info("🚀 Insta DL Bot (Premium) ishga tushdi...")
    print("🚀 Insta DL Bot (Premium) ishga tushdi...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
