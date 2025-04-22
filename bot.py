import os
import base58
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from solana.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from apscheduler.schedulers.background import BackgroundScheduler

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
        "🛠️ بوت تنظيف سولانا (وضع التجربة)\n\n"
        "⚠️ هذا الإصدار يعمل في وضع المحاكاة فقط\n"
        "أرسل المفتاح الخاص (Base58):"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_states and user_states[user_id] == "awaiting_confirmation":
        if text.lower() in ["yes", "نعم"]:
            await update.message.reply_text("جاري محاكاة التنظيف...")
            await simulate_cleanup(update, WALLET_INFO[user_id])
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
        await update.message.reply_text(
            f"✅ تم التحقق من المحفظة\n"
            f"العنوان: {str(keypair.public_key)[:8]}...\n\n"
            f"اكتب 'نعم' لمحاكاة التنظيف"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {str(e)}")

async def simulate_cleanup(update: Update, keypair: Keypair):
    try:
        client = AsyncClient("https://api.mainnet-beta.solana.com", timeout=10)
        pubkey = str(keypair.public_key)

        resp = await client.get_token_accounts_by_owner(
            pubkey,
            TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        )

        accounts = resp.value
        reclaimed = len(accounts) * 0.00204096

        await update.message.reply_text(
            f"🎉 محاكاة ناجحة!\n"
            f"الحسابات المكتشفة: {len(accounts)}\n"
            f"المتوقع استعادته: ~{reclaimed:.6f} SOL\n\n"
            f"⚠️ ملاحظة: هذا إصدار تجريبي لا ينفذ معاملات حقيقية"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ في المحاكاة: {str(e)}")
    finally:
        await client.close()

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("لم يتم تعيين TELEGRAM_BOT_TOKEN")
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = BackgroundScheduler()
    scheduler.start()

    logger.info("Starting bot (Simulation Mode)...")
    app.run_polling()
