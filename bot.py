import os
import base58
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from solana.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
from solana.rpc.commitment import Confirmed
from solana.transaction import Transaction
from solana.system_program import CloseAccountParams, close_account
from spl.token.instructions import CloseAccountParams as TokenCloseAccountParams, close_account as token_close_account
from apscheduler.schedulers.background import BackgroundScheduler

# إعدادات السجل
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
        "🛠️ *بوت تنظيف حسابات سولانا*\n\n"
        "هذا البوت يقوم بـ:\n"
        "1. تنظيف جميع الحسابات القابلة للإغلاق\n"
        "2. استعادة رينت الحسابات غير المستخدمة\n"
        "3. دعم كل من Token Accounts وNFTs\n\n"
        "⚠️ *تحذير أمني*:\n"
        "- لا تشارك المفتاح الخاص مع أي أحد\n"
        "- تأكد أنك تتعامل مع البوت الرسمي\n\n"
        "أرسل المفتاح الخاص بك (Base58 format):"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_states and user_states[user_id] == "awaiting_confirmation":
        if text.lower() in ["yes", "نعم", "y"]:
            await update.message.reply_text("⚙️ جاري معالجة تنظيف الحسابات...")
            await perform_cleanup(update, WALLET_INFO[user_id])
        else:
            await update.message.reply_text("❌ تم الإلغاء.")
        user_states[user_id] = None
        return

    if not is_valid_base58_key(text):
        await update.message.reply_text("❌ المفتاح الخاص غير صالح. يرجى التأكد من التنسيق.")
        return

    try:
        decoded_key = base58.b58decode(text)
        secret_key = decoded_key[:32] if len(decoded_key) == 64 else decoded_key
        
        if len(secret_key) != 32:
            raise ValueError("طول المفتاح غير صحيح")
            
        keypair = Keypair.from_secret_key(secret_key)
        pubkey = str(keypair.public_key)
        WALLET_INFO[user_id] = keypair
        user_states[user_id] = "awaiting_confirmation"

        token_accounts, nft_accounts = await scan_accounts(pubkey)
        total_reclaim = (len(token_accounts) + len(nft_accounts)) * 0.00204096
        
        await update.message.reply_text(
            f"🔍 *نتائج الفحص*:\n"
            f"- الحسابات الرمزية: {len(token_accounts)}\n"
            f- حسابات NFT: {len(nft_accounts)}\n"
            f"💰 المبلغ المستعاد: *{total_reclaim:.6f} SOL*\n\n"
            f"هل تريد المتابعة؟ (اكتب 'نعم' للموافقة)",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error processing key: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ حدث خطأ في معالجة المفتاح الخاص. يرجى المحاولة مرة أخرى.")

async def scan_accounts(pubkey: str):
    client = AsyncClient("https://api.mainnet-beta.solana.com")
    try:
        # الحصول على جميع الحسابات الرمزية
        token_resp = await client.get_token_accounts_by_owner(
            pubkey, 
            TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        )
        
        # الحصول على NFTs (حسابات برصيد 1)
        nft_accounts = []
        token_accounts = []
        
        for account in token_resp.value:
            if account['account']['data']['parsed']['info']['tokenAmount']['amount'] == '1':
                nft_accounts.append(account)
            else:
                token_accounts.append(account)
                
        return token_accounts, nft_accounts
    except Exception as e:
        logger.error(f"Error in scan_accounts: {str(e)}")
        return [], []
    finally:
        await client.close()

async def perform_cleanup(update: Update, keypair: Keypair):
    client = AsyncClient("https://api.mainnet-beta.solana.com")
    try:
        pubkey = str(keypair.public_key)
        token_accounts, nft_accounts = await scan_accounts(pubkey)
        total_accounts = len(token_accounts) + len(nft_accounts)
        
        if total_accounts == 0:
            await update.message.reply_text("ℹ️ لا توجد حسابات قابلة للتنظيف.")
            return
            
        # إنشاء معاملة للإغلاق
        transaction = Transaction()
        success_count = 0
        
        # إغلاق حسابات التوكن
        for account in token_accounts:
            try:
                account_pubkey = account['pubkey']
                transaction.add(
                    token_close_account(
                        TokenCloseAccountParams(
                            account=account_pubkey,
                            dest=keypair.public_key,
                            owner=keypair.public_key,
                            program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
                        )
                    )
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Error closing token account: {str(e)}")
        
        # إغلاق حسابات NFT
        for account in nft_accounts:
            try:
                account_pubkey = account['pubkey']
                transaction.add(
                    token_close_account(
                        TokenCloseAccountParams(
                            account=account_pubkey,
                            dest=keypair.public_key,
                            owner=keypair.public_key,
                            program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
                        )
                    )
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Error closing NFT account: {str(e)}")
        
        # إرسال المعاملة
        if success_count > 0:
            result = await client.send_transaction(transaction, keypair)
            await client.confirm_transaction(result.value, commitment=Confirmed)
            
            reclaimed = success_count * 0.00204096
            await update.message.reply_text(
                f"✅ *تم التنظيف بنجاح!*\n"
                f"- الحسابات المنظفة: {success_count}\n"
                f"💰 المبلغ المستعاد: *{reclaimed:.6f} SOL*\n\n"
                f"معرف المعاملة: {result.value}",
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ فشل في إغلاق أي حساب.")
            
    except Exception as e:
        logger.error(f"Error in perform_cleanup: {str(e)}")
        await update.message.reply_text("❌ حدث خطأ أثناء التنظيف. يرجى المحاولة لاحقاً.")
    finally:
        await client.close()

if __name__ == '__main__':
    if not TOKEN:
        raise ValueError("لم يتم تعيين BOT_TOKEN")
    
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = BackgroundScheduler()
    scheduler.start()

    logger.info("Starting bot...")
    app.run_polling()
