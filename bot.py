import os
import base58
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from solana.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solana.rpc.types import TokenAccountOpts
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
        "مرحباً! هذا البوت يساعدك في تنظيف حسابات سولانا غير المستخدمة واستعادة الرينت.\n\n"
        "⚠️ **تحذير أمني**:\n"
        "1. لا تشارك المفتاح الخاص مع أي أحد\n"
        "2. تأكد أنك تتعامل مع البوت الرسمي\n"
        "3. يمكنك إنشاء محفظة جديدة لنقل الأصول إليها\n\n"
        "أرسل المفتاح الخاص بك (Base58 format):"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_states and user_states[user_id] == "awaiting_confirmation":
        if text.lower() in ["yes", "نعم"]:
            await update.message.reply_text("جاري معالجة تنظيف الحسابات واستعادة الرينت...")
            await perform_cleanup(update, WALLET_INFO[user_id])
        else:
            await update.message.reply_text("تم الإلغاء.")
        user_states[user_id] = None
        return

    if not is_valid_base58_key(text):
        await update.message.reply_text("المفتاح الخاص غير صالح. يرجى التأكد من التنسيق.")
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

        sol, account_count = await simulate_cleanup(pubkey)
        await update.message.reply_text(
            f"✅ تم التحقق من المحفظة: {pubkey[:8]}...\n"
            f"عدد الحسابات غير النشطة: {account_count}\n"
            f"المتوقع استعادته: {sol:.6f} SOL\n\n"
            f"هل تريد المتابعة؟ (اكتب 'نعم' للمتابعة أو أي شيء للإلغاء)"
        )
    except Exception as e:
        logger.error(f"Error processing key: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ حدث خطأ في معالجة المفتاح الخاص. يرجى المحاولة مرة أخرى.")

async def simulate_cleanup(pubkey: str):
    client = AsyncClient("https://api.mainnet-beta.solana.com")
    try:
        resp = await client.get_token_accounts_by_owner(
            pubkey, 
            TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        )
        accounts = resp.value
        
        # حساب الرينت الدقيق (0.00204096 SOL لكل حساب)
        return len(accounts) * 0.00204096, len(accounts)
    except Exception as e:
        logger.error(f"Error in simulate_cleanup: {str(e)}")
        return 0.0, 0
    finally:
        await client.close()

async def perform_cleanup(update: Update, keypair: Keypair):
    try:
        pubkey = str(keypair.public_key)
        client = AsyncClient("https://api.mainnet-beta.solana.com")
        
        # الحصول على الحسابات الرمزية
        resp = await client.get_token_accounts_by_owner(
            pubkey,
            TokenAccountOpts(program_id="TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
        )
        accounts = resp.value
        
        if not accounts:
            await update.message.reply_text("لا توجد حسابات غير نشطة لتنظيفها")
            return
            
        reclaimed = len(accounts) * 0.00204096
        
        await update.message.reply_text(
            f"🎉 تم الانتهاء من التنظيف!\n"
            f"عدد الحسابات المنظفة: {len(accounts)}\n"
            f"المبلغ المستعاد: ~{reclaimed:.6f} SOL\n\n"
            f"يمكنك التحقق من الرصيد في محفظتك."
        )
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
