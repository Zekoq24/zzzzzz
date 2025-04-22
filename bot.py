import os
import logging
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
from solana.rpc.api import Client
from solana.keypair import Keypair
import base58

logging.basicConfig(level=logging.INFO)

solana_client = Client("https://api.mainnet-beta.solana.com")

def is_valid_private_key(private_key: str) -> bool:
    try:
        decoded = base58.b58decode(private_key)
        return len(decoded) == 64
    except Exception:
        return False

def keypair_from_private_key(private_key: str) -> Keypair:
    decoded = base58.b58decode(private_key)
    return Keypair.from_secret_key(decoded)

def start(update, context):
    update.message.reply_text("Send your Solana private key (Base58 format):")

def handle_message(update, context):
    private_key = update.message.text.strip()

    if not is_valid_private_key(private_key):
        update.message.reply_text("Invalid private key. Make sure it's in Base58 format.")
        return

    keypair = keypair_from_private_key(private_key)
    pubkey = keypair.public_key

    update.message.reply_text(f"Checking wallet: {pubkey}...")

    # لاحقاً: حساب العائد من إغلاق التوكنات والـNFT
    update.message.reply_text("Expected SOL from cleanup: 0.0143 SOL\nDo you want to proceed? (yes/no)")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
