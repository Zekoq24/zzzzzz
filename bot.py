import os
import logging
import requests
import datetime
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from base58 import b58decode
from solders.keypair import Keypair
from solana.rpc.api import Client
from solana.transaction import Transaction
from solana.rpc.types import TxOpts
from solana.system_program import CloseAccountParams, close_account
from solana.publickey import PublicKey

# إعدادات
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
client = Client("https://api.mainnet-beta.solana.com")

# متغيرات المستخدمين
user_wallets = {}
user_states = {}

# /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_states[message.chat.id] = None
    bot.reply_to(message, "Welcome 👋\n\nSend me the wallet address you want to check 🔍")

# استقبال عنوان المحفظة
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) is None)
def handle_wallet(message):
    wallet = message.text.strip()
    if not (32 <= len(wallet) <= 44):
        bot.reply_to(message, "❗ Invalid address, try again.")
        return

    solana_api = "https://api.mainnet-beta.solana.com"
    headers = {"Content-Type": "application/json"}
    data = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"}
        ]
    }

    try:
        response = requests.post(solana_api, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()

        accounts = result["result"]["value"]
        total_rent = 0
        empty_accounts = []

        for acc in accounts:
            info = acc["account"]["data"]["parsed"]["info"]
            amount = info["tokenAmount"]["uiAmount"]
            if amount == 0:
                empty_accounts.append(acc["pubkey"])
                total_rent += 0.00203928  # قيمة الرينت التقريبية لكل حساب

        sol_value = round(total_rent / 3, 5)
        short_wallet = wallet[:4] + "..." + wallet[-4:]

        if sol_value < 0.01:
            bot.send_message(
                message.chat.id,
                "🚫 No significant value found in this wallet."
            )
            return

        user_wallets[message.chat.id] = {
            "wallet": wallet,
            "amount": sol_value,
            "accounts": empty_accounts
        }

        result_text = (
            f"Wallet: `{short_wallet}`\n"
            f"Estimated reclaimable rent: `{sol_value} SOL` 💰\n\n"
            "Do you want to proceed with cleanup (burn)?"
        )

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Confirm", callback_data="confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        )

        bot.send_message(message.chat.id, result_text, parse_mode='Markdown', reply_markup=markup)

    except Exception as e:
        logging.error(f"Error checking wallet: {e}")
        bot.send_message(message.chat.id, "❌ Error checking the wallet.")

# تأكيد أو إلغاء
@bot.callback_query_handler(func=lambda call: call.data in ["confirm", "cancel"])
def handle_decision(call):
    if call.data == "confirm":
        user_states[call.message.chat.id] = "awaiting_private_key"
        bot.send_message(call.message.chat.id, "Please send the private key (Base58) to proceed:")
    else:
        bot.send_message(call.message.chat.id, "Operation canceled.")
        user_states[call.message.chat.id] = None

# استقبال المفتاح الخاص
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "awaiting_private_key")
def handle_private_key(message):
    try:
        private_key_base58 = message.text.strip()
        secret = b58decode(private_key_base58)
        if len(secret) != 64:
            raise ValueError("Invalid key length")

        keypair = Keypair.from_bytes(secret)
        pubkey = str(keypair.pubkey())
        expected_wallet = user_wallets[message.chat.id]["wallet"]

        if pubkey != expected_wallet:
            bot.send_message(message.chat.id, "❌ Private key does not match the provided wallet.")
            return

        bot.send_message(message.chat.id, "Processing cleanup... please wait.")
        perform_cleanup(keypair, message.chat.id)
        user_states[message.chat.id] = None

    except Exception as e:
        logging.error(f"Private key error: {e}")
        bot.send_message(message.chat.id, "❌ Invalid private key. Make sure it's Base58 format.")

# تنفيذ الحرق
def perform_cleanup(keypair, chat_id):
    try:
        wallet = str(keypair.pubkey())
        accounts = user_wallets[chat_id]["accounts"]
        tx = Transaction()

        for acc in accounts:
            acc_pubkey = PublicKey(acc)
            close_ix = close_account(
                CloseAccountParams(
                    account=acc_pubkey,
                    destination=PublicKey(wallet),
                    owner=PublicKey(wallet)
                )
            )
            tx.add(close_ix)

        if not tx.instructions:
            bot.send_message(chat_id, "No empty accounts to close.")
            return

        result = client.send_transaction(tx, keypair, opts=TxOpts(skip_confirmation=False))
        bot.send_message(chat_id, f"✅ Cleanup complete! Transaction:\n`{result['result']}`", parse_mode='Markdown')

    except Exception as e:
        logging.error(f"Cleanup error: {e}")
        bot.send_message(chat_id, "❌ Failed to execute cleanup.")

# تشغيل البوت
bot.infinity_polling()
