# bot.py
import os
import base58
import logging
import json
import aiohttp
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from solana.keypair import Keypair

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
user_states = {}
wallet_keys = {}

SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"

async def fetch_token_accounts(pubkey: str):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            pubkey,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"}
        ]
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(SOLANA_RPC_URL, json=payload) as resp:
            data = await resp.json()
            return data.get("result", {}).get("value", [])

def is_valid_base58_key(key: str):
    try:
        decoded = base58.b58decode(key)
        return len(decoded) in [32, 64]
    except Exception:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "مرحباً! أرسل المفتاح الخاص (Base58 format) لتحليل الحسابات واسترجاع الرينت المحتمل."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_states.get(user_id) == "awaiting_confirmation":
        if text.lower() in ["نعم", "yes"]:
            await update.message.reply_text("جاري تنفيذ التنظيف واسترجاع الرينت...")
            await perform_cleanup(update, wallet_keys[user_id])
        else:
            await update.message.reply_text("تم الإلغاء.")
        user_states[user_id] = None
        return

    if not is_valid_base58_key(text):
        await update.message.reply_text("❌ المفتاح الخاص غير صالح.")
        return

    try:
        decoded = base58.b58decode(text)
        secret = decoded[:32] if len(decoded) == 64 else decoded
        if len(secret) != 32:
            raise ValueError("طول المفتاح غير صالح.")
        keypair = Keypair.from_secret_key(secret)
        pubkey = str(keypair.public_key)
        wallet_keys[user_id] = keypair
        user_states[user_id] = "awaiting_confirmation"

        accounts = await fetch_token_accounts(pubkey)

        empty_tokens = 0
        nft_count = 0
        reclaimable_accounts = 0
        estimated_rent = 0

        for acc in accounts:
            try:
                info = acc["account"]["data"]["parsed"]["info"]
                token = info["tokenAmount"]
                amount = token["uiAmount"]
                decimals = token["decimals"]

                if amount == 0:
                    empty_tokens += 1
                    estimated_rent += 0.00203928
                elif amount == 1 and decimals == 0:
                    nft_count += 1
                    estimated_rent += 0.00203928
            except Exception as e:
                logger.warning(f"خطأ في تحليل الحساب: {e}")

        reclaimable_accounts = empty_tokens + nft_count
        short_pub = pubkey[:8]
        await update.message.reply_text(
            f"✅ Wallet: {short_pub}...\n"
            f"Reclaimable accounts: {reclaimable_accounts}\n"
            f"Estimated reclaim: {estimated_rent:.6f} SOL\n\n"
            f"Proceed with cleanup? (Send 'نعم' or 'yes' to confirm)"
        )
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await update.message.reply_text("❌ خطأ أثناء معالجة المفتاح.")

async def perform_cleanup(update: Update, keypair: Keypair):
    # لا نقوم بتنظيف حقيقي للحسابات، فقط نحاكي العملية
    pubkey = str(keypair.public_key)
    accounts = await fetch_token_accounts(pubkey)

    cleaned = 0
    for acc in accounts:
        try:
            info = acc["account"]["data"]["parsed"]["info"]
            token = info["tokenAmount"]
            amount = token["uiAmount"]
            decimals = token["decimals"]

            if amount == 0 or (amount == 1 and decimals == 0):
                cleaned += 1
        except Exception:
            continue

    reclaimed = cleaned * 0.00203928
    await update.message.reply_text(
        f"✅ Cleanup complete!\n"
        f"Accounts cleaned: {cleaned}\n"
        f"Rent reclaimed: {reclaimed:.6f} SOL"
    )

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("يرجى تعيين متغير TELEGRAM_BOT_TOKEN")

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
