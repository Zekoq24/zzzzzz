import os
import telebot
from solana_agentkit.core import SolanaAgent

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
agent = SolanaAgent("https://api.mainnet-beta.solana.com")

user_wallets = {}
user_states = {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Send your Solana wallet address to analyze.")

@bot.message_handler(func=lambda m: user_states.get(m.chat.id) is None)
def handle_wallet(message):
    wallet = message.text.strip()
    result = agent.analyze_wallet(wallet)
    if not result:
        bot.reply_to(message, "No empty accounts found or invalid wallet.")
        return

    user_wallets[message.chat.id] = {"wallet": wallet}
    msg = f"Found {result['empty_accounts_count']} empty accounts.\nEstimated return: {result['estimated_rent']} SOL"
    user_states[message.chat.id] = "awaiting_confirmation"

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Confirm", callback_data="confirm"),
        telebot.types.InlineKeyboardButton("❌ Cancel", callback_data="cancel")
    )
    bot.send_message(message.chat.id, msg, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "confirm")
def handle_confirm(call):
    user_states[call.message.chat.id] = "awaiting_private_key"
    bot.send_message(call.message.chat.id, "Now send your private key (Base58 format):")

@bot.callback_query_handler(func=lambda call: call.data == "cancel")
def handle_cancel(call):
    user_states[call.message.chat.id] = None
    bot.send_message(call.message.chat.id, "Cancelled.")

@bot.message_handler(func=lambda m: user_states.get(m.chat.id) == "awaiting_private_key")
def handle_private_key(message):
    private_key = message.text.strip()
    wallet = user_wallets[message.chat.id]["wallet"]
    try:
        result = agent.cleanup_wallet(private_key, wallet)
        bot.send_message(message.chat.id, f"Done! Reclaimed: {result['sol_reclaimed']} SOL")
    except Exception as e:
        bot.send_message(message.chat.id, f"Error: {str(e)}")
    user_states[message.chat.id] = None

bot.polling()
