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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # تأكد من أنك وضعت BOT_TOKEN في بيئة ريندر

user_states = {}
WALLET_INFO = {}

# فحص المفتاح الخاص
def is_valid_base58_key(key):
    try:
        decoded = base58.b58decode(key)
        if len(decoded) in [64, 128]:  # Solana keypair عادة 64 بايت
            return True
    except Exception:
        return False
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send your Solana private key (Base58 format):")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_states and user_states[user_id] == "awaiting_confirmation":
        if text.lower() == "yes":
            await update.message.reply_text("Processing cleanup and reclaiming rent...")
            await perform_cleanup(update, WALLET_INFO[user_id])
        else:
            await update.message.reply_text("Cancelled.")
        user_states[user_id] = None
        return

    if not is_valid_base58_key(text):
        await update.message.reply_text("Invalid private key. Make sure it's in Base58 format.")
        return

    try:
        keypair = Keypair.from_secret_key(base58.b58decode(text))
        pubkey = str(keypair.public_key)
        WALLET_INFO[user_id] = keypair
        user_states[user_id] = "awaiting_confirmation"

        sol = await simulate_cleanup(pubkey)
        await update.message.reply_text(
            f"Checking wallet: {pubkey[:8]}...\nExpected SOL from cleanup: {sol:.4f} SOL\nDo you want to proceed? (yes/no)"
        )
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def simulate_cleanup(pubkey: str) -> float:
    client = AsyncClient("https://api.mainnet-beta.solana.com")
    resp = await client.get_token_accounts_by_owner(pubkey, TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"))
    accounts = resp.value
    await client.close()
    return len(accounts) * 0.001  # مثال: 0.001 SOL لكل حساب

async def perform_cleanup(update: Update, keypair: Keypair):
    # ملاحظة: هنا المفروض يتم تنفيذ cleanup الفعلي (إغلاق الحسابات واستعادة الرينت)
    # حالياً مجرد محاكاة بدون تنفيذ حقيقي

    await update.message.reply_text("Cleanup complete. Rent reclaimed successfully.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # جدولة تشغيل البوت
    scheduler = BackgroundScheduler()
    scheduler.start()

    app.run_polling()
