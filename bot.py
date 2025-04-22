import os
import base58
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from solana.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solana.transaction import Transaction
from spl.token.instructions import close_account, get_associated_token_address
from apscheduler.schedulers.background import BackgroundScheduler

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
        "Welcome! Send your Solana private key (Base58) to analyze reclaimable rent and clean unused token accounts.\n\n"
        "**Security Notice**:\n- Don't share this key with anyone.\n- Recommended to use a new empty wallet for safety."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_states and user_states[user_id] == "awaiting_confirmation":
        if text.lower() in ["yes", "نعم"]:
            await update.message.reply_text("Processing cleanup...")
            await perform_cleanup(update, WALLET_INFO[user_id])
        else:
            await update.message.reply_text("Cancelled.")
        user_states[user_id] = None
        return

    if not is_valid_base58_key(text):
        await update.message.reply_text("Invalid private key. Make sure it's Base58 and correct.")
        return

    try:
        decoded_key = base58.b58decode(text)
        secret_key = decoded_key[:32] if len(decoded_key) == 64 else decoded_key

        if len(secret_key) != 32:
            raise ValueError("Invalid key length")

        keypair = Keypair.from_secret_key(secret_key)
        pubkey = str(keypair.public_key)
        WALLET_INFO[user_id] = keypair
        user_states[user_id] = "awaiting_confirmation"

        sol, count = await simulate_cleanup(pubkey)
        await update.message.reply_text(
            f"✅ Wallet: {pubkey[:8]}...\n"
            f"Reclaimable accounts: {count}\n"
            f"Estimated reclaim: {sol:.6f} SOL\n\n"
            "Proceed with cleanup? (Send 'نعم' or 'yes' to confirm)"
        )
    except Exception as e:
        logger.error(f"Error processing key: {str(e)}", exc_info=True)
        await update.message.reply_text("Error processing private key. Please try again.")

async def simulate_cleanup(pubkey: str):
    client = AsyncClient("https://api.mainnet-beta.solana.com")
    try:
        resp = await client.get_token_accounts_by_owner(
            pubkey,
            TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", encoding="jsonParsed")
        )
        accounts = resp.value
        reclaimable = 0

        for acc in accounts:
            info = acc['account']['data']['parsed']['info']
            owner = info['owner']
            amount = float(info['tokenAmount']['uiAmount'] or 0)
            if amount == 0 and owner == pubkey:
                reclaimable += 1

        return reclaimable * 0.00203928, reclaimable
    except Exception as e:
        logger.error(f"Simulation error: {e}")
        return 0.0, 0
    finally:
        await client.close()

async def perform_cleanup(update: Update, keypair: Keypair):
    client = AsyncClient("https://api.mainnet-beta.solana.com")
    try:
        pubkey = keypair.public_key
        resp = await client.get_token_accounts_by_owner(
            str(pubkey),
            TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", encoding="jsonParsed")
        )
        accounts = resp.value
        tx = Transaction()
        reclaimable = 0

        for acc in accounts:
            acc_pubkey = acc['pubkey']
            info = acc['account']['data']['parsed']['info']
            amount = float(info['tokenAmount']['uiAmount'] or 0)
            owner = info['owner']

            if amount == 0 and owner == str(pubkey):
                tx.add(close_account(
                    account=acc_pubkey,
                    dest=pubkey,
                    owner=pubkey,
                    program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
                ))
                reclaimable += 1

        if reclaimable == 0:
            await update.message.reply_text("No accounts to clean.")
            return

        res = await client.send_transaction(tx, keypair)
        await client.confirm_transaction(res.value)
        sol_returned = reclaimable * 0.00203928
        await update.message.reply_text(
            f"✅ Cleanup complete!\nAccounts closed: {reclaimable}\nReclaimed: ~{sol_returned:.6f} SOL"
        )
    except Exception as e:
        logger.error(f"Cleanup error: {e}")
        await update.message.reply_text("Error during cleanup. Try again later.")
    finally:
        await client.close()

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = BackgroundScheduler()
    scheduler.start()

    logger.info("Bot is running...")
    app.run_polling()
