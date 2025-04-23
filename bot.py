import os
import requests
import logging
import telebot
from base58 import b58decode
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from solders.keypair import Keypair
from solders.transaction import Transaction
from solders.instruction import Instruction
from solders.pubkey import Pubkey
from solders.message import Message
from solders.rpc.config import RpcSendTransactionConfig
from solders.system_program import close_account, CloseAccountParams
import base64
import json

# الإعدادات
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
RPC_URL = "https://api.mainnet-beta.solana.com"

# تخزين الحالة
user_wallets = {}
user_states = {}

# /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_states[message.chat.id] = None
    bot.reply_to(message, "Welcome 👋\n\nSend me the wallet address you want to check 🔍")

# فحص المحفظة
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) is None)
def handle_wallet(message):
    wallet = message.text.strip()
    if not (32 <= len(wallet) <= 44):
        bot.reply_to(message, "❗ Invalid address, try again.")
        return

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
        response = requests.post(RPC_URL, json=data, headers=headers)
        accounts = response.json()["result"]["value"]

        empty_accounts = []
        total_rent = 0
        for acc in accounts:
            info = acc["account"]["data"]["parsed"]["info"]
            amount = info["tokenAmount"]["uiAmount"]
            if amount == 0:
                empty_accounts.append(acc["pubkey"])
                total_rent += 0.00203928  # تقريباً

        sol_value = round(total_rent / 3, 5)
        short_wallet = wallet[:4] + "..." + wallet[-4:]

        if sol_value < 0.01:
            bot.send_message(message.chat.id, "🚫 No significant value found.")
            return

        user_wallets[message.chat.id] = {
            "wallet": wallet,
            "amount": sol_value,
            "accounts": empty_accounts
        }

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Confirm", callback_data="confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        )

        bot.send_message(
            message.chat.id,
            f"Wallet: `{short_wallet}`\n"
            f"Estimated reclaimable rent: `{sol_value} SOL`\n\n"
            "Do you want to proceed with cleanup?",
            parse_mode='Markdown',
            reply_markup=markup
        )

    except Exception as e:
        logging.error(e)
        bot.send_message(message.chat.id, "❌ Error while checking the wallet.")

# التأكيد
@bot.callback_query_handler(func=lambda call: call.data in ["confirm", "cancel"])
def handle_confirmation(call):
    if call.data == "confirm":
        user_states[call.message.chat.id] = "awaiting_private_key"
        bot.send_message(call.message.chat.id, "Please send the **private key (Base58)** to proceed:", parse_mode='Markdown')
    else:
        user_states[call.message.chat.id] = None
        bot.send_message(call.message.chat.id, "❌ Operation cancelled.")

# استقبال المفتاح الخاص
@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "awaiting_private_key")
def handle_private_key(message):
    try:
        privkey = b58decode(message.text.strip())
        keypair = Keypair.from_bytes(privkey)
        pubkey = str(keypair.pubkey())
        expected_wallet = user_wallets[message.chat.id]["wallet"]

        if pubkey != expected_wallet:
            bot.send_message(message.chat.id, "❌ Private key does not match wallet address.")
            return

        bot.send_message(message.chat.id, "Processing cleanup... please wait.")
        perform_cleanup(keypair, message.chat.id)

    except Exception as e:
        logging.error(e)
        bot.send_message(message.chat.id, "❌ Invalid private key.")

# تنفيذ عملية الحرق
def perform_cleanup(keypair: Keypair, chat_id: int):
    accounts = user_wallets[chat_id]["accounts"]
    destination = keypair.pubkey()
    instructions = []

    for acc in accounts:
        acc_pubkey = Pubkey.from_string(acc)
        ix = close_account(CloseAccountParams(
            account=acc_pubkey,
            destination=destination,
            owner=destination
        ))
        instructions.append(ix)

    if not instructions:
        bot.send_message(chat_id, "No empty accounts to close.")
        return

    transaction = Transaction()
    transaction.add(*instructions)

    # التوقيع
    transaction.sign([keypair])
    
    # إرسال المعاملة
    try:
        raw_tx = base64.b64encode(transaction.serialize()).decode("utf-8")
        send_data = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [raw_tx, {"skipPreflight": False}]
        }
        
        response = requests.post(RPC_URL, json=send_data)
        result = response.json()
        if "result" in result:
            bot.send_message(chat_id, f"✅ Cleanup complete!\nTransaction: `{result['result']}`", parse_mode='Markdown')
        else:
            bot.send_message(chat_id, f"❌ Transaction failed:\n{result}", parse_mode='Markdown')
    except Exception as e:
        logging.error(e)
        bot.send_message(chat_id, "❌ Failed to send transaction.")

# تشغيل البوت
bot.infinity_polling()
