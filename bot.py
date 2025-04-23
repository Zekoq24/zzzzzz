import os
import telebot
import requests
import base58
import base64
from solana.rpc.api import Client
from solana.transaction import Transaction
from solana.keypair import Keypair
from solana.publickey import PublicKey
from solana.rpc.types import TxOpts
from solana.system_program import CloseAccountParams, close_account
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RPC_URL = "https://api.mainnet-beta.solana.com"
bot = telebot.TeleBot(BOT_TOKEN)
client = Client(RPC_URL)

user_states = {}
wallet_data = {}

@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.reply_to(message, "Send your wallet address:")
    user_states[message.chat.id] = 'awaiting_wallet'

@bot.message_handler(func=lambda m: user_states.get(m.chat.id) == 'awaiting_wallet')
def handle_wallet(message):
    address = message.text.strip()
    if not (32 <= len(address) <= 44):
        bot.reply_to(message, "❌ Invalid wallet address.")
        return

    user_states[message.chat.id] = None
    wallet_data[message.chat.id] = {"address": address}

    response = requests.post(RPC_URL, json={
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            address,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"}
        ]
    }, headers={"Content-Type": "application/json"})

    result = response.json().get("result", {}).get("value", [])
    tokens = []
    close_candidates = []
    for acc in result:
        info = acc["account"]["data"]["parsed"]["info"]
        amount = info["tokenAmount"]["uiAmount"]
        symbol = info.get("mint", "")[:4]
        if amount > 0:
            tokens.append(f'{symbol}... = {amount}')
        else:
            close_candidates.append(acc["pubkey"])

    wallet_data[message.chat.id]["close_accounts"] = close_candidates

    text = f"Wallet: {address[:4]}...{address[-4:]}\n"
    if tokens:
        text += "\nTokens found:\n" + "\n".join(tokens)
    text += f"\n\nEmpty accounts to close: {len(close_candidates)}"
    text += f"\nExpected return: {round(len(close_candidates) * 0.00203928, 5)} SOL"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ Confirm", callback_data="confirm"))
    bot.send_message(message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "confirm")
def handle_confirm(call):
    bot.send_message(call.message.chat.id, "Send your private key:")
    user_states[call.message.chat.id] = "awaiting_key"

@bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "awaiting_key")
def handle_key(message):
    try:
        priv_key = base58.b58decode(message.text.strip())
        keypair = Keypair.from_secret_key(priv_key)
        user_states[message.chat.id] = None

        wallet_address = wallet_data[message.chat.id]["address"]
        if str(keypair.public_key) != wallet_address:
            bot.send_message(message.chat.id, "❌ Private key doesn't match wallet.")
            return

        close_accounts = wallet_data[message.chat.id]["close_accounts"]
        if not close_accounts:
            bot.send_message(message.chat.id, "✅ Verified.\nAccounts ready to close: 0")
            return

        # تنفيذ إغلاق الحسابات
        instructions = []
        for acc in close_accounts:
            instructions.append(
                close_account(
                    CloseAccountParams(
                        account=PublicKey(acc),
                        destination=keypair.public_key,
                        owner=keypair.public_key
                    )
                )
            )

        txn = Transaction()
        txn.add(*instructions)

        result = client.send_transaction(txn, keypair, opts=TxOpts(skip_preflight=True, preflight_commitment="confirmed"))
        sig = result['result']
        bot.send_message(
            message.chat.id,
            f"✅ Accounts closed.\n[View on SolScan](https://solscan.io/tx/{sig})",
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error: {str(e)}")

bot.polling()
