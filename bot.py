import os
import base58
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from solana.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solana.publickey import PublicKey
from solana.transaction import Transaction
from spl.token.instructions import close_account, get_associated_token_address
from apscheduler.schedulers.background import BackgroundScheduler

# إعداد السجل
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
        "أرسل المفتاح الخاص لمحفظتك (Base58 format) لتحليل الحسابات الفارغة واسترجاع الرينت.\n\n"
        "⚠️ لا تشارك هذا المفتاح مع أي شخص!"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_states.get(user_id) == "awaiting_confirmation":
        if text.lower() in ["yes", "نعم"]:
            await update.message.reply_text("جاري التنفيذ...")
            await perform_cleanup(update, WALLET_INFO[user_id])
        else:
            await update.message.reply_text("تم الإلغاء.")
        user_states[user_id] = None
        return

    if not is_valid_base58_key(text):
        await update.message.reply_text("❌ المفتاح غير صالح.")
        return

    try:
        decoded_key = base58.b58decode(text)
        secret_key = decoded_key[:32] if len(decoded_key) == 64 else decoded_key
        keypair = Keypair.from_secret_key(secret_key)
        pubkey = str(keypair.public_key)

        WALLET_INFO[user_id] = keypair
        user_states[user_id] = "awaiting_confirmation"

        sol, count = await simulate_cleanup(pubkey)
        await update.message.reply_text(
            f"✅ المحفظة: {pubkey[:8]}...\n"
            f"الحسابات القابلة للإغلاق: {count}\n"
            f"العائد المتوقع: {sol:.6f} SOL\n\n"
            "هل تريد المتابعة؟ (نعم / لا)"
        )
    except Exception as e:
        logger.error("Error decoding key", exc_info=True)
        await update.message.reply_text("❌ حدث خطأ. تأكد من أن المفتاح صحيح.")

async def simulate_cleanup(pubkey: str):
    client = AsyncClient("https://api.mainnet-beta.solana.com")
    try:
        response = await client.get_token_accounts_by_owner(
            pubkey,
            TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        )
        total = 0
        for acc in response.value:
            info = await client.get_token_account_balance(acc['pubkey'])
            amount = float(info.value.amount)
            if amount == 0:
                total += 1
        return total * 0.00203928, total  # رينت الحساب
    except Exception as e:
        logger.error("Error in simulate_cleanup", exc_info=True)
        return 0.0, 0
    finally:
        await client.close()

async def perform_cleanup(update: Update, keypair: Keypair):
    client = AsyncClient("https://api.mainnet-beta.solana.com")
    pubkey = keypair.public_key
    try:
        response = await client.get_token_accounts_by_owner(
            str(pubkey),
            TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        )

        closed = 0
        for acc in response.value:
            token_account = PublicKey(acc['pubkey'])
            info = await client.get_token_account_balance(str(token_account))
            amount = float(info.value.amount)
            if amount == 0:
                tx = Transaction()
                tx.add(
                    close_account(
                        account=token_account,
                        dest=pubkey,
                        owner=pubkey,
                        program_id=PublicKey("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
                    )
                )
                await client.send_transaction(tx, keypair)
                closed += 1

        await update.message.reply_text(
            f"✅ تم تنظيف {closed} حساب.\n"
            f"العائد المتوقع: ~{closed * 0.00203928:.6f} SOL"
        )
    except Exception as e:
        logger.error("Error in perform_cleanup", exc_info=True)
        await update.message.reply_text("❌ حدث خطأ أثناء التنظيف.")
    finally:
        await client.close()

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("يرجى تعيين TELEGRAM_BOT_TOKEN في المتغيرات البيئية.")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = BackgroundScheduler()
    scheduler.start()

    logger.info("Starting bot...")
    app.run_polling()
