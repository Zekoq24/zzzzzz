import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from solana.rpc.api import Client
from solana.keypair import Keypair
import base58

logging.basicConfig(level=logging.INFO)

# رابط شبكة سولانا الرئيسية
solana_client = Client("https://api.mainnet-beta.solana.com")

# تحقق من صحة المفتاح الخاص (Base58)
def is_valid_private_key(private_key: str) -> bool:
    try:
        decoded = base58.b58decode(private_key)
        return len(decoded) == 64
    except Exception:
        return False

# توليد keypair من المفتاح الخاص
def keypair_from_private_key(private_key: str) -> Keypair:
    decoded = base58.b58decode(private_key)
    return Keypair.from_secret_key(decoded)

# دالة /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send your Solana private key (Base58 format):")

# التعامل مع الرسائل
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    private_key = update.message.text.strip()

    if not is_valid_private_key(private_key):
        await update.message.reply_text("Invalid private key. Make sure it's in Base58 format.")
        return

    keypair = keypair_from_private_key(private_key)
    pubkey = keypair.public_key

    await update.message.reply_text(f"Checking wallet: {pubkey}...")

    # هنا نضيف خطوات تحليل الحساب لاحقًا
    await update.message.reply_text("Expected SOL from cleanup: 0.0143 SOL\nDo you want to proceed? (yes/no)")

# تشغيل البوت
async def main():
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    app = ApplicationBuilder().token(bot_token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await app.run_polling()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
