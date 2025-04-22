import os
import base58
import logging
from telegram import Update, __version__ as ptb_version
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from solana.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solana.rpc.commitment import Confirmed
from solana.transaction import Transaction
from spl.token.instructions import CloseAccountParams as TokenCloseAccountParams, close_account as token_close_account
from apscheduler.schedulers.background import BackgroundScheduler

# تحقق من إصدار المكتبة
if ptb_version != "20.3":
    logging.warning(f"تحذير: يجب استخدام إصدار 20.3 من python-telegram-bot، الإصدار الحالي: {ptb_version}")

# إعدادات السجل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
user_states = {}
WALLET_INFO = {}

def is_valid_base58_key(key):
    try:
        decoded = base58.b58decode(key)
        return len(decoded) in [32, 64]
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🛠️ بوت تنظيف سولانا (الخطة المجانية)\n\n"
        "⚠️ *تحذير*: هذا البوت للتجربة فقط\n"
        "أرسل المفتاح الخاص (Base58):"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_states and user_states[user_id] == "awaiting_confirmation":
        if text.lower() in ["yes", "نعم"]:
            await update.message.reply_text("جاري المعالجة...")
            await perform_cleanup(update, WALLET_INFO[user_id])
        else:
            await update.message.reply_text("تم الإلغاء")
        user_states[user_id] = None
        return

    if not is_valid_base58_key(text):
        await update.message.reply_text("❌ المفتاح غير صالح")
        return

    try:
        decoded_key = base58.b58decode(text)
        keypair = Keypair.from_secret_key(decoded_key[:32])
        WALLET_INFO[user_id] = keypair
        user_states[user_id] = "awaiting_confirmation"
        await update.message.reply_text("✅ تم التحقق، اكتب 'نعم' للمتابعة")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

async def perform_cleanup(update: Update, keypair: Keypair):
    try:
        client = AsyncClient("https://api.mainnet-beta.solana.com", timeout=30)
        pubkey = str(keypair.public_key)
        
        # محاكاة التنظيف فقط (للتجربة)
        await update.message.reply_text(
            f"🎉 محاكاة التنظيف لـ {pubkey[:8]}...\n"
            f"المبلغ المستعاد: ~0.002 SOL (محاكاة)\n\n"
            f"⚠️ هذا إصدار تجريبي لا ينفذ معاملات حقيقية"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")
    finally:
        if 'client' in locals():
            await client.close()

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("لم يتم تعيين BOT_TOKEN")
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = BackgroundScheduler()
    scheduler.start()

    logger.info("Starting bot...")
    app.run_polling()
