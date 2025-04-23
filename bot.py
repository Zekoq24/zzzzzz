import os
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import base58
import requests
import base64
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RPC_URL = "https://api.mainnet-beta.solana.com"
bot = telebot.TeleBot(BOT_TOKEN)
client = Client(RPC_URL)

user_wallets = {}
user_states = {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_states[message.chat.id] = None
    bot.reply_to(message, "Send me a Solana wallet address to check.")

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) is None)
def handle_wallet(message):
    address = message.text.strip()
    if not (32 <= len(address) <= 44):
        bot.reply_to(message, "❗ Invalid wallet address.")
        return

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            address,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"}
        ]
    }

    response = requests.post(RPC_URL, json=payload)
    result = response.json().get("result", {}).get("value", [])

    total_rent = 0
    accounts_to_close = []
    display_tokens = []

    for item in result:
        acc = item["account"]
        info = acc["data"]["parsed"]["info"]
        token_amount = info["tokenAmount"]
        amount = float(token_amount["uiAmount"] or 0)
        decimals = token_amount["decimals"]
        mint = info["mint"]
        owner = info["owner"]

        has_name = decimals != 0 or amount != 0 or True  # إظهار أي توكن
        if has_name:
            display_tokens.append(f"{mint[:4]}...{mint[-4:]} = {amount}")

        if amount == 0:
            accounts_to_close.append(item["pubkey"])
            total_rent += 0.00203928

    if not result:
        bot.reply_to(message, "❗ No token accounts found.")
        return

    user_wallets[message.chat.id] = {
        "wallet": address,
        "accounts": accounts_to_close
    }

    response_msg = f"Wallet: `{address[:4]}...{address[-4:]}`\n"
    response_msg += f"Tokens found:\n" + "\n".join(display_tokens[:10]) + ("\n..." if len(display_tokens) > 10 else "")
    response_msg += f"\n\nEmpty accounts to close: `{len(accounts_to_close)}`\nExpected return: `{round(total_rent, 5)} SOL`"

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Confirm", callback_data="confirm"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel")
    )

    bot.send_message(message.chat.id, response_msg, parse_mode="Markdown", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "confirm")
def handle_confirm(call):
    bot.send_message(call.message.chat.id, "Please send your private key:")
    user_states[call.message.chat.id] = "awaiting_private_key"

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "awaiting_private_key")
def handle_private_key(message):
    try:
        private_key = message.text.strip()
        decoded_key = base58.b58decode(private_key)

        # تحقق من صحة المفتاح الخاص
        if len(decoded_key) != 64:
            bot.reply_to(message, "❌ Invalid private key length.")
            return

        keypair = Keypair.from_bytes(decoded_key)
        pubkey = str(keypair.pubkey())

        if pubkey != user_wallets[message.chat.id]["wallet"]:
            bot.reply_to(message, "❌ Private key does not match wallet address.")
            return

        accounts = user_wallets[message.chat.id]["accounts"]
        bot.reply_to(message, f"✅ Verified.\nAccounts ready to close: {len(accounts)}\n(تنفيذ الإغلاق غير مضاف هنا)")
    except Exception as e:
        bot.reply_to(message, "❌ Invalid private key.")

bot.polling()
