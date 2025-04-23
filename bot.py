import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import base58
from solana.keypair import Keypair
from solana.rpc.api import Client
import logging

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = 'TELEGRAM_BOT_TOKEN'
bot = telebot.TeleBot(BOT_TOKEN)
solana_client = Client("https://api.mainnet-beta.solana.com")

user_states = {}
user_wallets = {}

# الحالة: انتظار تأكيد الحرق
WAITING_CONFIRMATION = 'waiting_confirmation'
# الحالة: انتظار المفتاح الخاص
WAITING_PRIVATE_KEY = 'waiting_private_key'

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "Welcome!\n\nSend your Solana wallet address to check cleanup value.")

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) is None)
def handle_wallet(message):
    wallet = message.text.strip()
    if not (32 <= len(wallet) <= 44):
        bot.reply_to(message, "❗ Invalid address. Please send a valid Solana wallet address.")
        return

    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                {"encoding": "jsonParsed"}
            ]
        }
        response = requests.post("https://api.mainnet-beta.solana.com", json=payload)
        result = response.json()["result"]["value"]

        count = len(result)
        estimated_sol = count * 0.00203928
        short_wallet = wallet[:4] + "..." + wallet[-4:]

        user_wallets[message.chat.id] = {"pubkey": wallet, "accounts": result}
        user_states[message.chat.id] = WAITING_CONFIRMATION

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Yes", callback_data="confirm_burn"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        )

        bot.send_message(
            message.chat.id,
            f"Wallet: `{short_wallet}`\n"
            f"Reclaimable Accounts: {count}\n"
            f"Estimated SOL: `{estimated_sol:.6f}`\n\n"
            f"Do you want to proceed with cleanup?",
            parse_mode='Markdown',
            reply_markup=markup
        )
    except Exception as e:
        bot.reply_to(message, "❌ Error while checking wallet.")
        logging.error(e)

@bot.callback_query_handler(func=lambda call: call.data == "confirm_burn")
def ask_private_key(call):
    bot.send_message(call.message.chat.id, "Please send your private key (Base58 format) to proceed.")
    user_states[call.message.chat.id] = WAITING_PRIVATE_KEY

@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def cancel_action(call):
    bot.send_message(call.message.chat.id, "❌ Cancelled.")
    user_states[call.message.chat.id] = None

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == WAITING_PRIVATE_KEY)
def handle_private_key(message):
    key_text = message.text.strip()
    try:
        secret = base58.b58decode(key_text)
        if len(secret) not in [32, 64]:
            raise ValueError("Invalid key length")

        keypair = Keypair.from_secret_key(secret[:32])
        pubkey = str(keypair.public_key)

        saved_pubkey = user_wallets.get(message.chat.id, {}).get("pubkey")
        if pubkey != saved_pubkey:
            bot.reply_to(message, "❌ This private key does not match the previous address.")
            return

        count = 0
        for acc in user_wallets[message.chat.id]["accounts"]:
            acc_pubkey = acc["pubkey"]
            try:
                tx = solana_client.close_account(acc_pubkey, keypair)
                if tx.get("result"):
                    count += 1
            except Exception as e:
                logging.warning(f"Failed to close account {acc_pubkey}: {e}")
                continue

        total_sol = count * 0.00203928
        bot.send_message(
            message.chat.id,
            f"✅ Cleanup complete.\nClosed accounts: {count}\nReclaimed: ~{total_sol:.6f} SOL"
        )
    except Exception as e:
        logging.error(e)
        bot.reply_to(message, "❌ Invalid private key or error occurred.")
    finally:
        user_states[message.chat.id] = None
        user_wallets[message.chat.id] = None

bot.polling()
