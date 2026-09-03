#!/usr/bin/env python3
"""
███████╗███████╗███████╗██████╗  ██████╗ ███████╗███████╗██╗ ██████╗ ███╗   ██╗ █████╗ ██╗
██╔════╝██╔════╝██╔════╝██╔══██╗██╔══██╗██╔════╝██╔════╝██║██╔═══██╗████╗  ██║██╔══██╗██║
███████╗█████╗  █████╗  ██████╔╝██████╔╝█████╗  ███████╗██║██║   ██║██╔██╗ ██║███████║██║
╚════██║██╔══╝  ██╔══╝  ██╔══██╗██╔══██╗██╔══╝  ╚════██║██║██║   ██║██║╚██╗██║██╔══██║██║
███████║███████╗██║     ██║  ██║██║  ██║███████╗███████║██║╚██████╔╝██║ ╚████║██║  ██║███████╗
╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝

Bot Version: 2.2.2 (Professional - Fixed)
Developer: Ahmed & DeepSeek
Purpose: Commercial Telegram Automation System

CHANGELOG v2.0.1 (FIXED):
  [FIX] تنظيف كل تشوهات النسخ/اللصق (أسماء المتغيرات والدوال)
  [FIX] follow_channel: target_bot_link = أول قناة بدل JSON كامل (منع كسر NOT NULL)
  [FIX] buy_number: أزرار الدول بفهرس آمن (منع تجاوز حد callback_data 64 بايت)
  [FIX] أمان التواريخ: slice آمن عند غياب created_at/added_at
  [FIX] 2FA: التقاط SessionPasswordNeededError بشكل صحيح
  [FIX] استبدال datetime.utcnow() بدالة aware (متوافق Python 3.12+)
  [FIX] إغلاق خادم aiohttp عند إيقاف البوت
  [FIX] buy_with_points: محاولة الاستماع لرمز التفعيل مثل الشراء العادي
"""

import asyncio
import logging
import os
import sys
import re
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Any, Optional, List

from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from dotenv import load_dotenv
from supabase import create_client, Client
from aiohttp import web
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.sessions import StringSession

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler('bot.log')]
)
logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """زمن UTC مدرك للمنطقة (بديل datetime.utcnow المهجور)"""
    return datetime.now(timezone.utc)


# ============================================
# CONFIGURATION
# ============================================
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME')
ADMIN_GROUP_ID = int(os.getenv('ADMIN_GROUP_ID', 0))
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
DEVELOPER_USERNAME = os.getenv('DEVELOPER_USERNAME')
CHANNEL_URL = os.getenv('CHANNEL_URL')
CHANNEL_ID = os.getenv('CHANNEL_ID')
BINANCE_PAY_ID = os.getenv('BINANCE_PAY_ID')
MIN_DEPOSIT_USD = Decimal(os.getenv('MIN_DEPOSIT_USD', '0.50'))
SESSION_DURATION = int(os.getenv('SESSION_DURATION_MINUTES', '15'))

if not BOT_TOKEN or BOT_TOKEN == "your_bot_token_here":
    logger.error("BOT_TOKEN is missing or invalid! Check .env file")
if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("SUPABASE_URL/KEY missing! Check .env file")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# FIXED v2.0.1: Admin IDs configurable via .env (ADMIN_IDS=123,456)
admin_ids_env = os.getenv('ADMIN_IDS', '')
if admin_ids_env.strip():
    try:
        ADMIN_IDS = [int(x.strip()) for x in admin_ids_env.split(',') if x.strip().isdigit()]
    except Exception:
        ADMIN_IDS = [8469650487]
else:
    ADMIN_IDS = [8469650487]

_admin_group_admin = os.getenv('ADMIN_ID', '')
if _admin_group_admin and _admin_group_admin.isdigit():
    _aid = int(_admin_group_admin)
    if _aid not in ADMIN_IDS:
        ADMIN_IDS.append(_aid)


# ============================================
# FSM STATES
# ============================================
class DepositStates(StatesGroup):
    waiting_for_txid = State()
    waiting_for_amount = State()
    waiting_for_sender_info = State()


class SupportStates(StatesGroup):
    waiting_for_message = State()


class AdminStates(StatesGroup):
    # Old states
    waiting_for_country = State()
    waiting_for_numbers = State()
    waiting_for_price = State()
    waiting_for_session_phone = State()
    waiting_for_session_code = State()
    waiting_for_session_2fa = State()
    waiting_for_proxy_host = State()
    waiting_for_proxy_port = State()
    waiting_for_proxy_username = State()
    waiting_for_proxy_password = State()
    waiting_for_channel = State()
    waiting_for_min_deposit = State()
    waiting_for_binance_id = State()
    waiting_for_session_duration = State()
    waiting_for_referral_points = State()
    waiting_for_delete_number = State()
    waiting_for_broadcast = State()
    waiting_for_edit_balance = State()
    waiting_for_edit_points = State()
    # New states for task automation
    waiting_for_task_bot_link = State()
    waiting_for_task_accounts_count = State()
    waiting_for_task_speed = State()
    waiting_for_task_group = State()
    waiting_for_composite_steps = State()
    waiting_for_channels_list = State()
    waiting_for_emoji = State()
    waiting_for_vote_option = State()
    waiting_for_message_link = State()
    waiting_for_proxy_data = State()
    waiting_for_group_name = State()
    waiting_for_group_type = State()
    waiting_for_learning_response = State()
    # v2.2.0: حالات الإضافة الدفعية والإيقاف المؤقت
    waiting_for_batch_phones = State()
    waiting_for_batch_codes = State()
    waiting_for_batch_2fa = State()
    waiting_for_pause_phone = State()
    waiting_for_resume_phone = State()


class BuyStates(StatesGroup):
    waiting_for_confirmation = State()


# ============================================
# DATABASE CLASS (COMPLETE)
# ============================================
class Database:

    @staticmethod
    async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
        try:
            response = supabase.table('users').select('*').eq('user_id', user_id).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error getting user {user_id}: {e}")
            return None

    @staticmethod
    async def create_or_update_user(user_data: Dict[str, Any]) -> bool:
        try:
            existing = await Database.get_user(user_data['user_id'])
            if existing:
                supabase.table('users').update(user_data).eq('user_id', user_data['user_id']).execute()
            else:
                supabase.table('users').insert(user_data).execute()
            return True
        except Exception as e:
            logger.error(f"Error upserting user: {e}")
            return False

    @staticmethod
    async def get_setting(key: str) -> Optional[str]:
        try:
            response = supabase.table('settings').select('*').eq('key', key).execute()
            return response.data[0].get('value') if response.data else None
        except Exception as e:
            logger.error(f"Error getting setting {key}: {e}")
            return None

    @staticmethod
    async def update_setting(key: str, value: str) -> bool:
        try:
            supabase.table('settings').upsert({
                'key': key, 'value': value,
                'updated_at': _utcnow().isoformat()
            }, on_conflict='key').execute()
            return True
        except Exception as e:
            logger.error(f"Error updating setting {key}: {e}")
            return False

    @staticmethod
    async def get_available_countries() -> List[str]:
        try:
            response = supabase.table('inventory').select('country').eq('is_sold', False).eq('status', 'available').execute()
            return sorted(list(set(item['country'] for item in response.data)))
        except Exception as e:
            logger.error(f"Error getting countries: {e}")
            return []

    @staticmethod
    async def get_available_numbers_by_country(country: str) -> List[Dict[str, Any]]:
        try:
            response = supabase.table('inventory').select('*').eq('country', country).eq('is_sold', False).eq('status', 'available').execute()
            return response.data
        except Exception as e:
            logger.error(f"Error getting numbers for {country}: {e}")
            return []

    @staticmethod
    async def purchase_number(number_id: str, buyer_id: int) -> Optional[Dict[str, Any]]:
        try:
            now = _utcnow()
            expires_at = now + timedelta(minutes=SESSION_DURATION)
            response = supabase.table('inventory').update({
                'is_sold': True, 'buyer_id': buyer_id, 'status': 'sold',
                'sold_at': now.isoformat(), 'session_expires_at': expires_at.isoformat()
            }).eq('id', number_id).eq('is_sold', False).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error purchasing number: {e}")
            return None

    @staticmethod
    async def get_user_transactions(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            response = supabase.table('transactions').select('*').eq('user_id', user_id).order('created_at', desc=True).limit(limit).execute()
            return response.data
        except Exception as e:
            logger.error(f"Error getting transactions: {e}")
            return []

    @staticmethod
    async def create_transaction(transaction_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            response = supabase.table('transactions').insert(transaction_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error creating transaction: {e}")
            return None

    @staticmethod
    async def add_referral_points(user_id: int, points: int) -> bool:
        try:
            user = await Database.get_user(user_id)
            if user:
                new_points = user.get('points', 0) + points
                supabase.table('users').update({'points': new_points}).eq('user_id', user_id).execute()
                return True
            return False
        except Exception as e:
            logger.error(f"Error adding referral points: {e}")
            return False

    @staticmethod
    async def get_mandatory_channels() -> List[str]:
        try:
            channels_str = await Database.get_setting('mandatory_channels')
            return json.loads(channels_str) if channels_str else []
        except Exception as e:
            logger.error(f"Error getting mandatory channels: {e}")
            return []

    # New database methods for task automation
    @staticmethod
    async def get_proxy_list() -> List[Dict[str, Any]]:
        try:
            response = supabase.table('proxy_list').select('*').order('added_at', desc=True).execute()
            return response.data
        except Exception as e:
            logger.error(f"Error getting proxy list: {e}")
            return []

    @staticmethod
    async def add_proxy(proxy_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            response = supabase.table('proxy_list').insert(proxy_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error adding proxy: {e}")
            return None

    @staticmethod
    async def delete_proxy(proxy_id: str) -> bool:
        try:
            supabase.table('proxy_list').delete().eq('id', proxy_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error deleting proxy: {e}")
            return False

    @staticmethod
    async def get_account_groups() -> List[Dict[str, Any]]:
        try:
            response = supabase.table('account_groups').select('*').order('created_at', desc=True).execute()
            return response.data
        except Exception as e:
            logger.error(f"Error getting account groups: {e}")
            return []

    @staticmethod
    async def create_account_group(group_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            response = supabase.table('account_groups').insert(group_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error creating group: {e}")
            return None

    @staticmethod
    async def get_bot_templates(bot_username: str = None) -> List[Dict[str, Any]]:
        try:
            query = supabase.table('bot_templates').select('*').order('success_count', desc=True)
            if bot_username:
                query = query.eq('bot_username', bot_username)
            response = query.execute()
            return response.data
        except Exception as e:
            logger.error(f"Error getting bot templates: {e}")
            return []

    @staticmethod
    async def save_bot_template(template_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            template_data['updated_at'] = _utcnow().isoformat()
            response = supabase.table('bot_templates').upsert(template_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error saving template: {e}")
            return None

    @staticmethod
    async def add_task_log(log_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            response = supabase.table('task_logs').insert(log_data).execute()
            return response.data[0] if response.data else None
        except Exception as e:
            logger.error(f"Error adding task log: {e}")
            return None

    @staticmethod
    async def check_completed_task(session_id: str, bot_username: str, parent_task_id: str = None) -> bool:
        try:
            q = supabase.table('completed_tasks_history').select('id').eq('session_id', session_id).eq('bot_username', bot_username)
            if parent_task_id:
                q = q.eq('parent_task_id', parent_task_id)
            response = q.execute()
            return len(response.data) > 0
        except Exception as e:
            logger.error(f"Error checking completed task: {e}")
            return False

    @staticmethod
    async def mark_task_completed(session_id: str, bot_username: str, task_type: str, parent_task_id: str = None) -> bool:
        try:
            data = {
                'session_id': session_id, 'bot_username': bot_username,
                'task_type': task_type, 'completed_at': _utcnow().isoformat()
            }
            if parent_task_id:
                data['parent_task_id'] = parent_task_id
            try:
                supabase.table('completed_tasks_history').insert(data).execute()
            except Exception:
                q = supabase.table('completed_tasks_history').update(data) \
                    .eq('session_id', session_id).eq('bot_username', bot_username)
                if parent_task_id:
                    q = q.eq('parent_task_id', parent_task_id)
                else:
                    q = q.is_('parent_task_id', 'null')
                q.execute()
            return True
        except Exception as e:
            logger.error(f"Error marking task completed: {e}")
            return False


# ============================================
# KEYBOARDS CLASS (COMPLETE)
# ============================================
class Keyboards:

    @staticmethod
    def main_menu() -> ReplyKeyboardMarkup:
        builder = ReplyKeyboardBuilder()
        builder.row(KeyboardButton(text="👤 معلومات حسابي"), KeyboardButton(text="💰 شحن الرصيد"))
        builder.row(KeyboardButton(text="🛒 شراء رقم"), KeyboardButton(text="🤝 بيع رقم"))
        builder.row(KeyboardButton(text="📢 قناة البوت"), KeyboardButton(text="🔗 نظام الإحالات"))
        builder.row(KeyboardButton(text="💬 مراسلة الدعم"), KeyboardButton(text="🎁 متجر النقاط"))
        builder.adjust(2)
        return builder.as_markup(resize_keyboard=True)

    @staticmethod
    def subscription_check() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ تحقق من الاشتراك", callback_data="verify_subscription")
        builder.button(text="📢 قناة البوت", url=CHANNEL_URL)
        builder.adjust(1)
        return builder.as_markup()

    @staticmethod
    def deposit_methods() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="💛 Binance Pay", callback_data="deposit_binance")
        builder.button(text="🇸🇾 شام كاش", callback_data="deposit_chamcash")
        builder.button(text="🔙 رجوع", callback_data="back_to_main")
        builder.adjust(1)
        return builder.as_markup()

    @staticmethod
    def admin_transaction_actions(transaction_id: str) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ موافقة", callback_data=f"approve_tx_{transaction_id}")
        builder.button(text="❌ رفض", callback_data=f"reject_tx_{transaction_id}")
        builder.adjust(2)
        return builder.as_markup()

    @staticmethod
    def session_controls(number_id: str) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="⏹ إنهاء الجلسة", callback_data=f"end_session_{number_id}")
        builder.button(text="🔄 لم أستلم الرمز", callback_data=f"no_code_{number_id}")
        builder.adjust(1)
        return builder.as_markup()

    @staticmethod
    def task_speed_selector() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="🐢 بطيء (آمن)", callback_data="speed_slow")
        builder.button(text="🐇 متوسط", callback_data="speed_medium")
        builder.button(text="🚀 سريع", callback_data="speed_fast")
        builder.button(text="🔙 رجوع", callback_data="admin_tasks")
        builder.adjust(1)
        return builder.as_markup()

    @staticmethod
    def task_type_selector() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="🧠 مهمة ذكية (تلقائي)", callback_data="task_smart")
        builder.button(text="✋ مهمة يدوية", callback_data="task_manual")
        builder.button(text="📢 متابعة قناة", callback_data="task_follow")
        builder.button(text="💬 تفاعل بمنشور", callback_data="task_react")
        builder.button(text="⭐ تصويت", callback_data="task_vote")
        builder.button(text="🔄 إعادة توجيه", callback_data="task_forward")
        builder.button(text="📋 المهام الحالية", callback_data="task_list")
        builder.button(text="📁 القوالب المحفوظة", callback_data="task_templates")
        builder.button(text="👥 مجموعات الحسابات", callback_data="task_groups")
        builder.button(text="🌐 البروكسيات", callback_data="task_proxies")
        builder.button(text="📊 تقارير", callback_data="task_reports")
        builder.button(text="🔙 رجوع", callback_data="admin_panel")
        builder.adjust(1)
        return builder.as_markup()

    @staticmethod
    def learning_response_buttons(options: List[str]) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        for option in options:
            builder.button(text=option, callback_data=f"learn_{option[:20]}")
        builder.button(text="📝 شرح يدوي", callback_data="learn_manual")
        builder.button(text="❌ تخطي", callback_data="learn_skip")
        builder.adjust(2)
        return builder.as_markup()

    @staticmethod
    def proxy_management_menu() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ إضافة بروكسي", callback_data="proxy_add")
        builder.button(text="📋 عرض البروكسيات", callback_data="proxy_list")
        builder.button(text="🗑 حذف بروكسي", callback_data="proxy_delete")
        builder.button(text="⚙️ إعدادات التوزيع", callback_data="proxy_settings")
        builder.button(text="🔙 رجوع", callback_data="admin_tasks")
        builder.adjust(1)
        return builder.as_markup()

    @staticmethod
    def groups_menu() -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ إنشاء مجموعة", callback_data="group_create")
        builder.button(text="📋 عرض المجموعات", callback_data="group_list")
        builder.button(text="➕ إضافة حسابات", callback_data="group_add_accounts")
        builder.button(text="🔙 رجوع", callback_data="admin_tasks")
        builder.adjust(1)
        return builder.as_markup()


# ============================================
# SUBSCRIPTION CHECK
# ============================================
async def check_user_subscription(user_id: int) -> bool:
    try:
        channels = await Database.get_mandatory_channels()
        if not channels:
            return True
        for channel in channels:
            try:
                member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
                if member.status in ['left', 'kicked', 'banned']:
                    return False
            except Exception:
                continue
        return True
    except Exception:
        return True


# ============================================
# START COMMAND
# ============================================
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        username = message.from_user.username or ""
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""

        args = message.text.split()
        referrer_id = None
        if len(args) > 1:
            try:
                referrer_id = int(args[1])
            except ValueError:
                pass

        user_data = {
            'user_id': user_id, 'username': username,
            'first_name': first_name, 'last_name': last_name,
            'joined_at': _utcnow().isoformat()
        }
        if referrer_id and referrer_id != user_id:
            user_data['referrer_id'] = referrer_id

        await Database.create_or_update_user(user_data)

        if referrer_id and referrer_id != user_id:
            referrer = await Database.get_user(referrer_id)
            if referrer:
                await Database.add_referral_points(referrer_id, 1)
                supabase.table('users').update({
                    'total_referrals': referrer.get('total_referrals', 0) + 1
                }).eq('user_id', referrer_id).execute()

        is_subscribed = await check_user_subscription(user_id)

        if not is_subscribed:
            await message.answer(
                "👋 *أهلاً بك في بوت شراء وبيع الأرقام!*\n\n"
                "⚠️ *يجب الاشتراك في القناة أولاً لاستخدام البوت*\n\n"
                "اشترك في القناة ثم اضغط على زر التحقق",
                reply_markup=Keyboards.subscription_check(), parse_mode="Markdown"
            )
        else:
            await message.answer(
                "👋 *أهلاً بك!*\n\nتم التحقق من اشتراكك بنجاح ✅\nيمكنك استخدام البوت الآن",
                reply_markup=Keyboards.main_menu(), parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}")
        await message.answer("❌ حدث خطأ، يرجى المحاولة مرة أخرى")


@router.callback_query(F.data == "verify_subscription")
async def verify_subscription(callback: CallbackQuery):
    try:
        if await check_user_subscription(callback.from_user.id):
            await callback.message.edit_text("✅ *تم التحقق من الاشتراك بنجاح!*\n\nيمكنك الآن استخدام جميع خدمات البوت", parse_mode="Markdown")
            await callback.message.answer("القائمة الرئيسية:", reply_markup=Keyboards.main_menu())
        else:
            await callback.answer("❌ لم يتم التحقق من الاشتراك، يرجى الاشتراك أولاً", show_alert=True)
    except Exception as e:
        logger.error(f"Error in verify_subscription: {e}")
        await callback.answer("❌ حدث خطأ، يرجى المحاولة مرة أخرى")


# ============================================
# USER PROFILE
# ============================================
@router.message(F.text == "👤 معلومات حسابي")
async def my_profile(message: Message):
    try:
        user = await Database.get_user(message.from_user.id)
        if not user:
            await message.answer("❌ لم يتم العثور على حسابك، يرجى استخدام /start")
            return
        profile_text = (
            "👤 *معلومات حسابي*\n\n"
            f"🆔 *معرف المستخدم:* `{user['user_id']}`\n"
            f"👤 *اسم المستخدم:* @{user.get('username', 'غير محدد')}\n"
            f"💰 *الرصيد المالي:* ${user.get('balance', 0):.2f}\n"
            f"🎁 *نقاط الإحالات:* {user.get('points', 0)} نقطة\n"
            f"👥 *عدد الإحالات:* {user.get('total_referrals', 0)}\n"
            f"📅 *تاريخ الانضمام:* {user.get('joined_at', 'غير محدد')}\n"
        )
        await message.answer(profile_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in my_profile: {e}")
        await message.answer("❌ حدث خطأ في عرض المعلومات")


# ============================================
# DEPOSIT HANDLERS
# ============================================
@router.message(F.text == "💰 شحن الرصيد")
async def deposit_balance(message: Message):
    try:
        await message.answer(
            "💰 *شحن الرصيد*\n\nاختر طريقة الشحن المناسبة:\n\n"
            f"💛 *Binance Pay:* الحد الأدنى ${MIN_DEPOSIT_USD}\n"
            f"🇸🇾 *شام كاش:* متاح للمستخدمين في سوريا\n\n"
            "يرجى اختيار طريقة الدفع:",
            reply_markup=Keyboards.deposit_methods(), parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in deposit_balance: {e}")
        await message.answer("❌ حدث خطأ")


@router.callback_query(F.data == "deposit_binance")
async def deposit_binance(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text(
            "💛 *الدفع عبر Binance Pay*\n\n"
            f"🆔 *Pay ID:* `{BINANCE_PAY_ID}`\n"
            f"💰 *الحد الأدنى:* ${MIN_DEPOSIT_USD}\n\n"
            "📝 *الخطوات:*\n"
            "1. افتح تطبيق Binance\n2. اذهب إلى Pay\n"
            "3. أرسل المبلغ إلى Pay ID أعلاه\n"
            "4. انسخ Transaction ID (TXID)\n5. أرسل TXID هنا\n\n"
            "🔹 *أرسل TXID الآن:*",
            parse_mode="Markdown"
        )
        await state.set_state(DepositStates.waiting_for_txid)
    except Exception as e:
        logger.error(f"Error in deposit_binance: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(DepositStates.waiting_for_txid))
async def process_binance_txid(message: Message, state: FSMContext):
    try:
        txid = message.text.strip()
        if not txid or len(txid) < 10:
            await message.answer("❌ TXID غير صالح، يرجى إرسال معرف معاملة صحيح")
            return

        transaction = await Database.create_transaction({
            'user_id': message.from_user.id, 'method': 'binance',
            'amount': 0, 'tx_id': txid, 'status': 'pending'
        })
        if not transaction:
            await message.answer("❌ فشل في إنشاء طلب الدفع، يرجى المحاولة لاحقاً")
            await state.clear()
            return

        admin_text = (
            "🔔 *طلب شحن جديد - Binance Pay*\n\n"
            f"👤 *المستخدم:* {message.from_user.full_name}\n"
            f"🆔 *ID:* `{message.from_user.id}`\n"
            f"💱 *TXID:* `{txid}`\n"
            f"📅 *التاريخ:* {_utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "يرجى التحقق من المعاملة واتخاذ الإجراء المناسب"
        )
        await bot.send_message(ADMIN_GROUP_ID, admin_text,
                               reply_markup=Keyboards.admin_transaction_actions(transaction['id']),
                               parse_mode="Markdown")
        await message.answer("✅ *تم استلام طلبك بنجاح!*\n\nسيتم مراجعة طلبك من قبل الإدارة قريباً.\nستتلقى إشعاراً عند الموافقة على الشحن.", parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing binance txid: {e}")
        await message.answer("❌ حدث خطأ في معالجة الطلب")
        await state.clear()


@router.callback_query(F.data == "deposit_chamcash")
async def deposit_chamcash(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_text(
            "🇸🇾 *الدفع عبر شام كاش*\n\n"
            "📝 *الخطوات:*\n1. قم بإرسال المبلغ عبر شام كاش\n2. احفظ رقم العملية\n\n"
            "🔹 *أرسل المبلغ الذي قمت بتحويله:*",
            parse_mode="Markdown"
        )
        await state.set_state(DepositStates.waiting_for_amount)
    except Exception as e:
        logger.error(f"Error in deposit_chamcash: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(DepositStates.waiting_for_amount))
async def process_chamcash_amount(message: Message, state: FSMContext):
    try:
        amount_str = message.text.strip()
        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except Exception:
            await message.answer("❌ يرجى إدخال مبلغ صحيح (أرقام فقط)")
            return

        await state.update_data(amount=float(amount))
        await message.answer("📝 *أرسل اسم المرسل ورقم العملية:*\n\nمثال: `أحمد محمد - 123456789`", parse_mode="Markdown")
        await state.set_state(DepositStates.waiting_for_sender_info)
    except Exception as e:
        logger.error(f"Error processing chamcash amount: {e}")
        await message.answer("❌ حدث خطأ")


@router.message(StateFilter(DepositStates.waiting_for_sender_info))
async def process_chamcash_sender(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        amount = data.get('amount', 0)
        sender_info = message.text.strip()

        transaction = await Database.create_transaction({
            'user_id': message.from_user.id, 'method': 'cham_cash',
            'amount': amount, 'tx_id': sender_info, 'status': 'pending'
        })
        if not transaction:
            await message.answer("❌ فشل في إنشاء طلب الدفع")
            await state.clear()
            return

        admin_text = (
            "🔔 *طلب شحن جديد - شام كاش*\n\n"
            f"👤 *المستخدم:* {message.from_user.full_name}\n"
            f"🆔 *ID:* `{message.from_user.id}`\n"
            f"💰 *المبلغ:* {amount}\n"
            f"📝 *معلومات المرسل:* {sender_info}\n"
            f"📅 *التاريخ:* {_utcnow().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "يرجى التحقق من المعاملة واتخاذ الإجراء المناسب"
        )
        await bot.send_message(ADMIN_GROUP_ID, admin_text,
                               reply_markup=Keyboards.admin_transaction_actions(transaction['id']),
                               parse_mode="Markdown")
        await message.answer("✅ *تم استلام طلبك بنجاح!*\n\nسيتم مراجعة طلبك من قبل الإدارة قريباً.", parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing chamcash sender info: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


# ============================================
# TRANSACTION APPROVAL/REJECTION
# ============================================
@router.message(Command("set_amount"))
async def set_transaction_amount(message: Message):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ غير مصرح لك")
            return
        parts = message.text.split()
        if len(parts) < 3:
            await message.answer("❌ استخدم: `/set_amount tx_id المبلغ`")
            return
        tx_id = parts[1]
        try:
            amount = float(parts[2])
        except Exception:
            await message.answer("❌ مبلغ غير صالح")
            return

        response = supabase.table('transactions').select('*').eq('id', tx_id).execute()
        if not response.data:
            await message.answer("❌ المعاملة غير موجودة")
            return
        tx = response.data[0]
        user_id = tx['user_id']
        supabase.table('transactions').update({'amount': amount}).eq('id', tx_id).execute()
        user = await Database.get_user(user_id)
        if user:
            new_balance = Decimal(str(user.get('balance', 0))) + Decimal(str(amount))
            supabase.table('users').update({'balance': float(new_balance)}).eq('user_id', user_id).execute()
            await bot.send_message(user_id, f"✅ *تمت الموافقة على الشحن!*\n\n💰 *المبلغ:* ${amount:.2f}\n💳 *رصيدك الحالي:* ${new_balance:.2f}", parse_mode="Markdown")
        await message.answer(f"✅ تم تحديد المبلغ: ${amount:.2f}")
    except Exception as e:
        logger.error(f"Error setting amount: {e}")
        await message.answer("❌ حدث خطأ")


@router.callback_query(F.data.startswith("reject_tx_"))
async def reject_transaction(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        tx_id = callback.data.replace("reject_tx_", "")
        response = supabase.table('transactions').select('*').eq('id', tx_id).execute()
        if not response.data:
            await callback.answer("❌ المعاملة غير موجودة", show_alert=True)
            return
        transaction = response.data[0]
        user_id = transaction['user_id']
        supabase.table('transactions').update({
            'status': 'rejected', 'admin_id': callback.from_user.id,
            'processed_at': _utcnow().isoformat()
        }).eq('id', tx_id).execute()
        await bot.send_message(user_id, "❌ *عذراً، تم رفض طلب الشحن*\n\nيرجى التحقق من المعلومات المرسلة والمحاولة مرة أخرى.\nللتواصل مع الدعم: @myusrrname", parse_mode="Markdown")
        await callback.message.edit_text(callback.message.text + "\n\n❌ *تم رفض المعاملة*", parse_mode="Markdown")
        await callback.answer("❌ تم الرفض")
    except Exception as e:
        logger.error(f"Error rejecting transaction: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data.startswith("approve_tx_"))
async def approve_transaction(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        tx_id = callback.data.replace("approve_tx_", "")
        response = supabase.table('transactions').select('*').eq('id', tx_id).execute()
        if not response.data:
            await callback.answer("❌ المعاملة غير موجودة", show_alert=True)
            return
        transaction = response.data[0]
        user_id = transaction['user_id']
        amount = float(transaction['amount'])
        supabase.table('transactions').update({
            'status': 'approved', 'admin_id': callback.from_user.id,
            'processed_at': _utcnow().isoformat()
        }).eq('id', tx_id).execute()

        if amount <= 0:
            await callback.message.edit_text(callback.message.text + f"\n\n⚠️ *المبلغ غير محدد!*\nاستخدم: `/set_amount {tx_id} المبلغ`", parse_mode="Markdown")
            await callback.answer("⚠️ استخدم /set_amount لتحديد المبلغ", show_alert=True)
            return

        user = await Database.get_user(user_id)
        if user:
            new_balance = Decimal(str(user.get('balance', 0))) + Decimal(str(amount))
            supabase.table('users').update({'balance': float(new_balance)}).eq('user_id', user_id).execute()
            await bot.send_message(user_id, f"✅ *تمت الموافقة على الشحن!*\n\n💰 *المبلغ:* ${amount:.2f}\n💳 *رصيدك الحالي:* ${new_balance:.2f}", parse_mode="Markdown")
        await callback.message.edit_text(callback.message.text + "\n\n✅ *تمت الموافقة على المعاملة*", parse_mode="Markdown")
        await callback.answer("✅ تمت الموافقة بنجاح")
    except Exception as e:
        logger.error(f"Error approving transaction: {e}")
        await callback.answer("❌ حدث خطأ", show_alert=True)


# ============================================
# BUY NUMBER HANDLERS
# ============================================
@router.message(F.text == "🛒 شراء رقم")
async def buy_number(message: Message, state: FSMContext):
    try:
        countries = await Database.get_available_countries()
        if not countries:
            await message.answer("😔 *عذراً، لا تتوفر أرقام حالياً*\n\nيرجى المحاولة لاحقاً", parse_mode="Markdown")
            return

        # FIXED v2.0.1: استخدام فهرس آمن بدل اسم الدولة (حد 64 بايت للـ callback)
        await state.update_data(country_list=countries)
        builder = InlineKeyboardBuilder()
        for i, country in enumerate(countries):
            builder.button(text=f"📍 {country}", callback_data=f"buy_country_{i}")
        builder.button(text="🔙 رجوع", callback_data="back_to_main")
        builder.adjust(2)
        await message.answer("🛒 *شراء رقم جديد*\n\nاختر الدولة المطلوبة:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in buy_number: {e}")
        await message.answer("❌ حدث خطأ")


@router.callback_query(F.data.startswith("buy_country_"))
async def select_country_numbers(callback: CallbackQuery, state: FSMContext):
    try:
        try:
            idx = int(callback.data.replace("buy_country_", ""))
        except ValueError:
            await callback.answer("❌ بيانات غير صالحة", show_alert=True)
            return
        data = await state.get_data()
        countries = data.get('country_list', [])
        if idx < 0 or idx >= len(countries):
            await callback.answer("❌ الدولة غير موجودة", show_alert=True)
            return
        country = countries[idx]

        numbers = await Database.get_available_numbers_by_country(country)
        if not numbers:
            await callback.answer(f"❌ لا توجد أرقام متاحة في {country}", show_alert=True)
            return

        builder = InlineKeyboardBuilder()
        for number in numbers:
            price = number['price']
            phone = number['phone_number']
            builder.button(text=f"📱 {phone} - ${price:.2f}", callback_data=f"confirm_buy_{number['id']}")
        builder.button(text="🔙 رجوع", callback_data="buy_number")
        builder.adjust(1)
        await callback.message.edit_text(f"📍 *الأرقام المتاحة في {country}:*\n\nاختر الرقم الذي تريد شراءه:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error selecting country numbers: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data.startswith("confirm_buy_"))
async def confirm_purchase(callback: CallbackQuery, state: FSMContext):
    try:
        number_id = callback.data.replace("confirm_buy_", "")
        response = supabase.table('inventory').select('*').eq('id', number_id).execute()
        if not response.data:
            await callback.answer("❌ الرقم غير متوفر", show_alert=True)
            return
        number = response.data[0]
        user = await Database.get_user(callback.from_user.id)
        if not user:
            await callback.answer("❌ يرجى بدء البوت أولاً /start", show_alert=True)
            return

        user_balance = Decimal(str(user.get('balance', 0)))
        number_price = Decimal(str(number['price']))
        if user_balance < number_price:
            await callback.answer(f"❌ رصيدك غير كافي\nالرصيد: ${user_balance:.2f}\nالسعر: ${number_price:.2f}", show_alert=True)
            return

        await state.update_data(purchase_number_id=number_id, purchase_price=float(number_price))
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ تأكيد الشراء", callback_data="execute_purchase")
        builder.button(text="❌ إلغاء", callback_data="buy_number")
        builder.adjust(1)
        await callback.message.edit_text(
            "🛒 *تأكيد عملية الشراء*\n\n"
            f"📱 *الرقم:* {number['phone_number']}\n"
            f"📍 *الدولة:* {number['country']}\n"
            f"💰 *السعر:* ${number_price:.2f}\n\n"
            f"💳 *رصيدك الحالي:* ${user_balance:.2f}\n"
            f"💳 *الرصيد بعد الشراء:* ${user_balance - number_price:.2f}\n\n"
            "هل تريد تأكيد عملية الشراء؟",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error confirming purchase: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "execute_purchase")
async def execute_purchase(callback: CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()
        number_id = data.get('purchase_number_id')
        price = Decimal(str(data.get('purchase_price', 0)))
        if not number_id:
            await callback.answer("❌ بيانات الشراء غير متوفرة", show_alert=True)
            return

        user_id = callback.from_user.id
        user = await Database.get_user(user_id)
        if not user:
            await callback.answer("❌ خطأ في بيانات المستخدم", show_alert=True)
            return
        if Decimal(str(user.get('balance', 0))) < price:
            await callback.answer("❌ رصيد غير كافي", show_alert=True)
            return

        # جلب session_string من المخزون (مع fallback إلى client_sessions)
        session_string = None
        try:
            inv = supabase.table('inventory').select('session_string').eq('id', number_id).execute()
            session_string = inv.data[0].get('session_string') if inv.data and inv.data[0] else None
        except Exception as e:
            logger.warning(f"Could not fetch session_string from inventory: {e}")
            session_string = None

        if not session_string:
            try:
                inv_phone = supabase.table('inventory').select('phone_number').eq('id', number_id).execute()
                if inv_phone.data:
                    phone = inv_phone.data[0].get('phone_number')
                    sess = supabase.table('client_sessions').select('session_string').eq('phone', phone).eq('is_active', True).limit(1).execute()
                    if sess.data:
                        session_string = sess.data[0].get('session_string')
                        logger.info(f"Found session_string via client_sessions for {phone}")
            except Exception as e:
                logger.debug(f"Fallback session lookup failed: {e}")

        purchased_number = await Database.purchase_number(number_id, user_id)
        if not purchased_number:
            await callback.answer("❌ فشلت عملية الشراء", show_alert=True)
            return

        new_balance = Decimal(str(user.get('balance', 0))) - price
        supabase.table('users').update({'balance': float(new_balance)}).eq('user_id', user_id).execute()

        if user.get('referrer_id'):
            referrer_purchases = supabase.table('inventory').select('id').eq('buyer_id', user_id).execute()
            if len(referrer_purchases.data) <= 1:
                referral_points = int(await Database.get_setting('referral_points_reward') or 10)
                await Database.add_referral_points(user['referrer_id'], referral_points)
                await bot.send_message(user['referrer_id'], f"🎁 *مبروك!*\n\nقام أحد المدعوين من قبلك بإتمام أول عملية شراء.\nتمت إضافة {referral_points} نقاط إلى رصيدك!", parse_mode="Markdown")

        if session_string:
            asyncio.create_task(listen_for_code(session_string, user_id, number_id))

        await callback.message.edit_text(
            "✅ *تمت عملية الشراء بنجاح!*\n\n"
            f"📱 *الرقم:* {purchased_number['phone_number']}\n"
            f"📍 *الدولة:* {purchased_number['country']}\n"
            f"💰 *السعر:* ${price:.2f}\n\n"
            "⏰ *مدة الجلسة:* 15 دقيقة\n\n"
            "🔄 *جاري انتظار رمز التفعيل...*\nسيصلك الرمز تلقائياً 📨",
            reply_markup=Keyboards.session_controls(number_id), parse_mode="Markdown"
        )
        asyncio.create_task(schedule_session_expiry(number_id, user_id))
        await state.clear()
    except Exception as e:
        logger.error(f"Error executing purchase: {e}")
        await callback.answer("❌ حدث خطأ أثناء الشراء")


async def listen_for_code(session_string: str, buyer_id: int, number_id: str):
    try:
        api_id = int(os.getenv('API_ID', 0))
        api_hash = os.getenv('API_HASH', '')
        if not api_id or not api_hash:
            logger.error("API credentials not configured for code listening")
            return

        client = TelegramClient(StringSession(session_string), api_id, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            logger.error(f"Session not authorized for number_id: {number_id}")
            await bot.send_message(buyer_id, "⚠️ تعذر الاتصال بالحساب لاستقبال الرمز. يرجى التواصل مع الدعم.")
            return

        logger.info(f"Listening for code on number_id: {number_id} for buyer {buyer_id}")
        code_received = False

        @client.on(events.NewMessage(incoming=True))
        async def handler(event):
            nonlocal code_received
            if code_received:
                return
            message_text = event.message.message or ""
            code_match = re.search(r'\b(\d{5,6})\b', message_text)
            if code_match:
                code = code_match.group(1)
                code_received = True
                await bot.send_message(buyer_id, f"📨 *تم استلام رمز التفعيل!*\n\n🔢 *الرمز:* `{code}`\n\n⏰ يرجى استخدامه قبل انتهاء الجلسة.", parse_mode="Markdown")
                supabase.table('inventory').update({'activation_code': code}).eq('id', number_id).execute()
                logger.info(f"Code {code} sent to buyer {buyer_id}")
                await asyncio.sleep(30)
                await client.disconnect()

        # إبقاء الجلسة 10 دقائق لاستقبال الرمز
        await asyncio.sleep(600)
        if not code_received:
            await bot.send_message(buyer_id, "⚠️ لم يتم استلام أي رمز تفعيل خلال 10 دقائق. يرجى التواصل مع الدعم.")
        await client.disconnect()
    except Exception as e:
        logger.error(f"Error listening for code: {e}")
        try:
            await bot.send_message(buyer_id, "⚠️ حدث خطأ في استقبال الرمز. يرجى التواصل مع الدعم.")
        except Exception:
            pass


async def schedule_session_expiry(number_id: str, user_id: int):
    try:
        await asyncio.sleep(SESSION_DURATION * 60)
        response = supabase.table('inventory').select('*').eq('id', number_id).execute()
        if response.data:
            number = response.data[0]
            if number['status'] == 'sold' and number['session_expires_at']:
                expires_at = datetime.fromisoformat(number['session_expires_at'].replace('Z', '+00:00'))
                if _utcnow() >= expires_at:
                    supabase.table('inventory').update({'status': 'expired', 'session_expires_at': None}).eq('id', number_id).execute()
                    await bot.send_message(user_id, f"⏰ *انتهت الجلسة*\n\nانتهت مدة الجلسة ({SESSION_DURATION} دقيقة) للرقم.\nشكراً لاستخدامك خدماتنا!", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in session expiry: {e}")


@router.callback_query(F.data.startswith("end_session_"))
async def end_session(callback: CallbackQuery):
    try:
        number_id = callback.data.replace("end_session_", "")
        supabase.table('inventory').update({'status': 'expired', 'session_expires_at': None}).eq('id', number_id).execute()
        await callback.message.edit_text("⏹ *تم إنهاء الجلسة*\n\nتم إنهاء جلستك بنجاح.", parse_mode="Markdown")
        await callback.answer("✅ تم إنهاء الجلسة")
    except Exception as e:
        logger.error(f"Error ending session: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data.startswith("no_code_"))
async def no_code_received(callback: CallbackQuery):
    try:
        number_id = callback.data.replace("no_code_", "")
        response = supabase.table('inventory').select('*').eq('id', number_id).execute()
        if not response.data:
            await callback.answer("❌ الرقم غير موجود", show_alert=True)
            return
        number = response.data[0]
        admin_text = (
            "⚠️ *مشكلة في استلام الرمز*\n\n"
            f"👤 *المستخدم:* {callback.from_user.full_name}\n"
            f"🆔 *ID:* `{callback.from_user.id}`\n"
            f"📱 *الرقم:* {number['phone_number']}\n"
            f"📍 *الدولة:* {number['country']}\n\n"
            "يرجى التحقق من المشكلة ومساعدة المستخدم"
        )
        await bot.send_message(ADMIN_GROUP_ID, admin_text, parse_mode="Markdown")
        await callback.answer("✅ تم إبلاغ الدعم، سنتواصل معك قريباً", show_alert=True)
    except Exception as e:
        logger.error(f"Error in no_code_received: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(F.text == "🤝 بيع رقم")
async def sell_number(message: Message):
    try:
        sell_text = (
            "🤝 *بيع رقمك للبوت*\n\n"
            "📋 *الشروط والأحكام:*\n\n"
            "1️⃣ *حالة الحساب:* يجب أن يكون الحساب نظيفاً وغير مقيد\n"
            "2️⃣ *نوع الحساب:* حسابات نظيفة فقط (غير مزعجة spam)\n"
            "3️⃣ *الدولة:* يجب تحديد دولة الرقم\n"
            "4️⃣ *تاريخ التفعيل:* يفضل أن يكون الحساب مفعلاً منذ فترة\n"
            "5️⃣ *البوتات النشطة:* يفضل عدم وجود بوتات نشطة كثيرة\n\n"
            "📞 *للتواصل مع المطور:*\n"
            f"👤 {DEVELOPER_USERNAME}\n\n"
            "💡 *ملاحظة:* يتم تقييم كل حساب بشكل فردي وتحديد السعر بناءً على الجودة والمواصفات."
        )
        builder = InlineKeyboardBuilder()
        builder.button(text=f"📞 تواصل مع {DEVELOPER_USERNAME}", url=f"https://t.me/{DEVELOPER_USERNAME}")
        builder.adjust(1)
        await message.answer(sell_text, reply_markup=builder.as_markup(), parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error in sell_number: {e}")
        await message.answer("❌ حدث خطأ")


@router.message(F.text == "📢 قناة البوت")
async def bot_channel(message: Message):
    try:
        builder = InlineKeyboardBuilder()
        builder.button(text="📢 قناة البوت", url=CHANNEL_URL)
        builder.adjust(1)
        await message.answer("📢 *قناة البوت الرسمية*\n\nتابع قناتنا للاطلاع على:\n🔹 آخر التحديثات\n🔹 العروض الخاصة\n🔹 الأرقام الجديدة\n🔹 نصائح وإرشادات\n\nاضغط على الزر أدناه للانضمام:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in bot_channel: {e}")
        await message.answer("❌ حدث خطأ")


@router.message(F.text == "🔗 نظام الإحالات")
async def referral_system(message: Message):
    try:
        user_id = message.from_user.id
        user = await Database.get_user(user_id)
        if not user:
            await message.answer("❌ يرجى استخدام /start أولاً")
            return

        referral_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        referral_points = int(await Database.get_setting('referral_points_reward') or 10)
        ref_text = (
            "🔗 *نظام الإحالات*\n\n"
            "🎁 *اربح نقاطاً مجانية عن طريق دعوة أصدقائك!*\n\n"
            "📋 *طريقة العمل:*\n"
            "1️⃣ انسخ رابط الإحالة الخاص بك\n2️⃣ شاركه مع أصدقائك\n"
            "3️⃣ عندما يسجل صديقك ويقوم بأول عملية شراء، تربح نقاطاً!\n\n"
            f"🔗 *رابط الإحالة الخاص بك:* `{referral_link}`\n\n"
            f"👥 *عدد المدعوين:* {user.get('total_referrals', 0)}\n"
            f"🎁 *رصيد النقاط:* {user.get('points', 0)} نقطة\n"
            f"💰 *قيمة النقاط:* كل {referral_points} نقاط = عملية شراء مجانية\n\n"
            "📌 *ملاحظة:* تحتسب النقاط فقط عند إتمام المدعو لعملية شراء."
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="📤 مشاركة الرابط", switch_inline_query=f"start={user_id}")
        builder.adjust(1)
        await message.answer(ref_text, reply_markup=builder.as_markup(), parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error in referral_system: {e}")
        await message.answer("❌ حدث خطأ")


@router.message(F.text == "💬 مراسلة الدعم")
async def support_message(message: Message, state: FSMContext):
    try:
        await message.answer("💬 *مراسلة الدعم*\n\nيمكنك إرسال رسالتك مباشرة إلى فريق الدعم.\nاكتب رسالتك الآن وسيتم تحويلها إلى فريق الدعم.", parse_mode="Markdown")
        await state.set_state(SupportStates.waiting_for_message)
    except Exception as e:
        logger.error(f"Error in support_message: {e}")
        await message.answer("❌ حدث خطأ")


@router.message(StateFilter(SupportStates.waiting_for_message))
async def forward_support_message(message: Message, state: FSMContext):
    try:
        support_msg = (
            "📩 *رسالة دعم جديدة*\n\n"
            f"👤 *من:* {message.from_user.full_name}\n"
            f"🆔 *ID:* `{message.from_user.id}`\n"
            f"👤 *Username:* @{message.from_user.username}\n\n"
            f"📝 *الرسالة:*\n{message.text}"
        )
        try:
            await message.forward(ADMIN_GROUP_ID)
        except Exception:
            pass
        await bot.send_message(ADMIN_GROUP_ID, support_msg, parse_mode="Markdown")
        await message.answer("✅ *تم إرسال رسالتك بنجاح!*\n\nسيتواصل معك فريق الدعم قريباً.", parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error forwarding support message: {e}")
        await message.answer("❌ حدث خطأ في إرسال الرسالة")
        await state.clear()


@router.message(F.text == "🎁 متجر النقاط")
async def points_store(message: Message):
    try:
        response = supabase.table('inventory').select('*').eq('is_sold', False).eq('status', 'available').gt('points_price', 0).execute()
        if not response.data:
            await message.answer("😔 *لا تتوفر منتجات في متجر النقاط حالياً*\n\nاجمع المزيد من النقاط عن طريق نظام الإحالات!", parse_mode="Markdown")
            return

        builder = InlineKeyboardBuilder()
        for item in response.data:
            builder.button(text=f"📍 {item['country']} - {item['points_price']} نقطة", callback_data=f"points_buy_{item['id']}")
        builder.button(text="🔙 رجوع", callback_data="back_to_main")
        builder.adjust(1)

        user = await Database.get_user(message.from_user.id)
        points = user.get('points', 0) if user else 0
        await message.answer(f"🎁 *متجر النقاط*\n\nاستخدم نقاط الإحالات لشراء أرقام مجانية!\n\n🎁 *رصيد نقاطك:* {points} نقطة\n\nاختر المنتج الذي تريد شراءه:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in points_store: {e}")
        await message.answer("❌ حدث خطأ")


@router.callback_query(F.data.startswith("points_buy_"))
async def buy_with_points(callback: CallbackQuery):
    try:
        number_id = callback.data.replace("points_buy_", "")
        response = supabase.table('inventory').select('*').eq('id', number_id).execute()
        if not response.data:
            await callback.answer("❌ المنتج غير متوفر", show_alert=True)
            return
        number = response.data[0]
        user = await Database.get_user(callback.from_user.id)
        if not user:
            await callback.answer("❌ يرجى استخدام /start أولاً", show_alert=True)
            return

        user_points = user.get('points', 0)
        required_points = number['points_price']
        if user_points < required_points:
            await callback.answer(f"❌ نقاطك غير كافية\nلديك: {user_points}\nالمطلوب: {required_points}", show_alert=True)
            return

        purchased = await Database.purchase_number(number_id, callback.from_user.id)
        if not purchased:
            await callback.answer("❌ فشلت عملية الشراء", show_alert=True)
            return

        supabase.table('users').update({'points': user_points - required_points}).eq('user_id', callback.from_user.id).execute()

        # FIXED v2.0.1: محاولة الاستماع لرمز التفعيل مثل الشراء العادي
        try:
            inv = supabase.table('inventory').select('session_string').eq('id', number_id).execute()
            session_string = inv.data[0].get('session_string') if inv.data and inv.data[0] else None
            if session_string:
                asyncio.create_task(listen_for_code(session_string, callback.from_user.id, number_id))
        except Exception:
            pass

        await callback.message.edit_text(f"✅ *تمت عملية الشراء بنجاح!*\n\n📱 *الرقم:* {purchased['phone_number']}\n📍 *الدولة:* {purchased['country']}\n🎁 *النقاط المستخدمة:* {required_points}\n\n⏰ *مدة الجلسة:* 15 دقيقة", reply_markup=Keyboards.session_controls(number_id), parse_mode="Markdown")
        asyncio.create_task(schedule_session_expiry(number_id, callback.from_user.id))
    except Exception as e:
        logger.error(f"Error buying with points: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    try:
        await callback.message.delete()
        await callback.message.answer("القائمة الرئيسية:", reply_markup=Keyboards.main_menu())
    except Exception:
        await callback.answer("القائمة الرئيسية")


@router.callback_query(F.data == "buy_number")
async def back_to_countries(callback: CallbackQuery, state: FSMContext):
    try:
        await callback.message.delete()
        await buy_number(callback.message, state)
    except Exception as e:
        logger.error(f"Error in back_to_countries: {e}")


# ============================================
# ADMIN PANEL - MAIN
# ============================================
@router.message(Command("admin"))
async def admin_panel(message: Message):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ غير مصرح لك بالوصول إلى لوحة التحكم")
            return
        builder = InlineKeyboardBuilder()
        builder.button(text="📦 إدارة المخزون", callback_data="admin_inventory")
        builder.button(text="🔐 إدارة الجلسات", callback_data="admin_sessions")
        builder.button(text="🤖 المهام الآلية", callback_data="admin_tasks")
        builder.button(text="🌐 البروكسيات", callback_data="task_proxies")
        builder.button(text="📊 إحصائيات", callback_data="admin_stats")
        builder.button(text="⚙️ إعدادات", callback_data="admin_settings")
        builder.adjust(2)
        await message.answer("👑 *لوحة التحكم الإدارية*\n\nاختر القسم المطلوب:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_panel: {e}")


# ============================================
# INVENTORY MANAGEMENT
# ============================================
@router.callback_query(F.data == "admin_inventory")
async def admin_inventory_menu(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ إضافة رقم واحد", callback_data="admin_add_single")
        builder.button(text="📋 إضافة أرقام بالجملة", callback_data="admin_add_bulk")
        builder.button(text="👁 عرض المخزون", callback_data="admin_view_inventory")
        builder.button(text="🗑 حذف رقم", callback_data="admin_delete_number")
        builder.button(text="🔙 رجوع", callback_data="admin_panel")
        builder.adjust(1)
        await callback.message.edit_text("📦 *إدارة المخزون*\n\nاختر العملية:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_inventory_menu: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_add_single")
async def admin_add_single_number(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "📱 *إضافة رقم واحد*\n\nأرسل الرقم بالصيغة التالية:\n"
            "`الدولة | رقم_الهاتف | السعر`\n\n"
            "مثال:\n`سوريا | +963123456789 | 5.00`\n\n"
            "أو أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_numbers)
    except Exception as e:
        logger.error(f"Error in admin_add_single: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_numbers))
async def process_admin_add_number(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        numbers_text = message.text.strip()
        numbers_list = numbers_text.split('\n')
        added_count = 0
        errors = []
        for line in numbers_list:
            try:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) == 3:
                    country, phone, price = parts
                    price = Decimal(price)
                    supabase.table('inventory').insert({
                        'country': country, 'phone_number': phone,
                        'price': float(price), 'status': 'available'
                    }).execute()
                    added_count += 1
                else:
                    errors.append(f"تنسيق خاطئ: {line}")
            except Exception as e:
                errors.append(f"خطأ في: {line} - {str(e)}")

        result_text = f"✅ *تمت إضافة {added_count} أرقام بنجاح*\n"
        if errors:
            result_text += f"\n❌ *أخطاء ({len(errors)}):*\n" + '\n'.join(errors[:10])
        await message.answer(result_text, parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing admin add: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.callback_query(F.data == "admin_add_bulk")
async def admin_add_bulk_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "📋 *إضافة أرقام بالجملة*\n\nأرسل الأرقام بالصيغة التالية (كل سطر على حدة):\n"
            "`الدولة | رقم_الهاتف | السعر`\n\n"
            "مثال:\n`سوريا | +963123456789 | 5.00`\n`مصر | +201234567890 | 3.50`\n\n"
            "أرسل الأرقام الآن أو `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_numbers)
    except Exception as e:
        logger.error(f"Error in admin_add_bulk: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_view_inventory")
async def admin_view_inventory(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        response = supabase.table('inventory').select('country, status, is_sold').execute()
        if not response.data:
            await callback.answer("المخزون فارغ", show_alert=True)
            return

        countries = {}
        for item in response.data:
            country = item['country']
            if country not in countries:
                countries[country] = {'available': 0, 'sold': 0, 'expired': 0}
            if item['status'] == 'available' and not item['is_sold']:
                countries[country]['available'] += 1
            elif item['is_sold']:
                countries[country]['sold'] += 1
            else:
                countries[country]['expired'] += 1

        stats_text = "📊 *إحصائيات المخزون*\n\n"
        for country, stats in countries.items():
            stats_text += f"📍 *{country}:*\n  ✅ متاح: {stats['available']}\n  🛒 مباع: {stats['sold']}\n  ⏰ منتهي: {stats['expired']}\n\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 رجوع", callback_data="admin_inventory")
        await callback.message.edit_text(stats_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error viewing inventory: {e}")
        await callback.answer("❌ حدث خطأ")


# ============================================
# SESSION MANAGEMENT
# ============================================
@router.callback_query(F.data == "admin_sessions")
async def admin_sessions_menu(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        total_response = supabase.table('client_sessions').select('id').execute()
        active_response = supabase.table('client_sessions').select('id').eq('is_active', True).execute()
        banned_response = supabase.table('client_sessions').select('id').eq('is_banned', True).execute()
        total = len(total_response.data)
        active = len(active_response.data)
        banned = len(banned_response.data)

        builder = InlineKeyboardBuilder()
        builder.button(text="➕ إضافة جلسة جديدة", callback_data="admin_add_session")
        builder.button(text="📚 إضافة عدة جلسات (دفعة)", callback_data="admin_add_batch_sessions")
        builder.button(text="👁 عرض الجلسات", callback_data="admin_view_sessions")
        builder.button(text="⏸ إيقاف مؤقت", callback_data="admin_pause_session")
        builder.button(text="▶️ استئناف", callback_data="admin_resume_session")
        builder.button(text="🗑 حذف جلسة", callback_data="admin_delete_session")
        builder.button(text="🔙 رجوع", callback_data="admin_panel")
        builder.adjust(1)
        await callback.message.edit_text(
            f"🔐 *إدارة الجلسات*\n\n📊 *إحصائيات:*\n• الإجمالي: {total}\n• نشط: {active}\n• محظور: {banned}\n\nاختر العملية:",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in admin_sessions: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_add_session")
async def admin_add_session_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text("🔐 *تسجيل جلسة جديدة*\n\nأرسل رقم الهاتف بصيغة دولية:\nمثال: `+963123456789`\n\nأرسل `/cancel` للإلغاء", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_session_phone)
    except Exception as e:
        logger.error(f"Error in admin_add_session_start: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_session_phone))
async def admin_process_session_phone(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        phone = message.text.strip()
        if not phone.startswith('+') or not phone[1:].isdigit():
            await message.answer("❌ صيغة رقم الهاتف غير صحيحة\nأرسل رقم بصيغة: +963123456789")
            return

        await state.update_data(session_phone=phone)

        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')
        if not api_id or not api_hash:
            await message.answer("❌ خطأ في إعدادات API")
            await state.clear()
            return

        client = TelegramClient(StringSession(), int(api_id), api_hash)
        try:
            await client.connect()
            sent_code = await client.send_code_request(phone)
            await state.update_data(
                phone_code_hash=sent_code.phone_code_hash,
                temp_session_string=client.session.save()
            )
            await client.disconnect()
            await message.answer("📱 *تم إرسال رمز التحقق*\n\nأرسل الرمز الذي استلمته (مثال: 12345)", parse_mode="Markdown")
            await state.set_state(AdminStates.waiting_for_session_code)
        except FloodWaitError as e:
            await message.answer(f"❌ خطأ: يرجى الانتظار {e.seconds} ثانية")
            await state.clear()
        except Exception as e:
            logger.error(f"Error sending code: {e}")
            await message.answer(f"❌ خطأ في إرسال الرمز: {str(e)}")
            await state.clear()
    except Exception as e:
        logger.error(f"Error processing session phone: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.message(StateFilter(AdminStates.waiting_for_session_code))
async def admin_process_session_code(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        code = message.text.strip()
        data = await state.get_data()
        phone = data.get('session_phone')
        phone_code_hash = data.get('phone_code_hash')
        saved_session = data.get('temp_session_string')
        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')

        client = TelegramClient(StringSession(saved_session), int(api_id), api_hash)
        try:
            await client.connect()
            try:
                # v2.2.1: sign_in(code) يعتمد على الجلسة (تحمل phone_code_hash) - أكثر موثوقية
                try:
                    await client.sign_in(code=code)
                except Exception as _e1:
                    # fallback: الطريقة القديمة بالوسائط الكاملة
                    logger.debug(f"sign_in(code) failed ({_e1}), trying full args")
                    await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            except SessionPasswordNeededError:
                # FIXED v2.0.1: التقاط صحيح لخطأ 2FA
                await state.update_data(temp_client_session=client.session.save())
                await client.disconnect()
                await message.answer("🔐 *الحساب محمي بكلمة مرور*\n\nأرسل كلمة المرور (2FA):", parse_mode="Markdown")
                await state.set_state(AdminStates.waiting_for_session_2fa)
                return
            except Exception:
                raise

            session_string = client.session.save()
            await supabase.table('client_sessions').insert({
                'phone': phone, 'session_string': session_string,
                'is_active': True, 'api_id': int(api_id), 'api_hash': api_hash
            }).execute()
            await client.disconnect()
            await message.answer(f"✅ *تم تسجيل الجلسة بنجاح!*\n\n📱 الرقم: {phone}\n🔐 الحالة: نشط", parse_mode="Markdown")
            await state.clear()
        except Exception as e:
            logger.error(f"Error signing in: {e}")
            # v2.2.1: رسائل واضحة للأخطاء الشائعة
            _err = str(e)
            _friendly = _err
            if 'PHONE_CODE_INVALID' in _err or 'code invalid' in _err.lower():
                _friendly = "الرمز غير صحيح - تأكد من الكود وأعد المحاولة"
            elif 'PHONE_CODE_EXPIRED' in _err:
                _friendly = "انتهت صلاحية الرمز - ابدأ العملية من جديد"
            elif 'FLOOD_WAIT' in _err or 'FloodWait' in _err:
                _friendly = "طلبات كثيرة - انتظر ثم حاول لاحقاً"
            elif 'AUTH_KEY' in _err or 'auth key' in _err.lower():
                _friendly = "مشكلة في مفتاح الجلسة - أعد إرسال الرمز"
            await message.answer(f"❌ خطأ في تسجيل الدخول: {_friendly}")
            try:
                await client.disconnect()
            except Exception:
                pass
            await state.clear()
    except Exception as e:
        logger.error(f"Error processing session code: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.message(StateFilter(AdminStates.waiting_for_session_2fa))
async def admin_process_session_2fa(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        password = message.text.strip()
        data = await state.get_data()
        phone = data.get('session_phone')
        saved_session = data.get('temp_client_session')
        if not saved_session:
            await message.answer("❌ خطأ في بيانات الجلسة")
            await state.clear()
            return

        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')
        client = TelegramClient(StringSession(saved_session), int(api_id), api_hash)
        try:
            await client.connect()
            await client.sign_in(password=password)
            session_string = client.session.save()
            await supabase.table('client_sessions').insert({
                'phone': phone, 'session_string': session_string,
                'is_active': True, 'api_id': int(api_id), 'api_hash': api_hash
            }).execute()
            await client.disconnect()
            await message.answer(f"✅ *تم تسجيل الجلسة بنجاح!*\n\n📱 الرقم: {phone}\n🔐 الحالة: نشط", parse_mode="Markdown")
            await state.clear()
        except Exception as e:
            logger.error(f"Error in 2FA: {e}")
            await message.answer(f"❌ خطأ في كلمة المرور: {str(e)}")
            try:
                await client.disconnect()
            except Exception:
                pass
            await state.clear()
    except Exception as e:
        logger.error(f"Error processing 2FA: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()




# ============================================================
# v2.2.0: إضافة عدة جلسات دفعة واحدة
# ============================================================
@router.callback_query(F.data == "admin_add_batch_sessions")
async def admin_add_batch_sessions_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "📚 *إضافة عدة جلسات (دفعة)*\n\n"
            "أرسل الأرقام بصيغة دولية - كل رقم في سطر مستقل:\n\n"
            "`+963937373737`\n`+963938383838`\n`+963939393939`\n\n"
            "أو بدون +:\n`937373737`\n`938383838`\n\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_batch_phones)
    except Exception as e:
        logger.error(f"Error in batch sessions start: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_batch_phones))
async def admin_process_batch_phones(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        lines = [l.strip() for l in message.text.split('\n') if l.strip()]
        # تنظيف: إزالة + إذا كانت موجودة، والتحقق من الأرقام
        phones = []
        for line in lines:
            p = line.replace(' ', '').replace('+', '')
            if p.isdigit() and len(p) >= 7:
                phones.append('+' + p if not line.startswith('+') else line.replace(' ', ''))
        if not phones:
            await message.answer("❌ لم أجد أرقاماً صالحة. أرسل الأرقام كل سطر رقم (بصيغة دولية).")
            return
        if len(phones) > 20:
            await message.answer("⚠️ الحد الأقصى 20 رقم في الدفعة الواحدة. أرسل أقل.")
            return

        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')
        if not api_id or not api_hash:
            await message.answer("❌ خطأ في إعدادات API")
            await state.clear()
            return

        await message.answer(f"🔄 *جاري إرسال رموز التحقق إلى {len(phones)} رقم...*\nقد يستغرق ذلك بعض الوقت، انتظر قليلاً.", parse_mode="Markdown")

        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.errors import FloodWaitError

        pending = []  # قائمة: {phone, phone_code_hash, temp_session}
        errors = []
        for i, phone in enumerate(phones):
            try:
                client = TelegramClient(StringSession(), int(api_id), api_hash)
                await client.connect()
                sent = await client.send_code_request(phone)
                pending.append({
                    'phone': phone,
                    'phone_code_hash': sent.phone_code_hash,
                    'temp_session': client.session.save()
                })
                await client.disconnect()
            except FloodWaitError as e:
                errors.append(f"{phone}: انتظار {e.seconds} ثانية (FloodWait)")
                try:
                    await client.disconnect()
                except Exception:
                    pass
            except Exception as e:
                errors.append(f"{phone}: {str(e)[:80]}")
                try:
                    await client.disconnect()
                except Exception:
                    pass

        if not pending:
            await message.answer(
                "❌ *فشل إرسال الرموز لكل الأرقام*\n\n" + ("\n".join(errors[:10]) if errors else ""),
                parse_mode="Markdown"
            )
            await state.clear()
            return

        await state.update_data(batch_pending=pending)
        phones_list = "\n".join(f"{i+1}. {p['phone']}" for i, p in enumerate(pending))
        reply = (
            f"✅ *تم إرسال رموز التحقق لـ {len(pending)} رقم:*\n\n{phones_list}\n\n"
            f"📩 *أرسل الآن الأكواد بنفس الترتيب* - كل كود في سطر مستقل:\n\n"
            f"`12345`\n`23456`\n`34567`\n\n"
            f"أرسل `/cancel` للإلغاء"
        )
        if errors:
            reply += f"\n\n⚠️ *أخطاء (لم يُرسل لها رمز):*\n" + "\n".join(errors[:5])
        await message.answer(reply, parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_batch_codes)
    except Exception as e:
        logger.error(f"Error processing batch phones: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.message(StateFilter(AdminStates.waiting_for_batch_codes))
async def admin_process_batch_codes(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        data = await state.get_data()
        pending = data.get('batch_pending', [])
        if not pending:
            await message.answer("❌ لا توجد أرقام معلقة. ابدأ من جديد.")
            await state.clear()
            return

        codes = [l.strip() for l in message.text.split('\n') if l.strip()]
        if len(codes) != len(pending):
            await message.answer(
                f"❌ عدد الأكواد ({len(codes)}) لا يطابق عدد الأرقام ({len(pending)}).\n"
                f"أرسل كود لكل رقم بنفس الترتيب - كل كود في سطر.",
                parse_mode="Markdown"
            )
            return

        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.errors import SessionPasswordNeededError, FloodWaitError

        added = []
        failed = []
        need_2fa = []  # قائمة: {phone, temp_session}
        for i, item in enumerate(pending):
            phone = item['phone']
            code = codes[i]
            try:
                client = TelegramClient(StringSession(item['temp_session']), int(api_id), api_hash)
                await client.connect()
                try:
                    try:
                        await client.sign_in(code=code)
                    except Exception as _e1:
                        logger.debug(f"batch sign_in(code) failed ({_e1}), trying full args")
                        await client.sign_in(phone=phone, code=code, phone_code_hash=item['phone_code_hash'])
                    session_string = client.session.save()
                    await supabase.table('client_sessions').insert({
                        'phone': phone, 'session_string': session_string,
                        'is_active': True, 'api_id': int(api_id), 'api_hash': api_hash
                    }).execute()
                    added.append(phone)
                except SessionPasswordNeededError:
                    # حفظ الجلسة المؤقتة لمرحلة 2FA
                    need_2fa.append({'phone': phone, 'temp_session': client.session.save()})
                except FloodWaitError as e:
                    failed.append(f"{phone}: FloodWait {e.seconds}s")
                except Exception as e:
                    failed.append(f"{phone}: {str(e)[:60]}")
                await client.disconnect()
            except Exception as e:
                failed.append(f"{phone}: {str(e)[:60]}")

        if need_2fa:
            await state.update_data(batch_2fa_pending=need_2fa, batch_added=added, batch_failed=failed)
            phones_2fa = "\n".join(f"• {p['phone']}" for p in need_2fa)
            await message.answer(
                f"🔐 *{len(need_2fa)} حساب محمي بكلمة مرور (2FA):*\n\n{phones_2fa}\n\n"
                f"أرسل كلمة المرور (تُطبق على جميع هذه الحسابات):\n"
                f"أرسل `/skip` لتخطيها (تُسجل لاحقاً)",
                parse_mode="Markdown"
            )
            await state.set_state(AdminStates.waiting_for_batch_2fa)
            return

        summary = (
            f"✅ *اكتملت الإضافة الدفعية!*\n\n"
            f"🟢 تمت إضافة: {len(added)}\n"
            f"🔴 فشل: {len(failed)}"
        )
        if failed:
            summary += "\n\n" + "\n".join(failed[:10])
        await message.answer(summary, parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing batch codes: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.message(StateFilter(AdminStates.waiting_for_batch_2fa))
async def admin_process_batch_2fa(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        data = await state.get_data()
        need_2fa = data.get('batch_2fa_pending', [])
        added = data.get('batch_added', [])
        failed = data.get('batch_failed', [])

        api_id = os.getenv('API_ID')
        api_hash = os.getenv('API_HASH')
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        if message.text == '/skip':
            await state.clear()
            await message.answer(
                f"⏭ *تم التخطي - تُسجل الأكواد المتبقية لاحقاً يدوياً.*\n\n"
                f"🟢 أُضيفت: {len(added)}\n🔐 بانتظار 2FA: {len(need_2fa)}\n🔴 فشل: {len(failed)}",
                parse_mode="Markdown"
            )
            return

        password = message.text.strip()
        for item in need_2fa:
            phone = item['phone']
            try:
                client = TelegramClient(StringSession(item['temp_session']), int(api_id), api_hash)
                await client.connect()
                await client.sign_in(password=password)
                session_string = client.session.save()
                await supabase.table('client_sessions').insert({
                    'phone': phone, 'session_string': session_string,
                    'is_active': True, 'api_id': int(api_id), 'api_hash': api_hash
                }).execute()
                added.append(phone)
                await client.disconnect()
            except Exception as e:
                failed.append(f"{phone}: 2FA: {str(e)[:60]}")
                try:
                    await client.disconnect()
                except Exception:
                    pass

        summary = (
            f"✅ *اكتملت الإضافة الدفعية!*\n\n"
            f"🟢 تمت إضافة: {len(added)}\n"
            f"🔴 فشل: {len(failed)}"
        )
        if failed:
            summary += "\n\n" + "\n".join(failed[:10])
        await message.answer(summary, parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing batch 2FA: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


# ============================================================
# v2.2.0: إيقاف مؤقت / استئناف (الجلسة تبقى مسجلة)
# ============================================================
@router.callback_query(F.data == "admin_pause_session")
async def admin_pause_session_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "⏸ *إيقاف مؤقت لجلسة*\n\n"
            "أرسل رقم الهاتف أو أول 8 أحرف من معرف الجلسة (id):\n"
            "مثال: `+963937373737` أو `a1b2c3d4`\n\n"
            "الجلسة ستبقى مسجلة لكن لن تعمل حتى تستأنفها.\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_pause_phone)
    except Exception as e:
        logger.error(f"Error in pause prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_pause_phone))
async def admin_process_pause(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        target = message.text.strip().replace('+', '')
        q = supabase.table('client_sessions').update({'is_active': False})             .or_(f"phone.eq.+{target},phone.eq.{target},id.eq.{target}")
        resp = q.execute()
        if resp.data:
            await message.answer(f"⏸ *تم إيقاف الجلسة مؤقتاً:* {resp.data[0].get('phone')}\n\nتبقى مسجلة ويمكنك استئنافها لاحقاً.", parse_mode="Markdown")
        else:
            await message.answer("❌ لم أجد جلسة بهذا الرقم/المعرف.")
        await state.clear()
    except Exception as e:
        logger.error(f"Error pausing session: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.callback_query(F.data == "admin_resume_session")
async def admin_resume_session_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "▶️ *استئناف جلسة*\n\n"
            "أرسل رقم الهاتف أو أول 8 أحرف من معرف الجلسة (id):\n"
            "مثال: `+963937373737` أو `a1b2c3d4`\n\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_resume_phone)
    except Exception as e:
        logger.error(f"Error in resume prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_resume_phone))
async def admin_process_resume(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        target = message.text.strip().replace('+', '')
        q = supabase.table('client_sessions').update({'is_active': True})             .or_(f"phone.eq.+{target},phone.eq.{target},id.eq.{target}")
        resp = q.execute()
        if resp.data:
            await message.answer(f"▶️ *تم استئناف الجلسة:* {resp.data[0].get('phone')}", parse_mode="Markdown")
        else:
            await message.answer("❌ لم أجد جلسة بهذا الرقم/المعرف.")
        await state.clear()
    except Exception as e:
        logger.error(f"Error resuming session: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()



@router.callback_query(F.data == "admin_view_sessions")
async def admin_view_sessions(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        response = supabase.table('client_sessions').select('*').order('added_at', desc=True).limit(20).execute()
        if not response.data:
            await callback.answer("لا توجد جلسات", show_alert=True)
            return

        sessions_text = "📋 *قائمة الجلسات (آخر 20):*\n\n"
        for session in response.data:
            status_emoji = "🟢" if session['is_active'] else "🔴"
            banned_emoji = " ⚠️" if session['is_banned'] else ""
            added = (session.get('added_at') or '')[:10] or 'N/A'  # FIXED: slice آمن
            sessions_text += f"{status_emoji}{banned_emoji} `{session['phone']}`\n  🆔: `{session['id'][:8]}...`\n  📅: {added}\n\n"

        if len(sessions_text) > 4000:
            for i in range(0, len(sessions_text), 4000):
                await callback.message.answer(sessions_text[i:i + 4000], parse_mode="Markdown")
        else:
            builder = InlineKeyboardBuilder()
            builder.button(text="🔙 رجوع", callback_data="admin_sessions")
            await callback.message.edit_text(sessions_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error viewing sessions: {e}")
        await callback.answer("❌ حدث خطأ")


# ============================================
# PROXY SETTINGS (OLD - متوافق مع الإعدادات القديمة)
# ============================================
@router.callback_query(F.data == "admin_proxy")
async def admin_proxy_settings(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        proxy_enabled = await Database.get_setting('proxy_enabled') or 'false'
        proxy_host = await Database.get_setting('proxy_host') or 'غير محدد'
        proxy_port = await Database.get_setting('proxy_port') or 'غير محدد'
        proxy_type = await Database.get_setting('proxy_type') or 'socks5'
        status_emoji = "🟢" if proxy_enabled == 'true' else "🔴"

        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 تبديل حالة البروكسي", callback_data="admin_toggle_proxy")
        builder.button(text="🔧 تحديث إعدادات البروكسي", callback_data="admin_update_proxy")
        builder.button(text="📊 عرض الإعدادات الحالية", callback_data="admin_show_proxy")
        builder.button(text="🔙 رجوع", callback_data="admin_panel")
        builder.adjust(1)
        await callback.message.edit_text(
            f"🌐 *إعدادات البروكسي*\n\n{status_emoji} *الحالة:* {'مفعل' if proxy_enabled == 'true' else 'معطل'}\n🔗 *النوع:* {proxy_type}\n📍 *المضيف:* {proxy_host}\n🔌 *المنفذ:* {proxy_port}\n\nاختر الإجراء:",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in admin_proxy: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_toggle_proxy")
async def admin_toggle_proxy(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        current = await Database.get_setting('proxy_enabled') or 'false'
        new_state = 'false' if current == 'true' else 'true'
        await Database.update_setting('proxy_enabled', new_state)
        status_text = "مفعل 🟢" if new_state == 'true' else "معطل 🔴"
        await callback.answer(f"✅ تم تغيير حالة البروكسي إلى: {status_text}", show_alert=True)
        await admin_proxy_settings(callback)
    except Exception as e:
        logger.error(f"Error toggling proxy: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_update_proxy")
async def admin_update_proxy_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "🔧 *تحديث إعدادات البروكسي*\n\nأرسل بيانات البروكسي بالصيغة التالية:\n"
            "`IP:Port:Username:Password`\n\n"
            "مثال:\n`192.168.1.1:8080:user123:pass456`\n\n"
            "أو أرسل `none` لاستخدام اتصال مباشر\nأو `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_proxy_host)
    except Exception as e:
        logger.error(f"Error in admin_update_proxy_start: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_proxy_host))
async def admin_process_proxy_data(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        proxy_data = message.text.strip()
        if proxy_data.lower() == 'none':
            await Database.update_setting('proxy_enabled', 'false')
            await Database.update_setting('proxy_host', '')
            await Database.update_setting('proxy_port', '')
            await Database.update_setting('proxy_username', '')
            await Database.update_setting('proxy_password', '')
            await message.answer("✅ تم تعطيل البروكسي وسيتم استخدام اتصال مباشر")
            await state.clear()
            return

        parts = proxy_data.split(':')
        if len(parts) != 4:
            await message.answer("❌ صيغة غير صحيحة\nاستخدم: IP:Port:Username:Password")
            return
        ip, port, username, password = parts
        try:
            port_num = int(port)
            if port_num < 1 or port_num > 65535:
                raise ValueError("Invalid port range")
        except ValueError:
            await message.answer("❌ المنفذ غير صالح (يجب أن يكون بين 1-65535)")
            return

        await Database.update_setting('proxy_host', ip)
        await Database.update_setting('proxy_port', str(port_num))
        await Database.update_setting('proxy_username', username)
        await Database.update_setting('proxy_password', password)
        await Database.update_setting('proxy_enabled', 'true')
        await message.answer(f"✅ *تم تحديث إعدادات البروكسي بنجاح!*\n\n📍 المضيف: {ip}\n🔌 المنفذ: {port_num}\n👤 المستخدم: {username}\n🔐 الحالة: مفعل", parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing proxy data: {e}")
        await message.answer("❌ حدث خطأ في حفظ البيانات")
        await state.clear()


@router.callback_query(F.data == "admin_show_proxy")
async def admin_show_proxy_details(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        proxy_enabled = await Database.get_setting('proxy_enabled') or 'false'
        proxy_host = await Database.get_setting('proxy_host') or 'غير محدد'
        proxy_port = await Database.get_setting('proxy_port') or 'غير محدد'
        proxy_username = await Database.get_setting('proxy_username') or 'غير محدد'
        proxy_password = await Database.get_setting('proxy_password') or '****'
        proxy_type = await Database.get_setting('proxy_type') or 'socks5'

        details = (
            f"🌐 *تفاصيل إعدادات البروكسي*\n\n"
            f"🔗 *النوع:* `{proxy_type}`\n🟢 *مفعل:* `{proxy_enabled}`\n"
            f"📍 *المضيف:* `{proxy_host}`\n🔌 *المنفذ:* `{proxy_port}`\n"
            f"👤 *المستخدم:* `{proxy_username}`\n🔑 *كلمة المرور:* `{proxy_password}`\n\n"
            f"🔗 *رابط الاتصال:* `{proxy_type}://{proxy_username}:****@{proxy_host}:{proxy_port}`"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 رجوع", callback_data="admin_proxy")
        await callback.message.edit_text(details, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error showing proxy details: {e}")
        await callback.answer("❌ حدث خطأ")


# ============================================
# STATISTICS
# ============================================
@router.callback_query(F.data == "admin_stats")
async def admin_statistics(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        total_users = supabase.table('users').select('user_id', count='exact').execute()
        total_numbers = supabase.table('inventory').select('id', count='exact').execute()
        total_sold = supabase.table('inventory').select('id', count='exact').eq('is_sold', True).execute()
        total_transactions = supabase.table('transactions').select('id', count='exact').execute()
        approved_transactions = supabase.table('transactions').select('id', count='exact').eq('status', 'approved').execute()
        revenue_response = supabase.table('transactions').select('amount').eq('status', 'approved').execute()
        total_revenue = sum([t['amount'] for t in revenue_response.data]) if revenue_response.data else 0

        stats = (
            "📊 *إحصائيات البوت*\n\n"
            f"👥 *إجمالي المستخدمين:* {len(total_users.data)}\n"
            f"📱 *إجمالي الأرقام:* {len(total_numbers.data)}\n"
            f"🛒 *الأرقام المباعة:* {len(total_sold.data)}\n"
            f"📦 *المخزون المتاح:* {len(total_numbers.data) - len(total_sold.data)}\n\n"
            f"💳 *إجمالي المعاملات:* {len(total_transactions.data)}\n"
            f"✅ *المعاملات المقبولة:* {len(approved_transactions.data)}\n"
            f"💰 *إجمالي الإيرادات:* ${total_revenue:.2f}\n\n"
            f"📅 *التاريخ:* {_utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 تحديث", callback_data="admin_stats")
        builder.button(text="🔙 رجوع", callback_data="admin_panel")
        await callback.message.edit_text(stats, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_stats: {e}")
        await callback.answer("❌ حدث خطأ")


# ============================================
# SETTINGS MENU
# ============================================
@router.callback_query(F.data == "admin_settings")
async def admin_settings_menu(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        builder = InlineKeyboardBuilder()
        builder.button(text="📢 إدارة القنوات الإجبارية", callback_data="admin_channels")
        builder.button(text="💰 إعدادات الدفع", callback_data="admin_payment_settings")
        builder.button(text="⚙️ إعدادات متقدمة", callback_data="admin_advanced")
        builder.button(text="🔙 رجوع", callback_data="admin_panel")
        builder.adjust(1)
        await callback.message.edit_text("⚙️ *الإعدادات*\n\nاختر القسم المطلوب:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_settings: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_panel")
async def back_to_admin_panel(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.delete()
        await admin_panel(callback.message)
    except Exception as e:
        logger.error(f"Error returning to admin panel: {e}")


# ============================================
# CHANNELS MANAGEMENT
# ============================================
@router.callback_query(F.data == "admin_channels")
async def admin_channels_menu(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        channels = await Database.get_mandatory_channels()
        channels_text = "📢 *القنوات الإجبارية الحالية:*\n\n"
        if channels:
            for i, channel in enumerate(channels, 1):
                channels_text += f"{i}. {channel}\n"
        else:
            channels_text += "لا توجد قنوات مضافة\n"

        builder = InlineKeyboardBuilder()
        builder.button(text="➕ إضافة قناة", callback_data="admin_add_channel")
        builder.button(text="🗑 حذف قناة", callback_data="admin_remove_channel")
        builder.button(text="🔙 رجوع", callback_data="admin_settings")
        builder.adjust(1)
        await callback.message.edit_text(channels_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in admin_channels_menu: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_add_channel")
async def admin_add_channel_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "➕ *إضافة قناة إجبارية*\n\nأرسل معرف القناة:\n"
            "- للمعرف العام: `@channelusername`\n"
            "- للمعرف الخاص: `-1001234567890`\n\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_channel)
    except Exception as e:
        logger.error(f"Error in admin_add_channel_prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_channel))
async def admin_process_add_channel(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        channel_id = message.text.strip()
        if not (channel_id.startswith('@') or channel_id.startswith('-100')):
            await message.answer("❌ صيغة غير صحيحة\nاستخدم @username أو -1001234567890")
            return

        channels_str = await Database.get_setting('mandatory_channels') or '[]'
        channels = json.loads(channels_str)
        if channel_id not in channels:
            channels.append(channel_id)
            await Database.update_setting('mandatory_channels', json.dumps(channels))
            await message.answer(f"✅ تمت إضافة القناة: {channel_id}")
        else:
            await message.answer("❌ هذه القناة مضافة بالفعل")
        await state.clear()
    except Exception as e:
        logger.error(f"Error adding channel: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.callback_query(F.data == "admin_remove_channel")
async def admin_remove_channel_prompt(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        channels = await Database.get_mandatory_channels()
        if not channels:
            await callback.answer("لا توجد قنوات للحذف", show_alert=True)
            return

        builder = InlineKeyboardBuilder()
        for channel in channels:
            builder.button(text=f"🗑 {channel}", callback_data=f"remove_channel_{channel}")
        builder.button(text="🔙 رجوع", callback_data="admin_channels")
        builder.adjust(1)
        await callback.message.edit_text("🗑 *حذف قناة إجبارية*\n\nاختر القناة المراد حذفها:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in remove channel prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data.startswith("remove_channel_"))
async def admin_remove_channel_execute(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        channel_to_remove = callback.data.replace("remove_channel_", "")
        channels_str = await Database.get_setting('mandatory_channels') or '[]'
        channels = json.loads(channels_str)
        if channel_to_remove in channels:
            channels.remove(channel_to_remove)
            await Database.update_setting('mandatory_channels', json.dumps(channels))
            await callback.answer(f"✅ تم حذف القناة: {channel_to_remove}", show_alert=True)
        else:
            await callback.answer("❌ القناة غير موجودة", show_alert=True)
        await admin_channels_menu(callback)
    except Exception as e:
        logger.error(f"Error removing channel: {e}")
        await callback.answer("❌ حدث خطأ")


# ============================================
# PAYMENT SETTINGS
# ============================================
@router.callback_query(F.data == "admin_payment_settings")
async def admin_payment_settings(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        min_deposit = await Database.get_setting('min_deposit_amount') or '0.50'
        binance_pay_id = await Database.get_setting('binance_pay_id') or os.getenv('BINANCE_PAY_ID', 'غير محدد')

        builder = InlineKeyboardBuilder()
        builder.button(text="💰 تغيير الحد الأدنى للإيداع", callback_data="admin_set_min_deposit")
        builder.button(text="🆔 تغيير Binance Pay ID", callback_data="admin_set_binance_id")
        builder.button(text="🔙 رجوع", callback_data="admin_settings")
        builder.adjust(1)
        await callback.message.edit_text(f"💰 *إعدادات الدفع*\n\n💵 *الحد الأدنى للإيداع:* ${min_deposit}\n🆔 *Binance Pay ID:* `{binance_pay_id}`\n\nاختر الإعداد المراد تعديله:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in payment settings: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_set_min_deposit")
async def admin_set_min_deposit_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text("💰 *تغيير الحد الأدنى للإيداع*\n\nأرسل المبلغ الجديد بالدولار:\nمثال: `1.00`\n\nأرسل `/cancel` للإلغاء", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_min_deposit)
    except Exception as e:
        logger.error(f"Error in set min deposit prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_min_deposit))
async def admin_process_min_deposit(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                raise ValueError("Amount must be positive")
        except ValueError:
            await message.answer("❌ يرجى إدخال مبلغ صحيح (أرقام فقط)")
            return
        await Database.update_setting('min_deposit_amount', str(amount))
        await message.answer(f"✅ تم تغيير الحد الأدنى للإيداع إلى: ${amount:.2f}")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing min deposit: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.callback_query(F.data == "admin_set_binance_id")
async def admin_set_binance_id_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text("🆔 *تغيير Binance Pay ID*\n\nأرسل Pay ID الجديد:\nمثال: `123456789`\n\nأرسل `/cancel` للإلغاء", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_binance_id)
    except Exception as e:
        logger.error(f"Error in set binance id prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_binance_id))
async def admin_process_binance_id(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        binance_id = message.text.strip()
        if not binance_id.isdigit():
            await message.answer("❌ Pay ID يجب أن يكون أرقام فقط")
            return
        await Database.update_setting('binance_pay_id', binance_id)
        await message.answer(f"✅ تم تغيير Binance Pay ID إلى: `{binance_id}`", parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing binance id: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


# ============================================
# ADVANCED SETTINGS
# ============================================
@router.callback_query(F.data == "admin_advanced")
async def admin_advanced_settings(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        maintenance_mode = await Database.get_setting('bot_maintenance_mode') or 'false'
        session_duration = await Database.get_setting('session_duration_minutes') or '15'
        referral_points = await Database.get_setting('referral_points_reward') or '10'

        builder = InlineKeyboardBuilder()
        builder.button(text=f"🔄 وضع الصيانة: {'مفعل' if maintenance_mode == 'true' else 'معطل'}", callback_data="admin_toggle_maintenance")
        builder.button(text="⏰ تغيير مدة الجلسة", callback_data="admin_set_session_duration")
        builder.button(text="🎁 تغيير نقاط الإحالة", callback_data="admin_set_referral_points")
        builder.button(text="🗑 تنظيف المهام القديمة", callback_data="admin_clean_tasks")
        builder.button(text="🔙 رجوع", callback_data="admin_settings")
        builder.adjust(1)
        await callback.message.edit_text(
            f"⚙️ *الإعدادات المتقدمة*\n\n🔄 *وضع الصيانة:* {'مفعل 🟢' if maintenance_mode == 'true' else 'معطل 🔴'}\n⏰ *مدة الجلسة:* {session_duration} دقيقة\n🎁 *نقاط الإحالة:* {referral_points} نقطة\n\nاختر الإعداد المراد تعديله:",
            reply_markup=builder.as_markup(), parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in advanced settings: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_toggle_maintenance")
async def admin_toggle_maintenance(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        current = await Database.get_setting('bot_maintenance_mode') or 'false'
        new_state = 'false' if current == 'true' else 'true'
        await Database.update_setting('bot_maintenance_mode', new_state)
        status_text = "مفعل 🟢" if new_state == 'true' else "معطل 🔴"
        await callback.answer(f"✅ وضع الصيانة: {status_text}", show_alert=True)
        await admin_advanced_settings(callback)
    except Exception as e:
        logger.error(f"Error toggling maintenance: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_set_session_duration")
async def admin_set_session_duration_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text("⏰ *تغيير مدة الجلسة*\n\nأرسل المدة بالدقائق:\nمثال: `30`\n\nأرسل `/cancel` للإلغاء", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_session_duration)
    except Exception as e:
        logger.error(f"Error in set session duration prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_session_duration))
async def admin_process_session_duration(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        try:
            duration = int(message.text.strip())
            if duration < 1 or duration > 120:
                raise ValueError("Duration out of range")
        except ValueError:
            await message.answer("❌ يرجى إدخال رقم صحيح بين 1 و 120 دقيقة")
            return
        await Database.update_setting('session_duration_minutes', str(duration))
        global SESSION_DURATION
        SESSION_DURATION = duration
        await message.answer(f"✅ تم تغيير مدة الجلسة إلى: {duration} دقيقة")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing session duration: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.callback_query(F.data == "admin_set_referral_points")
async def admin_set_referral_points_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text("🎁 *تغيير نقاط الإحالة*\n\nأرسل عدد النقاط الجديدة:\nمثال: `20`\n\nأرسل `/cancel` للإلغاء", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_referral_points)
    except Exception as e:
        logger.error(f"Error in set referral points prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_referral_points))
async def admin_process_referral_points(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        try:
            points = int(message.text.strip())
            if points < 1:
                raise ValueError("Points must be positive")
        except ValueError:
            await message.answer("❌ يرجى إدخال رقم صحيح موجب")
            return
        await Database.update_setting('referral_points_reward', str(points))
        await message.answer(f"✅ تم تغيير نقاط الإحالة إلى: {points} نقطة")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing referral points: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.callback_query(F.data == "admin_clean_tasks")
async def admin_clean_tasks(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        seven_days_ago = (_utcnow() - timedelta(days=7)).isoformat()
        completed_deleted = supabase.table('tasks_queue').delete().eq('status', 'completed').lt('completed_at', seven_days_ago).execute()
        three_days_ago = (_utcnow() - timedelta(days=3)).isoformat()
        failed_deleted = supabase.table('tasks_queue').delete().eq('status', 'failed').lt('created_at', three_days_ago).execute()
        await callback.answer(
            f"✅ تم تنظيف المهام القديمة\n"
            f"المهام المكتملة المحذوفة: {len(completed_deleted.data) if completed_deleted.data else 0}\n"
            f"المهام الفاشلة المحذوفة: {len(failed_deleted.data) if failed_deleted.data else 0}",
            show_alert=True
        )
    except Exception as e:
        logger.error(f"Error cleaning tasks: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "admin_delete_number")
async def admin_delete_number_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text("🗑 *حذف رقم من المخزون*\n\nأرسل رقم الهاتف المراد حذفه:\nمثال: `+963123456789`\n\nأرسل `/cancel` للإلغاء", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_delete_number)
    except Exception as e:
        logger.error(f"Error in delete number prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_delete_number))
async def admin_process_delete_number(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        phone = message.text.strip()
        response = supabase.table('inventory').delete().eq('phone_number', phone).execute()
        if response.data:
            await message.answer(f"✅ تم حذف الرقم: {phone}")
        else:
            await message.answer("❌ الرقم غير موجود في المخزون")
        await state.clear()
    except Exception as e:
        logger.error(f"Error deleting number: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


# ============================================
# BROADCAST MESSAGE
# ============================================
@router.message(Command("broadcast"))
async def broadcast_message(message: Message, state: FSMContext):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ غير مصرح لك")
            return
        text = message.text.replace('/broadcast', '').strip()
        if not text:
            await message.answer("📢 *إرسال رسالة جماعية*\n\nاستخدم الأمر مع النص:\n`/broadcast نص الرسالة هنا`\n\nأرسل `/cancel` للإلغاء", parse_mode="Markdown")
            await state.set_state(AdminStates.waiting_for_broadcast)
            return
        await process_broadcast(message, text)
    except Exception as e:
        logger.error(f"Error in broadcast: {e}")
        await message.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_broadcast))
async def admin_process_broadcast(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        await process_broadcast(message, message.text)
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing broadcast: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


async def process_broadcast(message: Message, text: str):
    try:
        response = supabase.table('users').select('user_id').execute()
        if not response.data:
            await message.answer("❌ لا يوجد مستخدمين")
            return

        success_count = 0
        fail_count = 0
        await message.answer(f"📢 *جاري إرسال الرسالة الجماعية...*\nعدد المستخدمين: {len(response.data)}", parse_mode="Markdown")

        for user in response.data:
            try:
                await bot.send_message(user['user_id'], f"📢 *رسالة من الإدارة*\n\n{text}", parse_mode="Markdown")
                success_count += 1
                await asyncio.sleep(0.05)
            except Exception:
                fail_count += 1

        await message.answer(f"✅ *تم إرسال الرسالة الجماعية*\n\n✅ نجاح: {success_count}\n❌ فشل: {fail_count}", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in process_broadcast: {e}")
        await message.answer("❌ حدث خطأ في إرسال الرسالة الجماعية")


# ============================================
# USER INFO (ADMIN)
# ============================================
@router.message(Command("user_info"))
async def admin_user_info(message: Message):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ غير مصرح لك")
            return
        parts = message.text.split()
        if len(parts) < 2:
            await message.answer("❌ استخدم: `/user_info 123456789`", parse_mode="Markdown")
            return
        try:
            user_id = int(parts[1])
        except ValueError:
            await message.answer("❌ معرف مستخدم غير صالح")
            return

        user = await Database.get_user(user_id)
        if not user:
            await message.answer(f"❌ المستخدم {user_id} غير موجود")
            return

        purchases = supabase.table('inventory').select('*').eq('buyer_id', user_id).execute()
        purchases_count = len(purchases.data) if purchases.data else 0
        transactions = await Database.get_user_transactions(user_id)
        info_text = (
            f"👤 *معلومات المستخدم*\n\n"
            f"🆔 *ID:* `{user['user_id']}`\n"
            f"👤 *Username:* @{user.get('username', 'غير محدد')}\n"
            f"📝 *الاسم:* {user.get('first_name', '')} {user.get('last_name', '')}\n"
            f"💰 *الرصيد:* ${user.get('balance', 0):.2f}\n"
            f"🎁 *النقاط:* {user.get('points', 0)}\n"
            f"👥 *الإحالات:* {user.get('total_referrals', 0)}\n"
            f"📅 *تاريخ الانضمام:* {user.get('joined_at', 'غير محدد')}\n"
            f"🛒 *عدد المشتريات:* {purchases_count}\n"
            f"💳 *عدد المعاملات:* {len(transactions)}\n"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="💰 تعديل الرصيد", callback_data=f"admin_edit_balance_{user_id}")
        builder.button(text="🎁 تعديل النقاط", callback_data=f"admin_edit_points_{user_id}")
        builder.button(text="🚫 حظر/فك حظر", callback_data=f"admin_toggle_ban_{user_id}")
        builder.adjust(2)
        await message.answer(info_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in user_info: {e}")
        await message.answer("❌ حدث خطأ")


@router.callback_query(F.data.startswith("admin_edit_balance_"))
async def admin_edit_balance_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        user_id = int(callback.data.replace("admin_edit_balance_", ""))
        await state.update_data(edit_user_id=user_id)
        await callback.message.answer("💰 *تعديل رصيد المستخدم*\n\nأرسل الرصيد الجديد:\nمثال: `50.00`\n\nأرسل `/cancel` للإلغاء", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_edit_balance)
    except Exception as e:
        logger.error(f"Error in edit balance prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_edit_balance))
async def admin_process_edit_balance(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        try:
            new_balance = float(message.text.strip())
            if new_balance < 0:
                raise ValueError("Balance cannot be negative")
        except ValueError:
            await message.answer("❌ يرجى إدخال مبلغ صحيح")
            return
        data = await state.get_data()
        user_id = data.get('edit_user_id')
        if not user_id:
            await message.answer("❌ خطأ في البيانات")
            await state.clear()
            return
        supabase.table('users').update({'balance': new_balance}).eq('user_id', user_id).execute()
        await message.answer(f"✅ تم تعديل رصيد المستخدم {user_id} إلى: ${new_balance:.2f}")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing balance edit: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.callback_query(F.data.startswith("admin_edit_points_"))
async def admin_edit_points_prompt(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        user_id = int(callback.data.replace("admin_edit_points_", ""))
        await state.update_data(edit_user_id=user_id)
        await callback.message.answer("🎁 *تعديل نقاط المستخدم*\n\nأرسل عدد النقاط الجديد:\nمثال: `100`\n\nأرسل `/cancel` للإلغاء", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_edit_points)
    except Exception as e:
        logger.error(f"Error in edit points prompt: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_edit_points))
async def admin_process_edit_points(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        try:
            new_points = int(message.text.strip())
            if new_points < 0:
                raise ValueError("Points cannot be negative")
        except ValueError:
            await message.answer("❌ يرجى إدخال رقم صحيح")
            return
        data = await state.get_data()
        user_id = data.get('edit_user_id')
        if not user_id:
            await message.answer("❌ خطأ في البيانات")
            await state.clear()
            return
        supabase.table('users').update({'points': new_points}).eq('user_id', user_id).execute()
        await message.answer(f"✅ تم تعديل نقاط المستخدم {user_id} إلى: {new_points}")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing points edit: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.callback_query(F.data.startswith("admin_toggle_ban_"))
async def admin_toggle_ban(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        user_id = int(callback.data.replace("admin_toggle_ban_", ""))
        user = await Database.get_user(user_id)
        if not user:
            await callback.answer("❌ المستخدم غير موجود", show_alert=True)
            return
        new_ban_status = not user.get('is_banned', False)
        supabase.table('users').update({'is_banned': new_ban_status}).eq('user_id', user_id).execute()
        status_text = "محظور 🚫" if new_ban_status else "مفعل ✅"
        await callback.answer(f"تم تغيير حالة المستخدم إلى: {status_text}", show_alert=True)
    except Exception as e:
        logger.error(f"Error toggling ban: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(Command("stats"))
async def public_stats(message: Message):
    try:
        total_users_response = supabase.table('users').select('user_id', count='exact').execute()
        total_users = len(total_users_response.data) if total_users_response.data else 0
        available_response = supabase.table('inventory').select('id', count='exact').eq('is_sold', False).eq('status', 'available').execute()
        available_numbers = len(available_response.data) if available_response.data else 0
        countries_response = supabase.table('inventory').select('country').eq('is_sold', False).eq('status', 'available').execute()
        countries = set()
        if countries_response.data:
            for item in countries_response.data:
                countries.add(item['country'])

        stats_text = f"📊 *إحصائيات البوت*\n\n👥 *عدد المستخدمين:* {total_users}\n📱 *الأرقام المتاحة:* {available_numbers}\n🌍 *الدول المتاحة:* {len(countries)}\n\nللشراء والتواصل: @MyNumberShopBot"
        await message.answer(stats_text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in public_stats: {e}")
        await message.answer("❌ حدث خطأ")


# ============================================
# TASK AUTOMATION - MAIN MENU
# ============================================
@router.callback_query(F.data == "admin_tasks")
async def admin_tasks_menu(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "🤖 *المهام الآلية*\n\nاختر نوع المهمة:",
            reply_markup=Keyboards.task_type_selector(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in admin_tasks_menu: {e}")
        await callback.answer("❌ حدث خطأ")


# ---- SMART TASK (AUTO LEARN) ----
@router.callback_query(F.data == "task_smart")
async def task_smart_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "🧠 *مهمة ذكية (تلقائية)*\n\n"
            "أرسل رابط البوت المستهدف:\n"
            "مثال: `https://t.me/BotName?start=REF123`\n\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_task_bot_link)
        await state.update_data(task_mode="smart")
    except Exception as e:
        logger.error(f"Error in task_smart_start: {e}")
        await callback.answer("❌ حدث خطأ")


# ---- MANUAL TASK ----
@router.callback_query(F.data == "task_manual")
async def task_manual_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "✋ *مهمة يدوية*\n\n"
            "أرسل رابط البوت المستهدف:\n"
            "مثال: `https://t.me/BotName?start=REF123`\n\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_task_bot_link)
        await state.update_data(task_mode="manual")
    except Exception as e:
        logger.error(f"Error in task_manual_start: {e}")
        await callback.answer("❌ حدث خطأ")


# ---- FOLLOW CHANNEL TASK ----
@router.callback_query(F.data == "task_follow")
async def task_follow_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "📢 *متابعة قناة/مجموعة (متعدد)*\n\n"
            "أرسل قائمة القنوات (كل سطر قناة):\n"
            "مثال:\n"
            "`https://t.me/channel1`\n"
            "`https://t.me/channel2`\n"
            "`@channel3`\n\n"
            "يدعم 1-15 قناة، سيتم توزيعها بذكاء على الحسابات.\n\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_channels_list)
        await state.update_data(task_mode="follow_channel")
    except Exception as e:
        logger.error(f"Error in task_follow_start: {e}")
        await callback.answer("❌ حدث خطأ")


# ---- REACT TO POST TASK ----
@router.callback_query(F.data == "task_react")
async def task_react_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "💬 *تفاعل على منشور*\n\n"
            "أرسل رابط المنشور المستهدف:\n"
            "مثال: `https://t.me/ChannelName/12345`\n\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_message_link)
        await state.update_data(task_mode="react_post")
    except Exception as e:
        logger.error(f"Error in task_react_start: {e}")
        await callback.answer("❌ حدث خطأ")


# ---- VOTE TASK ----
@router.callback_query(F.data == "task_vote")
async def task_vote_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "⭐ *تصويت في استفتاء*\n\n"
            "أرسل رابط الرسالة التي تحتوي على الاستفتاء:\n"
            "مثال: `https://t.me/ChannelName/12345`\n\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_message_link)
        await state.update_data(task_mode="vote_poll")
    except Exception as e:
        logger.error(f"Error in task_vote_start: {e}")
        await callback.answer("❌ حدث خطأ")


# ---- FORWARD TASK ----
@router.callback_query(F.data == "task_forward")
async def task_forward_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "🔄 *إعادة توجيه رسالة*\n\n"
            "أرسل رابط الرسالة الأصلية:\n"
            "مثال: `https://t.me/ChannelName/12345`\n\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_message_link)
        await state.update_data(task_mode="forward")
    except Exception as e:
        logger.error(f"Error in task_forward_start: {e}")
        await callback.answer("❌ حدث خطأ")


# ---- HANDLE BOT LINK INPUT ----
@router.message(StateFilter(AdminStates.waiting_for_task_bot_link))
async def process_task_bot_link(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        bot_link = message.text.strip()
        await state.update_data(task_bot_link=bot_link)
        await message.answer("📊 *عدد الحسابات*\n\nكم حساب تريد استخدامه؟\nأرسل رقماً: `5`", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_task_accounts_count)
    except Exception as e:
        logger.error(f"Error processing bot link: {e}")
        await message.answer("❌ حدث خطأ")


# ---- HANDLE MESSAGE LINK INPUT ----
@router.message(StateFilter(AdminStates.waiting_for_message_link))
async def process_message_link(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        msg_link = message.text.strip()
        data = await state.get_data()
        task_mode = data.get('task_mode', 'react_post')
        await state.update_data(target_message_link=msg_link)

        if task_mode == 'vote_poll':
            await message.answer("🗳 *خيار التصويت*\n\nأرسل رقم الخيار أو اسمه:\nمثال: `1` أو `الخيار الأول`", parse_mode="Markdown")
            await state.set_state(AdminStates.waiting_for_vote_option)
        elif task_mode == 'react_post':
            await message.answer("😊 *الإيموجي*\n\nأرسل الإيموجي المطلوب:\nمثال: `👍`\nأو اكتب `random` لإيموجي عشوائي", parse_mode="Markdown")
            await state.set_state(AdminStates.waiting_for_emoji)
        elif task_mode == 'forward':
            await message.answer("📤 *الجهة المستهدفة*\n\nأرسل رابط البوت أو المجموعة المراد التوجيه إليها:", parse_mode="Markdown")
            await state.set_state(AdminStates.waiting_for_task_bot_link)
    except Exception as e:
        logger.error(f"Error processing message link: {e}")
        await message.answer("❌ حدث خطأ")


# ---- HANDLE ACCOUNTS COUNT ----
@router.message(StateFilter(AdminStates.waiting_for_task_accounts_count))
async def process_accounts_count(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        try:
            count = int(message.text.strip())
        except ValueError:
            await message.answer("❌ الرجاء إدخال رقم صحيح")
            return
        if count < 1 or count > 100:
            await message.answer("❌ الرجاء إدخال رقم بين 1 و 100")
            return
        await state.update_data(accounts_count=count)
        await message.answer("⚡ *سرعة التنفيذ*\n\nاختر السرعة:", reply_markup=Keyboards.task_speed_selector(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error processing accounts count: {e}")
        await message.answer("❌ حدث خطأ")


# ---- HANDLE SPEED SELECTION ----
@router.callback_query(F.data.startswith("speed_"))
async def process_speed_selection(callback: CallbackQuery, state: FSMContext):
    try:
        speed = callback.data.replace("speed_", "")
        speed_labels = {"slow": "بطيء", "medium": "متوسط", "fast": "سريع"}
        await state.update_data(task_speed=speed)

        data = await state.get_data()
        task_mode = data.get('task_mode', 'smart')
        bot_link = data.get('task_bot_link', '')
        target_message_link = data.get('target_message_link', '')
        accounts_count = data.get('accounts_count', 0)
        emoji_target = data.get('emoji_target', '👍')
        vote_option = data.get('vote_option', '0')
        channel_list = data.get('channel_list', '[]')

        if task_mode == 'manual':
            await callback.message.edit_text(
                "✋ *الخطوات اليدوية*\n\n"
                "أرسل الخطوات بالترتيب (كل سطر خطوة):\n"
                "الخيارات: `start`, `language`, `subscribe`, `check`, `math`, `emoji`, `text`, `phone`, `visit`, `forward`, `follow_channel`, `react_post`, `vote_poll`\n\n"
                "مثال:\n`start`\n`language`\n`subscribe`\n`check`\n`math`\n\n"
                "يمكنك أيضاً كتابة: `text:مرحبا` أو `forward:https://t.me/xxx/123`\n\n"
                "أرسل `/cancel` للإلغاء",
                parse_mode="Markdown"
            )
            await state.set_state(AdminStates.waiting_for_composite_steps)
            return

        # FIXED v2.0.1: follow_channel يستخدم أول قناة كـ target_bot_link (NOT NULL)
        final_bot_link = bot_link
        final_task_type = task_mode
        if task_mode == 'smart':
            final_task_type = 'composite'
        elif task_mode == 'follow_channel':
            final_task_type = 'follow_channel'
            channels = []
            try:
                parsed = json.loads(channel_list) if isinstance(channel_list, str) else channel_list
                channels = [str(c).strip() for c in parsed if str(c).strip()]
            except Exception:
                channels = []
            final_bot_link = channels[0] if channels else (bot_link or target_message_link or 'unknown')
        elif task_mode in ('react_post', 'vote_poll', 'forward'):
            final_task_type = task_mode

        task_data = {
            'target_bot_link': final_bot_link or target_message_link or bot_link or 'unknown',
            'target_message_link': target_message_link,
            'task_type': final_task_type,
            'status': 'pending',
            'speed': speed,
            'composite_steps': json.dumps([]),
            'emoji_target': emoji_target,
            'vote_option': vote_option,
            'channel_list': channel_list if isinstance(channel_list, str) else json.dumps(channel_list, ensure_ascii=False),
            'required_accounts': accounts_count if accounts_count else 1,
            'multi_account': True if accounts_count and accounts_count > 1 else False,
            'parent_task_id': None,
            'created_at': _utcnow().isoformat()
        }
        response = supabase.table('tasks_queue').insert(task_data).execute()
        task_id = response.data[0]['id'] if response.data else None

        if task_id:
            await callback.message.edit_text(
                f"✅ *تم إنشاء المهمة!*\n\n"
                f"🆔 رقم المهمة: `{task_id}`\n"
                f"🔗 الهدف: {str(final_bot_link or target_message_link)[:50]}\n"
                f"📋 النوع: {final_task_type}\n"
                f"👤 الحسابات: {accounts_count}\n"
                f"⚡ السرعة: {speed_labels.get(speed, speed)}\n"
                f"📦 متعدد الحسابات: {'نعم' if task_data['multi_account'] else 'لا'}\n"
                f"📋 الحالة: ⏳ قيد الانتظار\n\n"
                f"سيبدأ المحرك بتوزيعها تلقائياً على {accounts_count} حساب.",
                parse_mode="Markdown"
            )
        else:
            await callback.answer("❌ فشل في إنشاء المهمة", show_alert=True)
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing speed: {e}")
        await callback.answer("❌ حدث خطأ")


# ============================================
# FIXED v3.0: Missing Handlers for Manual & Advanced Tasks
# ============================================
@router.message(StateFilter(AdminStates.waiting_for_composite_steps))
async def process_composite_steps(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        steps_text = message.text.strip()
        if not steps_text:
            await message.answer("❌ أرسل خطوات صحيحة")
            return

        lines = [l.strip() for l in steps_text.split('\n') if l.strip()]
        valid_types = ['start', 'language', 'subscribe', 'check', 'math', 'emoji', 'text', 'phone', 'visit', 'forward', 'follow_channel', 'react_post', 'vote_poll', 'subscribe_channel']
        steps = []
        for line in lines:
            if ':' in line:
                typ, val = line.split(':', 1)
                typ = typ.strip().lower()
                val = val.strip()
                if typ in valid_types:
                    if typ == 'text':
                        steps.append({'type': 'text', 'text_to_send': val})
                    elif typ == 'forward':
                        steps.append({'type': 'forward', 'target_link': val})
                    elif typ == 'react_post':
                        steps.append({'type': 'react_post', 'target_link': val})
                    elif typ == 'vote_poll':
                        steps.append({'type': 'vote_poll', 'target_link': val})
                    elif typ in ('follow_channel', 'subscribe', 'subscribe_channel'):
                        # v2.1.7: حفظ كقائمة قنوات (يمكن تكرار الخطوة لجمع عدة قنوات)
                        steps.append({'type': 'subscribe', 'channels': [val]})
                    elif typ == 'phone':
                        # دعم الصيغ الصريحة لمشاركة الرقم (v2.1.0)
                        if val.startswith('forward:'):
                            steps.append({'type': 'phone', 'phone_link': val.split('forward:', 1)[1], 'phone_mode': 'forward'})
                        elif val == 'button':
                            steps.append({'type': 'phone', 'phone_mode': 'button'})
                        elif val == 'direct':
                            steps.append({'type': 'phone', 'phone_mode': 'direct'})
                        elif val.startswith('http'):
                            steps.append({'type': 'phone', 'phone_link': val, 'phone_mode': 'forward'})
                        else:
                            steps.append({'type': 'phone', 'phone_mode': 'auto'})
                    else:
                        steps.append({'type': typ, 'target_text': val})
                else:
                    steps.append({'type': 'click', 'target_text': line})
            else:
                typ = line.strip().lower()
                if typ in valid_types:
                    steps.append({'type': typ})
                else:
                    await message.answer(f"⚠️ نوع خطوة غير معروف: {line} - تم تجاهلها")
                    continue

        if not steps:
            await message.answer("❌ لم يتم التعرف على أي خطوة صحيحة")
            return

        data = await state.get_data()
        bot_link = data.get('task_bot_link', '')
        accounts_count = data.get('accounts_count', 1)
        speed = data.get('task_speed', 'medium')

        task_data = {
            'target_bot_link': bot_link or 'unknown',
            'task_type': 'manual',
            'status': 'pending',
            'speed': speed,
            'composite_steps': json.dumps(steps, ensure_ascii=False),
            'required_accounts': accounts_count,
            'multi_account': True if accounts_count > 1 else False,
            'parent_task_id': None,
            'created_at': _utcnow().isoformat()
        }
        response = supabase.table('tasks_queue').insert(task_data).execute()
        task_id = response.data[0]['id'] if response.data else None

        if task_id:
            steps_summary = "\n".join([f"{i + 1}. {s.get('type')}" for i, s in enumerate(steps[:10])])
            await message.answer(
                f"✅ *تم إنشاء المهمة اليدوية!*\n\n"
                f"🆔 رقم المهمة: `{task_id}`\n"
                f"🔗 البوت: {bot_link}\n"
                f"📋 الخطوات: {len(steps)}\n"
                f"👤 الحسابات: {accounts_count}\n"
                f"⚡ السرعة: {speed}\n\n"
                f"تفاصيل الخطوات:\n{steps_summary}",
                parse_mode="Markdown"
            )
        else:
            await message.answer("❌ فشل في إنشاء المهمة")
        await state.clear()
    except Exception as e:
        logger.error(f"Error processing composite steps: {e}")
        await message.answer("❌ حدث خطأ في حفظ الخطوات")
        await state.clear()


@router.message(StateFilter(AdminStates.waiting_for_emoji))
async def process_emoji_input(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        emoji = message.text.strip()
        if not emoji:
            await message.answer("❌ أرسل إيموجي صحيح، مثال: 👍 أو random")
            return
        await state.update_data(emoji_target=emoji)
        await message.answer("📊 *عدد الحسابات*\n\nكم حساب تريد استخدامه؟\nأرسل رقماً: `5`", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_task_accounts_count)
    except Exception as e:
        logger.error(f"Error processing emoji: {e}")
        await message.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_vote_option))
async def process_vote_option_input(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        option = message.text.strip()
        if not option:
            await message.answer("❌ أرسل رقم الخيار أو اسمه")
            return
        await state.update_data(vote_option=option)
        await message.answer("📊 *عدد الحسابات*\n\nكم حساب تريد استخدامه؟\nأرسل رقماً: `5`", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_task_accounts_count)
    except Exception as e:
        logger.error(f"Error processing vote option: {e}")
        await message.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_channels_list))
async def process_channels_list_input(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        channels_text = message.text.strip()
        lines = [l.strip() for l in channels_text.split('\n') if l.strip()]
        cleaned = []
        for ch in lines:
            ch = ch.replace('https://t.me/', '').replace('@', '').split('/')[0].strip()
            if ch:
                cleaned.append(ch)
        if not cleaned:
            await message.answer("❌ أرسل قائمة قنوات صحيحة، مثال:\nhttps://t.me/channel1\n@channel2")
            return

        await state.update_data(channel_list=json.dumps(cleaned, ensure_ascii=False))
        if not data_has_task_mode(state):
            await state.update_data(task_mode='follow_channel')
        await message.answer("📊 *عدد الحسابات*\n\nكم حساب تريد استخدامه؟\nأرسل رقماً: `5`", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_task_accounts_count)
    except Exception as e:
        logger.error(f"Error processing channels list: {e}")
        await message.answer("❌ حدث خطأ")


def data_has_task_mode(state: FSMContext) -> bool:
    """فحص مؤقت: هل task_mode موجود في بيانات الحالة"""
    try:
        return bool(state._state_data and state._state_data.get('task_mode'))
    except Exception:
        return False


# ============================================
# PROXY MANAGEMENT (NEW)
# ============================================
@router.callback_query(F.data == "task_proxies")
async def proxy_management_menu(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text("🌐 *إدارة البروكسيات*\n\nاختر الإجراء:", reply_markup=Keyboards.proxy_management_menu(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in proxy menu: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "proxy_add")
async def proxy_add_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text(
            "➕ *إضافة بروكسي*\n\n"
            "أرسل بيانات البروكسي بالصيغة:\n"
            "`النوع|IP|Port|Username|Password|الحد_الأقصى`\n\n"
            "مثال:\n`socks5|192.168.1.1|8080|user|pass|5`\n\n"
            "أرسل `/cancel` للإلغاء",
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_proxy_data)
    except Exception as e:
        logger.error(f"Error in proxy_add_start: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_proxy_data))
async def proxy_add_process(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return

        parts = message.text.strip().split('|')
        if len(parts) < 4:
            await message.answer("❌ صيغة غير صحيحة\nاستخدم: النوع|IP|Port|Username|Password|الحد")
            return
        proxy_type = parts[0].strip() or 'socks5'
        host = parts[1].strip()
        try:
            port = int(parts[2].strip())
        except ValueError:
            await message.answer("❌ المنفذ يجب أن يكون رقماً")
            return
        username = parts[3].strip()
        password = parts[4].strip() if len(parts) > 4 else ''
        try:
            max_accounts = int(parts[5].strip()) if len(parts) > 5 else 5
        except ValueError:
            max_accounts = 5

        proxy_data = {
            'proxy_type': proxy_type, 'host': host, 'port': port,
            'username': username, 'password': password, 'max_accounts': max_accounts
        }
        result = await Database.add_proxy(proxy_data)
        if result:
            await message.answer(f"✅ *تم إضافة البروكسي!*\n\n🔗 {host}:{port}\n👤 {username}\n📊 الحد الأقصى: {max_accounts} حسابات", parse_mode="Markdown")
        else:
            await message.answer("❌ فشل في إضافة البروكسي")
        await state.clear()
    except Exception as e:
        logger.error(f"Error adding proxy: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.callback_query(F.data == "proxy_list")
async def proxy_list_show(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        proxies = await Database.get_proxy_list()
        if not proxies:
            await callback.answer("لا توجد بروكسيات", show_alert=True)
            return
        text = "📋 *قائمة البروكسيات:*\n\n"
        for p in proxies:
            status = "🟢" if p.get('is_active') else "🔴"
            text += f"{status} `{p['host']}:{p['port']}`\n  👤 {p.get('username', '-')} | 📊 {p.get('used_count', 0)}/{p.get('max_accounts', 5)}\n\n"
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 رجوع", callback_data="task_proxies")
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error listing proxies: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "proxy_delete")
async def proxy_delete_prompt(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        proxies = await Database.get_proxy_list()
        if not proxies:
            await callback.answer("لا توجد بروكسيات", show_alert=True)
            return
        builder = InlineKeyboardBuilder()
        for p in proxies:
            builder.button(text=f"🗑 {p['host']}:{p['port']}", callback_data=f"proxy_del_{p['id']}")
        builder.button(text="🔙 رجوع", callback_data="task_proxies")
        builder.adjust(1)
        await callback.message.edit_text("🗑 *حذف بروكسي*\n\nاختر البروكسي:", reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in proxy delete: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data.startswith("proxy_del_"))
async def proxy_delete_execute(callback: CallbackQuery):
    try:
        proxy_id = callback.data.replace("proxy_del_", "")
        await Database.delete_proxy(proxy_id)
        await callback.answer("✅ تم الحذف", show_alert=True)
        await proxy_list_show(callback)
    except Exception as e:
        logger.error(f"Error deleting proxy: {e}")
        await callback.answer("❌ حدث خطأ")


# ============================================
# ACCOUNT GROUPS MANAGEMENT
# ============================================
@router.callback_query(F.data == "task_groups")
async def groups_menu_show(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text("👥 *مجموعات الحسابات*\n\nاختر الإجراء:", reply_markup=Keyboards.groups_menu(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in groups menu: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "group_create")
async def group_create_start(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        await callback.message.edit_text("➕ *إنشاء مجموعة*\n\nأرسل اسم المجموعة:\nمثال: `حسابات ميانمار`\n\nأرسل `/cancel` للإلغاء", parse_mode="Markdown")
        await state.set_state(AdminStates.waiting_for_group_name)
    except Exception as e:
        logger.error(f"Error in group_create_start: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_group_name))
async def group_create_process(message: Message, state: FSMContext):
    try:
        if message.text == '/cancel':
            await state.clear()
            await message.answer("✅ تم الإلغاء")
            return
        group_name = message.text.strip()
        await state.update_data(group_name=group_name)
        await message.answer(
            "🌍 *نوع المجموعة*\n\nاختر النوع:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🇸🇾 عربية", callback_data="gtype_arabic"),
                 InlineKeyboardButton(text="🌍 أجنبية", callback_data="gtype_foreign")],
                [InlineKeyboardButton(text="📦 أخرى", callback_data="gtype_other")]
            ]),
            parse_mode="Markdown"
        )
        await state.set_state(AdminStates.waiting_for_group_type)
    except Exception as e:
        logger.error(f"Error in group_create_process: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


@router.callback_query(F.data.startswith("gtype_"))
async def group_type_process(callback: CallbackQuery, state: FSMContext):
    try:
        gtype = callback.data.replace("gtype_", "")
        data = await state.get_data()
        group_name = data.get('group_name', 'Unknown')
        result = await Database.create_account_group({
            'group_name': group_name, 'group_type': gtype,
            'description': f'مجموعة {group_name}'
        })
        if result:
            await callback.message.edit_text(f"✅ *تم إنشاء المجموعة!*\n\n📁 الاسم: {group_name}\n🌍 النوع: {gtype}", parse_mode="Markdown")
        else:
            await callback.answer("❌ فشل في إنشاء المجموعة", show_alert=True)
        await state.clear()
    except Exception as e:
        logger.error(f"Error in group_type_process: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "group_list")
async def group_list_show(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        groups = await Database.get_account_groups()
        if not groups:
            await callback.answer("لا توجد مجموعات", show_alert=True)
            return
        text = "📋 *المجموعات:*\n\n"
        for g in groups:
            emoji = "🇸🇾" if g['group_type'] == 'arabic' else "🌍" if g['group_type'] == 'foreign' else "📦"
            text += f"{emoji} {g['group_name']} `{g['group_type']}`\n"
        builder = InlineKeyboardBuilder()
        builder.button(text="🔙 رجوع", callback_data="task_groups")
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error listing groups: {e}")
        await callback.answer("❌ حدث خطأ")


# ============================================
# TASK TEMPLATES (LEARNED PATTERNS)
# ============================================
@router.callback_query(F.data == "task_templates")
async def templates_menu(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        templates = await Database.get_bot_templates()
        if not templates:
            await callback.answer("لا توجد قوالب محفوظة", show_alert=True)
            return
        text = "📁 *القوالب المحفوظة:*\n\n"
        for t in templates[:10]:
            last_used = (t.get('last_used_at') or '')[:10] if t.get('last_used_at') else '-'
            text += f"🤖 @{t['bot_username']}\n  ✅ {t.get('success_count', 0)} | ❌ {t.get('fail_count', 0)}\n  📅 {last_used}\n\n"
        builder = InlineKeyboardBuilder()
        builder.button(text="🗑 حذف الكل", callback_data="templates_clear")
        builder.button(text="🔙 رجوع", callback_data="admin_tasks")
        builder.adjust(1)
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in templates_menu: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "templates_clear")
async def templates_clear(callback: CallbackQuery):
    try:
        supabase.table('bot_templates').delete().neq('id', '00000000-0000-0000-0000-000000000000').execute()
        await callback.answer("✅ تم حذف جميع القوالب", show_alert=True)
        await admin_tasks_menu(callback)
    except Exception as e:
        logger.error(f"Error clearing templates: {e}")
        await callback.answer("❌ حدث خطأ")


# ============================================
# TASK LIST & REPORTS
# ============================================
@router.callback_query(F.data == "task_list")
async def task_list_show(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        tasks = supabase.table('tasks_queue').select('*').in_('status', ['pending', 'processing']).order('created_at', desc=True).limit(10).execute()
        if not tasks.data:
            await callback.answer("لا توجد مهام حالية", show_alert=True)
            return
        text = "📋 *المهام الحالية:*\n\n"
        for t in tasks.data:
            status_emoji = "⏳" if t['status'] == 'pending' else "🔄"
            created = (t.get('created_at') or '')[:10] or 'N/A'
            text += f"{status_emoji} `{t['id'][:8]}...`\n  🔗 {str(t.get('target_bot_link', '-'))[:30]}\n  📅 {created}\n\n"
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 تحديث", callback_data="task_list")
        builder.button(text="🗑 حذف المعلقة", callback_data="task_clear_pending")
        builder.button(text="🔙 رجوع", callback_data="admin_tasks")
        builder.adjust(1)
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in task_list: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "task_clear_pending")
async def task_clear_pending(callback: CallbackQuery):
    try:
        supabase.table('tasks_queue').delete().eq('status', 'pending').execute()
        await callback.answer("✅ تم حذف المهام المعلقة", show_alert=True)
        await task_list_show(callback)
    except Exception as e:
        logger.error(f"Error clearing pending tasks: {e}")
        await callback.answer("❌ حدث خطأ")


@router.callback_query(F.data == "task_reports")
async def task_reports_show(callback: CallbackQuery):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        completed = supabase.table('tasks_queue').select('id', count='exact').eq('status', 'completed').execute()
        failed = supabase.table('tasks_queue').select('id', count='exact').eq('status', 'failed').execute()
        pending = supabase.table('tasks_queue').select('id', count='exact').eq('status', 'pending').execute()
        total_completed = len(completed.data)
        total_failed = len(failed.data)
        total_pending = len(pending.data)
        total = total_completed + total_failed + total_pending
        success_rate = round((total_completed / total * 100), 1) if total > 0 else 0

        text = (
            f"📊 *تقارير المهام*\n\n"
            f"✅ مكتملة: {total_completed}\n"
            f"❌ فاشلة: {total_failed}\n"
            f"⏳ معلقة: {total_pending}\n"
            f"📈 نسبة النجاح: {success_rate}%\n\n"
            f"📅 التاريخ: {_utcnow().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 تحديث", callback_data="task_reports")
        builder.button(text="🔙 رجوع", callback_data="admin_tasks")
        builder.adjust(1)
        await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in task_reports: {e}")
        await callback.answer("❌ حدث خطأ")


# ============================================
# LEARNING RESPONSE HANDLER
# ============================================
@router.callback_query(F.data.startswith("learn_"))
async def learning_response_handler(callback: CallbackQuery, state: FSMContext):
    try:
        action = callback.data.replace("learn_", "")
        if action == "manual":
            await callback.message.edit_text("📝 *اشرح الخطوة*\n\nاكتب وصفاً للخطوة التي يجب تنفيذها:\nمثال: `اضغط على زر Star ثم تحقق`", parse_mode="Markdown")
            await state.set_state(AdminStates.waiting_for_learning_response)
        elif action == "skip":
            await callback.answer("⏭ تم التخطي", show_alert=True)
        else:
            await callback.answer(f"✅ تم التعلم: {action}", show_alert=True)
    except Exception as e:
        logger.error(f"Error in learning response: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(StateFilter(AdminStates.waiting_for_learning_response))
async def learning_manual_response(message: Message, state: FSMContext):
    try:
        response = message.text.strip()
        await message.answer(f"✅ *تم حفظ التعليمات:*\n{response}", parse_mode="Markdown")
        await state.clear()
    except Exception as e:
        logger.error(f"Error in learning manual: {e}")
        await message.answer("❌ حدث خطأ")
        await state.clear()


# ============================================
# CATCH-ALL HANDLERS
# ============================================
@router.message()
async def handle_text_message(message: Message, state: FSMContext):
    try:
        user = await Database.get_user(message.from_user.id)
        if user and user.get('is_banned'):
            await message.answer("❌ حسابك محظور من استخدام البوت")
            return

        maintenance = await Database.get_setting('bot_maintenance_mode') or 'false'
        if maintenance == 'true' and message.from_user.id not in ADMIN_IDS:
            await message.answer("🔧 *البوت في وضع الصيانة حالياً*\n\nيرجى المحاولة لاحقاً", parse_mode="Markdown")
            return

        current_state = await state.get_state()
        if current_state:
            return
        await message.answer("👋 *أهلاً بك!*\n\nاستخدم الأزرار أدناه للتنقل في البوت:", reply_markup=Keyboards.main_menu(), parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error handling text message: {e}")
        await message.answer("❌ حدث خطأ")


@router.callback_query()
async def handle_unknown_callback(callback: CallbackQuery):
    try:
        await callback.answer("⚠️ هذا الزر غير متاح حالياً", show_alert=True)
    except Exception as e:
        logger.error(f"Error handling unknown callback: {e}")


# ============================================
# ERROR HANDLER
# ============================================
@router.errors()
async def error_handler(update, exception):
    logger.error(f"Update {update} caused error: {exception}")
    try:
        if update.callback_query:
            await update.callback_query.answer("❌ حدث خطأ غير متوقع")
        elif update.message:
            await update.message.answer("❌ حدث خطأ غير متوقع، يرجى المحاولة مرة أخرى")
    except Exception:
        pass
    return True


# ============================================
# FALLBACK SYSTEM v3.0 (NEW)
# ============================================
@router.callback_query(F.data.startswith("fallback_"))
async def handle_fallback_callback(callback: CallbackQuery, state: FSMContext):
    try:
        if callback.from_user.id not in ADMIN_IDS:
            await callback.answer("❌ غير مصرح لك", show_alert=True)
            return
        data = callback.data.replace("fallback_", "")
        parts = data.rsplit("_", 1)
        if len(parts) == 2:
            option, req_id = parts
            supabase.table('fallback_requests').update({
                'status': 'answered',
                'admin_response': option,
                'answered_at': _utcnow().isoformat()
            }).eq('id', req_id).execute()
            await callback.answer(f"✅ تم الرد: {option}", show_alert=True)
            await callback.message.edit_text(callback.message.text + f"\n\n✅ *تم الرد:* `{option}`", parse_mode="Markdown")
        else:
            await callback.answer("❌ تنسيق غير صحيح", show_alert=True)
    except Exception as e:
        logger.error(f"Fallback callback error: {e}")
        await callback.answer("❌ حدث خطأ")


@router.message(Command("fallback_list"))
async def fallback_list_command(message: Message):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ غير مصرح لك")
            return
        resp = supabase.table('fallback_requests').select('*').eq('status', 'pending').order('created_at', desc=True).limit(10).execute()
        if not resp.data:
            await message.answer("✅ لا توجد طلبات fallback معلقة")
            return
        text = "🤖 *طلبات Fallback المعلقة:*\n\n"
        for req in resp.data:
            btns = json.loads(req.get('buttons', '[]'))
            btn_str = ", ".join([b.get('text', '') for b in btns[:3]])
            text += f"🆔 `{req['id'][:8]}` | @{req['bot_username']}\n📝 {str(req.get('message_text', ''))[:80]}...\n🔘 {btn_str}\n\n"
        await message.answer(text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Fallback list error: {e}")
        await message.answer("❌ حدث خطأ")


@router.message(Command("fallback_answer"))
async def fallback_answer_command(message: Message):
    try:
        if message.from_user.id not in ADMIN_IDS:
            await message.answer("❌ غير مصرح لك")
            return
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.answer("❌ استخدم: `/fallback_answer <request_id> <answer>`\nمثال: `/fallback_answer abc123 1`", parse_mode="Markdown")
            return
        req_id = parts[1]
        answer = parts[2]

        resp = supabase.table('fallback_requests').select('id').eq('id', req_id).execute()
        target_id = req_id
        if not resp.data:
            all_pending = supabase.table('fallback_requests').select('id').eq('status', 'pending').execute()
            for r in all_pending.data:
                if r['id'].startswith(req_id):
                    target_id = r['id']
                    break

        supabase.table('fallback_requests').update({
            'status': 'answered',
            'admin_response': answer,
            'answered_at': _utcnow().isoformat()
        }).eq('id', target_id).execute()
        await message.answer(f"✅ تم الرد على الطلب `{target_id[:8]}` بـ: `{answer}`", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Fallback answer error: {e}")
        await message.answer("❌ حدث خطأ")


async def fallback_polling_task():
    """مهمة خلفية تراقب طلبات fallback الجديدة وترسل للآدمن"""
    await asyncio.sleep(10)
    last_notified = set()
    while True:
        try:
            resp = supabase.table('fallback_requests').select('*').eq('status', 'pending').order('created_at', desc=True).limit(5).execute()
            for req in resp.data or []:
                if req['id'] not in last_notified:
                    try:
                        bot_username = req.get('bot_username', 'unknown')
                        msg_text = req.get('message_text', '')
                        buttons = json.loads(req.get('buttons', '[]'))
                        btn_lines = ""
                        for i, b in enumerate(buttons, 1):
                            btn_lines += f"   [{i}] {b.get('text', '')} ({b.get('type', '')})\n"
                        if not btn_lines:
                            btn_lines = "   لا توجد أزرار\n"
                        notify = (
                            f"🤖 *البوت يحتاج مساعدتك*\n\n"
                            f"📍 *البوت:* @{bot_username}\n\n"
                            f"📝 *الرسالة:* \"{str(msg_text)[:400]}\"\n\n"
                            f"🔘 *الأزرار المتاحة:*\n{btn_lines}\n"
                            f"❓ *ماذا أفعل؟*\n"
                            f"🆔 الطلب: `{req['id']}`\n\n"
                            f"💡 رد بـ: `/fallback_answer {req['id'][:8]} 1` أو رقم الخيار"
                        )
                        from aiogram.utils.keyboard import InlineKeyboardBuilder as Builder2
                        builder = Builder2()
                        for i, b in enumerate(buttons[:4], 1):
                            builder.button(text=f"{i}: {str(b.get('text', ''))[:15]}", callback_data=f"fallback_{i}_{req['id']}")
                        builder.button(text="❌ تخطي", callback_data=f"fallback_skip_{req['id']}")
                        builder.adjust(2)
                        await bot.send_message(ADMIN_GROUP_ID, notify, reply_markup=builder.as_markup(), parse_mode="Markdown")
                        last_notified.add(req['id'])
                    except Exception as e:
                        logger.debug(f"Fallback notify error: {e}")
            if len(last_notified) > 100:
                last_notified.clear()
        except Exception as e:
            logger.debug(f"Fallback polling error: {e}")
        await asyncio.sleep(15)


# ============================================
# MAIN FUNCTION
# ============================================
async def main():
    logger.info("Starting bot...")

    # Initialize database connection check
    try:
        test_response = supabase.table('settings').select('key').limit(1).execute()
        logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        sys.exit(1)

    # Load settings into cache
    try:
        global SESSION_DURATION
        duration = await Database.get_setting('session_duration_minutes')
        if duration:
            SESSION_DURATION = int(duration)
        logger.info(f"Session duration: {SESSION_DURATION} minutes")
    except Exception as e:
        logger.warning(f"Could not load settings: {e}")

    # تشغيل مهام الخلفية v3.0
    asyncio.create_task(fallback_polling_task())
    logger.info("Fallback polling started")

    # تشغيل خادم وهمي على منفذ 10000 (للاستضافة على Railway/Render)
    dummy_app = web.Application()
    async def handle_health(request):
        return web.Response(text="OK")
    dummy_app.router.add_get('/', handle_health)

    runner = web.AppRunner(dummy_app)
    await runner.setup()
    port = int(os.getenv('PORT', '10000'))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Health server started on port {port}")

    # Start bot
    try:
        logger.info("Bot polling started...")
        await dp.start_polling(bot, skip_updates=True)
    except Exception as e:
        logger.error(f"Bot polling error: {e}")
    finally:
        await bot.session.close()
        await runner.cleanup()  # FIXED v2.0.1: إغلاق الخادم
        logger.info("Bot session closed")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
