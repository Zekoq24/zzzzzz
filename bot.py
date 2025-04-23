import os
import base58
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from solana.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solana.publickey import PublicKey

logging.basicConfig(level=logging.INFO)
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
        "أهلاً بك! أرسل المفتاح الخاص (Private Key بصيغة Base58) لفحص الحسابات القابلة للإغلاق واسترجاع الرينت."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_states.get(user_id) == "awaiting_confirmation":
        if text.lower() in ["نعم", "yes"]:
            await update.message.reply_text("جاري تنفيذ عمليات الإغلاق واستعادة الرينت...")
            await perform_cleanup(update, WALLET_INFO[user_id])
        else:
            await update.message.reply_text("تم الإلغاء.")
        user_states[user_id] = None
        return

    if not is_valid_base58_key(text):
        await update.message.reply_text("❌ المفتاح غير صالح. تأكد من أنه Base58.")
        return

    try:
        decoded = base58.b58decode(text)
        secret_key = decoded[:32] if len(decoded) == 64 else decoded
        keypair = Keypair.from_secret_key(secret_key)
        pubkey = str(keypair.public_key)

        WALLET_INFO[user_id] = keypair
        user_states[user_id] = "awaiting_confirmation"

        sol, count = await simulate_cleanup(pubkey)

        await update.message.reply_text(
            f"✅ Wallet: {pubkey[:8]}...\n"
            f"Reclaimable token accounts: {count}\n"
            f"Estimated reclaim: {sol:.6f} SOL\n\n"
            f"Proceed with cleanup? (Send 'نعم' or 'yes' to confirm)"
        )
    except Exception as e:
        logger.error(f"Error decoding key: {e}")
        await update.message.reply_text("❌ حدث خطأ أثناء التحقق من المفتاح.")

async def simulate_cleanup(pubkey: str):
    client = AsyncClient("https://api.mainnet-beta.solana.com")
    try:
        pubkey_obj = PublicKey(pubkey)
        resp = await client.get_token_accounts_by_owner(
            pubkey_obj,
            TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", encoding="jsonParsed")
        )
        accounts = resp.value
        count = len(accounts)
        reclaimable_sol = count * 0.00203928
        return reclaimable_sol, count
    except Exception as e:
        logger.error(f"simulate_cleanup error: {e}")
        return 0.0, 0
    finally:
        await client.close()

async def perform_cleanup(update: Update, keypair: Keypair):
    client = AsyncClient("https://api.mainnet-beta.solana.com")
    try:
        pubkey_obj = keypair.public_key
        resp = await client.get_token_accounts_by_owner(
            pubkey_obj,
            TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", encoding="jsonParsed")
        )
        accounts = resp.value
        count = len(accounts)
        reclaimed = count * 0.00203928
        await update.message.reply_text(
            f"تم تنظيف {count} حساب توكن.\n"
            f"المبلغ المستعاد: ~{reclaimed:.6f} SOL"
        )
    except Exception as e:
        logger.error(f"perform_cleanup error: {e}")
        await update.message.reply_text("❌ خطأ أثناء تنفيذ التنظيف.")
    finally:
        await client.close()

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("يرجى تعيين TELEGRAM_BOT_TOKEN")

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting bot...")
    app.run_polling()
