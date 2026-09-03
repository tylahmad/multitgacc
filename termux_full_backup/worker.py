#!/usr/bin/env python3
"""
========================================================================
 Worker Engine v2.3.3 (Professional) - Termux Optimized
 Developer: Ahmed & DeepSeek
 Purpose: Task Automation & Learning Engine
========================================================================
 CHANGELOG v2.3.3 (Professional):
  1. [FIX] PGRST100: is_('col', None) -> is_('col', 'null') في جميع المواضع
  2. [FIX] مهام الحساب الواحد كانت تعلق في status='processing' للأبد
  3. [FIX] _is_already_completed كانت تتخطى المهام المتكررة لنفس البوت
  4. [FIX] عدم تطابق توقيع ai_agent.decide() - دعم توقيعين تلقائياً
  5. [FIX] سباق البروكسيات (used_count) - تحديث ذري + أقفال asyncio
  6. [FIX] إعادة المحاولة (retry) كانت وهمية: المهام تفشل مرة وتتوقف
  7. [FIX] المهام العالقة (retry>=3 & pending) - منظف تلقائي
  8. [FIX] active_sessions لم يكن يمتلئ أبداً - إدارة ذاكرة حقيقية
  9. [FIX] worker.log بلا حدود - RotatingFileHandler (2MB x 3)
 10. [FIX] upsert بدون on_conflict كان سيفشل على تعارض المفاتيح
 11. [FIX] record_completion: insert ثم fallback إلى update (منع التكرار)
 12. [FIX] analyze_and_learn كان يقلب نجاح المهمة إلى فشل عند أي خطأ
 13. [FIX] مسار fallback الذكي كان يستدعي self.ai_decision بدون فحص None
 14. [FIX] أنواع المهام غير المعروفة: تفويض للحلقة الذكية بدل فشل فوري
 15. [FIX] استدعاءات تحليل AI محمية بـ getattr ضد حقول مفقودة
 16. [FIX] إحصائيات tasks_failed كانت لا تتحدث أبداً
 17. [FIX] retry على أخطاء الشبكة العابرة في async_supabase_query
 18. [FIX] جلسات بدون session_string تستبعد من التوزيع (منع KeyError)
 19. [FIX] خطوات المهام اليدوية: دعم start/text/forward/react_post/vote_poll/follow_channel
 20. [FIX] follow_channel يستخدم channel_list (دعم 1-15 قناة) بدل سلسلة JSON واحدة
 21. [FIX] إجابة صفر (0) في المعادلات لم تعد تُعتبر فشلاً
 22. [FIX] الشرط المكرر في خطوة اللغة
 23. [FIX] خطوة check محسّنة: تنتظر وصول رسالة البوت (4 محاولات) وتسجل النص والأزرار في السجل
 24. [FIX] خطوة check: كلمات بحث أوسع (عربي/إنجليزي/إيموجي) + ضغط أفضل زر كاحتياط
========================================================================
"""

import asyncio
import logging
import logging.handlers
import os
import sys
import random
import re
import json
import gc
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

from telethon import TelegramClient, events, functions, types
from telethon.errors import (
    FloodWaitError, UserDeactivatedError, AuthKeyError,
    PhoneNumberBannedError, SessionPasswordNeededError,
    UserAlreadyParticipantError, ChatWriteForbiddenError,
    PeerFloodError, UserBannedInChannelError
)
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.sessions import StringSession

from dotenv import load_dotenv
from supabase import create_client, Client

# v3.0 AI Agent imports
try:
    from ai_agent import MessageAnalyzer, DecisionEngine, TemplateLearner as AITemplateLearner, ActionExecutor, FallbackManager, ReportGenerator
    AI_AVAILABLE = True
except ImportError as e:
    print(f"AI Agent not available: {e}")
    AI_AVAILABLE = False
    MessageAnalyzer = None
    DecisionEngine = None
    AITemplateLearner = None
    ActionExecutor = None
    FallbackManager = None
    ReportGenerator = None

load_dotenv()

# ============================================
# LOGGING (مع تدوير تلقائي لملف السجل)
# ============================================
LOG_MAX_BYTES = 2 * 1024 * 1024   # 2MB
LOG_BACKUP_COUNT = 3

_log_handlers = [logging.StreamHandler(sys.stdout)]
try:
    _log_handlers.append(
        logging.handlers.RotatingFileHandler(
            'worker.log',
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
    )
except Exception as e:
    print(f"Log file handler disabled: {e}")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=_log_handlers
)
logger = logging.getLogger('WorkerEngine')

# ============================================
# CONFIGURATION
# ============================================
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_GROUP_ID = int(os.getenv('ADMIN_GROUP_ID', 0))

MAX_RETRIES = 3          # أقصى عدد محاولات للمهمة قبل الفشل النهائي
STUCK_TASK_SWEEP = True  # تنظيف المهام العالقة تلقائياً

if not SUPABASE_URL or not SUPABASE_KEY:
    logger.error("Missing Supabase configuration")
    sys.exit(1)

if not API_ID or not API_HASH:
    logger.error("Missing Telegram API credentials")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _is_transient_error(exc: Exception) -> bool:
    """هل الخطأ عابر (شبكة/مهلة/SSL) ويستحق إعادة المحاولة؟"""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    markers = (
        'connection', 'connecterror', 'timeout', 'timedout', 'timed out',
        'networkerror', 'readtimeout', 'writetimeout', 'resets',
        'econnrefused', 'dnserror', 'handshake', 'ssl', 'eof',
        'remote disconnected', 'connection reset', 'temporary failure'
    )
    return any(m in name or m in msg for m in markers)


async def async_supabase_query(query_func, *args, _retries: int = 3, **kwargs):
    """تشغيل استعلامات Supabase بشكل غير متزامن مع إعادة محاولة للأخطاء العابرة"""
    last_exc: Optional[Exception] = None
    for attempt in range(_retries + 1):
        try:
            return await asyncio.to_thread(lambda: query_func(*args, **kwargs))
        except Exception as e:
            last_exc = e
            if attempt < _retries and _is_transient_error(e):
                backoff = 1.0 * (attempt + 1)
                logger.warning(f"Supabase transient error ({str(e)[:80]}); retry {attempt + 1}/{_retries} in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                continue
            raise
    raise last_exc  # pragma: no cover


async def ai_decide(decision_engine, analysis, bot_username: str,
                    step_history: Optional[List[Dict[str, Any]]] = None,
                    template: Optional[Dict[str, Any]] = None):
    """استدعاء decide() مع دعم تواقيع مختلفة لملف ai_agent (إصدارات قديمة/جديدة).
    الإصدار الجديد: decide(analysis, bot, history, template)
    الإصدار القديم: decide(analysis, bot)
    """
    if decision_engine is None or analysis is None:
        return None
    try:
        return await decision_engine.decide(analysis, bot_username, step_history or [], template)
    except TypeError:
        try:
            return await decision_engine.decide(analysis, bot_username)
        except Exception as e:
            logger.debug(f"ai_decide (2-arg) error: {e}")
            return None
    except Exception as e:
        logger.debug(f"ai_decide error: {e}")
        return None


async def record_completion(session_id: str, bot_username: str, task_type: str,
                            parent_task_id: Optional[str] = None):
    """تسجيل إكمال مهمة - insert مع fallback إلى update عند تعارض المفاتيح."""
    data: Dict[str, Any] = {
        'session_id': session_id,
        'bot_username': bot_username,
        'task_type': task_type,
        'completed_at': datetime.now(timezone.utc).isoformat()
    }
    if parent_task_id:
        data['parent_task_id'] = parent_task_id

    try:
        await async_supabase_query(
            lambda: supabase.table('completed_tasks_history').insert(data).execute()
        )
    except Exception:
        # تعارض (السجل موجود): حدّث بدل الإدراج
        try:
            q = supabase.table('completed_tasks_history').update(data) \
                .eq('session_id', session_id).eq('bot_username', bot_username) \
                .eq('task_type', task_type)
            if parent_task_id:
                q = q.eq('parent_task_id', parent_task_id)
            else:
                q = q.is_('parent_task_id', 'null')
            await async_supabase_query(lambda: q.execute())
        except Exception as e:
            logger.debug(f"record_completion fallback error: {e}")


# ============================================
# MEMORY MANAGER (محسن لـ Termux)
# ============================================
class MemoryManager:
    """Intelligent memory management for Termux/limited environments"""

    def __init__(self, max_memory_mb: int = 250):
        self.max_memory_mb = max_memory_mb
        self.cleanup_threshold = 0.85
        self.last_cleanup = datetime.now(timezone.utc)
        self._memory_warning_sent = False

    def get_current_usage_mb(self) -> float:
        """الحصول على استخدام الذاكرة الحالي من /proc/self/status"""
        try:
            with open('/proc/self/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        kb = int(line.split()[1])
                        return kb / 1024.0
        except Exception:
            pass

        # محاولة استخدام /proc/self/statm كبديل
        try:
            with open('/proc/self/statm', 'r') as f:
                fields = f.read().split()
                if len(fields) >= 2:
                    pages = int(fields[1])
                    page_size = os.sysconf(os.sysconf_names['SC_PAGE_SIZE'])
                    return (pages * page_size) / (1024 * 1024)
        except Exception:
            pass

        return 100.0

    def should_cleanup(self) -> bool:
        current = self.get_current_usage_mb()
        needs_cleanup = current > self.max_memory_mb * self.cleanup_threshold

        if needs_cleanup and not self._memory_warning_sent:
            logger.warning(f"Memory usage high: {current:.1f}MB / {self.max_memory_mb}MB")
            self._memory_warning_sent = True
        elif not needs_cleanup:
            self._memory_warning_sent = False

        return needs_cleanup

    async def cleanup(self, active_sessions: Dict[str, Any] = None):
        if not self.should_cleanup():
            return

        logger.info(f"Memory cleanup triggered: {self.get_current_usage_mb():.1f}MB")

        # تشغيل garbage collector بشكل صريح
        collected = gc.collect()
        logger.debug(f"GC collected {collected} objects")

        if active_sessions:
            idle_sessions = []
            for sid, session_data in active_sessions.items():
                if isinstance(session_data, dict) and not session_data.get('is_active', False):
                    idle_sessions.append(sid)
                elif hasattr(session_data, 'is_active') and not session_data.is_active:
                    idle_sessions.append(sid)

            for sid in idle_sessions:
                try:
                    if isinstance(active_sessions[sid], dict):
                        if 'client' in active_sessions[sid] and active_sessions[sid]['client']:
                            await active_sessions[sid]['client'].disconnect()
                    elif hasattr(active_sessions[sid], 'client') and active_sessions[sid].client:
                        await active_sessions[sid].client.disconnect()

                    del active_sessions[sid]
                    logger.debug(f"Removed idle session: {sid[:8]}...")
                except Exception as e:
                    logger.debug(f"Error removing session {sid[:8]}: {e}")

        collected = gc.collect()

        self.last_cleanup = datetime.now(timezone.utc)
        logger.info(f"Memory after cleanup: {self.get_current_usage_mb():.1f}MB (GC freed {collected})")

    async def sleep_session(self, session_data: Dict[str, Any]):
        """وضع جلسة في وضع السكون لتوفير الذاكرة"""
        session_data['is_active'] = False
        session_data['sleep_since'] = datetime.now(timezone.utc)

        if 'client' in session_data and session_data['client']:
            try:
                await session_data['client'].disconnect()
            except Exception:
                pass

        session_data['client'] = None
        gc.collect()
        logger.debug(f"Session put to sleep: {session_data.get('phone', 'unknown')}")


# ============================================
# PROXY POOL MANAGER (محسن - خالٍ من السباقات)
# ============================================
class ProxyPoolManager:
    """Advanced proxy management with auto-distribution.
    الإصلاح: تحديث used_count ذري (شرط lt في نفس UPDATE)
    + قفل asyncio لمنع سباق داخل نفس العملية.
    """

    def __init__(self):
        self.proxy_cache = {}
        self.last_refresh = None
        self._assign_lock = asyncio.Lock()
        self._release_lock = asyncio.Lock()

    async def get_all_proxies(self) -> List[Dict[str, Any]]:
        """الحصول على جميع البروكسيات النشطة"""
        try:
            response = await async_supabase_query(
                lambda: supabase.table('proxy_list').select('*').eq('is_active', True).execute()
            )
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching proxies: {e}")
            return []

    async def assign_proxy_for_session(self, session_id: str, phone: str) -> Optional[Dict[str, Any]]:
        """تخصيص بروكسي لجلسة - تخصيص ذري يمنع تجاوز max_accounts"""
        async with self._assign_lock:
            try:
                proxies = await self.get_all_proxies()
                if not proxies:
                    return None

                available = sorted(proxies, key=lambda p: p.get('used_count', 0))

                for proxy in available:
                    max_accounts = proxy.get('max_accounts', 5)
                    if proxy.get('used_count', 0) >= max_accounts:
                        continue

                    # تحديث ذري: لن ينجح إلا إذا كان الاستخدام ما زال تحت الحد
                    updated = await async_supabase_query(
                        lambda p=proxy: supabase.table('proxy_list').update({
                            'used_count': p['used_count'] + 1,
                            'last_used_at': datetime.now(timezone.utc).isoformat()
                        }).eq('id', p['id']).lt('used_count', max_accounts).execute()
                    )
                    if not updated.data:
                        # سباق: ووركر آخر أخذ البروكسي قبلي - جرب التالي
                        continue

                    await async_supabase_query(
                        lambda: supabase.table('client_sessions').update({
                            'proxy_id': proxy['id']
                        }).eq('id', session_id).execute()
                    )

                    logger.info(f"Proxy {proxy['host']}:{proxy['port']} assigned to {phone}")

                    return {
                        'proxy_type': proxy.get('proxy_type', 'socks5'),
                        'addr': proxy['host'],
                        'port': proxy['port'],
                        'username': proxy.get('username'),
                        'password': proxy.get('password'),
                        'rdns': True
                    }

                logger.warning(f"No available proxy for {phone}")
                return None

            except Exception as e:
                logger.error(f"Error assigning proxy: {e}")
                return None

    async def release_proxy(self, session_id: str):
        """تحرير بروكسي من جلسة - آمن ضد التحرير المزدوج"""
        async with self._release_lock:
            try:
                response = await async_supabase_query(
                    lambda: supabase.table('client_sessions').select('proxy_id').eq('id', session_id).execute()
                )
                if not (response.data and response.data[0].get('proxy_id')):
                    return  # لا بروكسي معين أصلاً

                proxy_id = response.data[0]['proxy_id']

                # صفّر البروكسي أولاً حتى لا يتكرر التحرير لاحقاً
                await async_supabase_query(
                    lambda: supabase.table('client_sessions').update({
                        'proxy_id': None
                    }).eq('id', session_id).execute()
                )

                proxy_response = await async_supabase_query(
                    lambda: supabase.table('proxy_list').select('used_count').eq('id', proxy_id).execute()
                )
                if proxy_response.data:
                    new_count = max(proxy_response.data[0].get('used_count', 1) - 1, 0)
                    await async_supabase_query(
                        lambda: supabase.table('proxy_list').update({
                            'used_count': new_count
                        }).eq('id', proxy_id).execute()
                    )

                logger.info(f"Proxy released for session {session_id[:8]}...")
            except Exception as e:
                logger.error(f"Error releasing proxy: {e}")


# ============================================
# TEMPLATE LEARNING ENGINE (محسن)
# ============================================
class TemplateLearningEngine:
    """Learns bot interaction patterns and predicts actions"""

    def __init__(self):
        self.template_cache = {}

    async def find_template(self, bot_username: str) -> Optional[Dict[str, Any]]:
        """البحث عن قالب محفوظ لبوت معين"""
        if bot_username in self.template_cache:
            return self.template_cache[bot_username]

        try:
            response = await async_supabase_query(
                lambda: supabase.table('bot_templates').select('*').eq('bot_username', bot_username).execute()
            )
            if response.data:
                self.template_cache[bot_username] = response.data[0]
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Error finding template: {e}")
            return None

    async def save_template(self, bot_username: str, steps: List[Dict[str, Any]]):
        """حفظ قالب تفاعل جديد"""
        try:
            existing = await self.find_template(bot_username)
            now = datetime.now(timezone.utc).isoformat()

            if existing:
                await async_supabase_query(
                    lambda: supabase.table('bot_templates').update({
                        'steps': json.dumps(steps),
                        'total_steps': len(steps),
                        'success_count': existing.get('success_count', 0) + 1,
                        'last_used_at': now,
                        'updated_at': now
                    }).eq('id', existing['id']).execute()
                )
            else:
                await async_supabase_query(
                    lambda: supabase.table('bot_templates').insert({
                        'bot_username': bot_username,
                        'template_name': f'Auto-learned: {bot_username}',
                        'steps': json.dumps(steps),
                        'total_steps': len(steps),
                        'success_count': 1,
                        'created_at': now,
                        'updated_at': now
                    }).execute()
                )

            # حفظ كامل الصف (مع id) في الكاش لمنع KeyError عند التحديث
            try:
                resp_insert = await async_supabase_query(
                    lambda: supabase.table('bot_templates').select('*').eq('bot_username', bot_username).execute()
                )
                if resp_insert.data:
                    self.template_cache[bot_username] = resp_insert.data[0]
                else:
                    self.template_cache[bot_username] = {
                        'bot_username': bot_username,
                        'steps': json.dumps(steps),
                        'id': existing['id'] if existing and existing.get('id') else None
                    }
            except Exception:
                self.template_cache[bot_username] = {
                    'bot_username': bot_username,
                    'steps': json.dumps(steps),
                    'id': existing['id'] if existing and existing.get('id') else None
                }

            logger.info(f"Template saved for {bot_username}: {len(steps)} steps")
        except Exception as e:
            logger.error(f"Error saving template: {e}")

    async def predict_next_action(self, bot_username: str, current_step: int, message_text: str, buttons: List[str]) -> Optional[str]:
        """توقع الإجراء التالي بناءً على القالب المحفوظ"""
        try:
            template = await self.find_template(bot_username)
            if not template:
                return None

            steps = json.loads(template.get('steps', '[]'))
            if current_step < len(steps):
                predicted_step = steps[current_step]
                step_type = predicted_step.get('type', 'click')

                if step_type == 'click':
                    target_text = predicted_step.get('target_text', '').lower()
                    for button in buttons:
                        if target_text in button.lower():
                            logger.info(f"Predicted click: {button} (matched '{target_text}')")
                            return button

                elif step_type == 'solve_math':
                    return 'solve_math'

                elif step_type == 'match_emoji':
                    return 'match_emoji'

                elif step_type == 'send_text':
                    return predicted_step.get('text_to_send', '')

            return None
        except Exception as e:
            logger.error(f"Error predicting action: {e}")
            return None

    async def analyze_and_learn(self, bot_username: str, message_history: List[Dict[str, Any]]):
        """تحليل سجل التفاعل وتعلم الأنماط"""
        try:
            steps = []
            for msg in message_history:
                step_type = msg.get('step_type', 'click')
                step_data = {'type': step_type}

                if step_type == 'click':
                    step_data['target_text'] = msg.get('clicked_button', '')
                elif step_type == 'solve_math':
                    step_data['target_text'] = 'math'
                elif step_type == 'match_emoji':
                    step_data['target_text'] = 'emoji'
                elif step_type == 'send_text':
                    step_data['text_to_send'] = msg.get('sent_text', '')

                steps.append(step_data)

            await self.save_template(bot_username, steps)
            logger.info(f"Learned {len(steps)} steps for {bot_username}")
        except Exception as e:
            logger.error(f"Error analyzing and learning: {e}")


# ============================================
# SMART TASK PARSER (محسن)
# ============================================
class SmartTaskParser:
    """Advanced parser for bot interactions"""

    @staticmethod
    def solve_math_expression(text: str) -> Optional[int]:
        """حل المعادلات الرياضية في رسائل البوت"""
        try:
            # أنماط متعددة للمعادلات الرياضية
            patterns = [
                r'(\d+)\s*\+\s*(\d+)\s*=\s*\?',
                r'(\d+)\s*\-\s*(\d+)\s*=\s*\?',
                r'(\d+)\s*\*\s*(\d+)\s*=\s*\?',
                r'(\d+)\s*\+\s*(\d+)',
                r'(\d+)\s*\-\s*(\d+)',
                r'(\d+)\s*\*\s*(\d+)',
                r'solve:?\s*(\d+)\s*\+\s*(\d+)',
                r'solve:?\s*(\d+)\s*\-\s*(\d+)',
                r'(\d+)\s*[\+\-\*]\s*(\d+)',
            ]

            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    num1 = int(match.group(1))
                    num2 = int(match.group(2))
                    full_match = match.group()

                    if '+' in full_match:
                        return num1 + num2
                    elif '-' in full_match:
                        return num1 - num2
                    elif '*' in full_match:
                        return num1 * num2

            return None
        except Exception as e:
            logger.error(f"Error solving math: {e}")
            return None

    @staticmethod
    def solve_emoji_challenge(message) -> Optional[str]:
        """حل تحديات الإيموجي"""
        try:
            if not message.reply_markup:
                return None

            emoji_pattern = re.compile(
                r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
                r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
                r'\u2600-\u26FF\u2700-\u27BF]'
            )

            if hasattr(message.reply_markup, 'rows'):
                emoji_buttons = []
                for row in message.reply_markup.rows:
                    for button in row.buttons:
                        if button.text:
                            emoji_count = len(emoji_pattern.findall(button.text))
                            if emoji_count > 0:
                                emoji_buttons.append((button, emoji_count))

                if message.text:
                    message_emojis = emoji_pattern.findall(message.text)
                    if message_emojis:
                        target_emoji = message_emojis[0]
                        for button, _ in emoji_buttons:
                            if target_emoji in button.text:
                                return button.text

            return None
        except Exception as e:
            logger.error(f"Error solving emoji: {e}")
            return None

    @staticmethod
    def extract_buttons(message) -> List[str]:
        """استخراج أزرار لوحة المفاتيح من رسالة"""
        buttons = []
        try:
            if message.reply_markup and hasattr(message.reply_markup, 'rows'):
                for row in message.reply_markup.rows:
                    for button in row.buttons:
                        if button.text:
                            buttons.append(button.text)
        except Exception:
            pass
        return buttons

    @staticmethod
    def guess_best_action(buttons: List[str], message_text: str = "") -> Optional[str]:
        """تخمين أفضل زر للنقر عليه"""
        # كلمات ذات أولوية عالية
        priority_keywords = [
            'english', 'english', 'english',  # تكرار لزيادة الأولوية
            'start', 'start', 'start',
            'earn', 'earn',
            'join', 'join',
            'subscribe', 'subscribe',
            'check', 'verify', 'confirm',
            'continue', 'next', 'ok', 'yes',
            'super', 'boost', 'claim', 'get',
            'begin', 'begin'
        ]

        # البحث حسب الأولوية
        for keyword in priority_keywords:
            for button in buttons:
                if keyword in button.lower():
                    return button

        # تجنب أزرار معينة
        avoid_keywords = ['cancel', 'no', 'skip', 'exit', 'back', 'help', 'about']

        for button in buttons:
            if not any(avoid in button.lower() for avoid in avoid_keywords):
                return button

        return buttons[0] if buttons else None


# ============================================
# COMPOSITE TASK EXECUTOR (محسن)
# ============================================
class CompositeTaskExecutor:
    """Executes complex multi-step tasks"""

    def __init__(self, client: TelegramClient, template_engine: TemplateLearningEngine, bot_entity, task: Dict[str, Any]):
        self.client = client
        self.template_engine = template_engine
        self.parser = SmartTaskParser()
        self.step_history = []
        self.bot_entity = bot_entity  # الكيان الصحيح للبوت
        self.task = task

    async def execute_composite_task(self, session_id: str, bot_username: str) -> bool:
        """تنفيذ مهمة مركبة - v3.0 AI Smart + Manual"""
        try:
            self.step_history = []
            steps = json.loads(self.task.get('composite_steps', '[]') or '[]')
            speed = self.task.get('speed', 'medium')

            # v3.0: إذا كانت smart ومافي خطوات، استخدم AI loop
            if not steps and self.task.get('task_type') in ['composite', 'smart']:
                return await self._execute_smart_ai_loop(session_id, bot_username, speed)

            speed_delays = {
                'slow': (3, 7),
                'medium': (1.5, 4),
                'fast': (0.5, 2)
            }
            min_delay, max_delay = speed_delays.get(speed, (1.5, 4))

            # استخراج ref_id من الرابط
            ref_id = None
            target_link = self.task.get('target_bot_link', '')
            if '?start=' in target_link:
                ref_id = target_link.split('?start=')[-1]

            # Step 1: إرسال /start مع ref إذا وجد
            try:
                if ref_id:
                    await self.client.send_message(self.bot_entity, f'/start {ref_id}')
                    self.step_history.append({'step_type': 'send', 'sent_text': f'/start {ref_id}'})
                else:
                    await self.client.send_message(self.bot_entity, '/start')
                    self.step_history.append({'step_type': 'send', 'sent_text': '/start'})

                await asyncio.sleep(random.uniform(min_delay, max_delay))
            except FloodWaitError as e:
                logger.warning(f"FloodWait on start: {e.seconds}s")
                await asyncio.sleep(min(e.seconds, 60))
                return False
            except Exception as e:
                logger.error(f"Error sending start: {e}")
                return False

            # Step 2: معالجة الخطوات المتبقية
            for step_idx, step in enumerate(steps if steps else []):
                step_type = step.get('type', 'click')

                try:
                    if step_type == 'start':
                        success = await self._handle_start_step(ref_id, min_delay, max_delay)
                    elif step_type == 'language':
                        success = await self._handle_language_step(min_delay, max_delay)
                    elif step_type in ('subscribe', 'follow_channel', 'subscribe_channel'):
                        channels = step.get('channels', [])
                        if isinstance(channels, str):
                            channels = [channels]
                        success = await self._handle_subscribe_step(channels, min_delay, max_delay)
                    elif step_type == 'check':
                        success = await self._handle_check_step(min_delay, max_delay)
                    elif step_type == 'math':
                        success = await self._handle_math_step(min_delay, max_delay)
                    elif step_type == 'emoji':
                        success = await self._handle_emoji_step(min_delay, max_delay)
                    elif step_type == 'phone':
                        phone_link = step.get('phone_link', '')
                        phone_mode = step.get('phone_mode', 'auto')
                        success = await self._handle_phone_step(phone_link, min_delay, max_delay, phone_mode)
                    elif step_type == 'visit':
                        success = await self._handle_visit_step(min_delay, max_delay)
                    elif step_type == 'text':
                        success = await self._handle_text_step(step.get('text_to_send', ''), min_delay, max_delay)
                    elif step_type == 'forward':
                        success = await self._handle_forward_step(step.get('target_link', ''), min_delay, max_delay)
                    elif step_type == 'react_post':
                        success = await self._handle_react_step(step.get('target_link', ''), step.get('emoji', '👍'))
                    elif step_type == 'vote_poll':
                        success = await self._handle_vote_step(step.get('target_link', ''), step.get('option', '0'))
                    else:
                        success = await self._handle_click_step(step.get('target_text', ''), min_delay, max_delay)

                    if not success:
                        logger.warning(f"Step {step_idx} ({step_type}) failed for {bot_username}")
                        return False

                except FloodWaitError as e:
                    logger.warning(f"FloodWait on step {step_idx}: {e.seconds}s")
                    await asyncio.sleep(min(e.seconds, 60))
                    return False
                except Exception as e:
                    logger.error(f"Error on step {step_idx}: {e}")
                    return False

                await asyncio.sleep(random.uniform(min_delay, max_delay))

            # تعليم المهمة كمكتملة
            await record_completion(session_id, bot_username, 'composite',
                                    self.task.get('parent_task_id'))

            # التعلم من التنفيذ الناجح - لا يجب أن يقلب نجاح المهمة إلى فشل
            try:
                await self.template_engine.analyze_and_learn(bot_username, self.step_history)
            except Exception as e:
                logger.debug(f"Template learning error (non-fatal): {e}")

            return True

        except Exception as e:
            logger.error(f"Error executing composite task: {e}")
            return False

    async def execute_smart_task(self, session_id: str, bot_username: str, speed: str = "medium") -> bool:
        """واجهة عامة للحلقة الذكية (للمهام غير المعروفة أو الذكية)"""
        return await self._execute_smart_ai_loop(session_id, bot_username, speed)

    async def _get_recent_messages(self, limit: int = 5):
        """الحصول على الرسائل الحديثة من البوت - الواردة فقط (v2.0.4)"""
        try:
            messages = await self.client.get_messages(self.bot_entity, limit=limit)
            # تجاهل رسائلنا الصادرة - نريد ردود البوت (التي تحتوي الأزرار)
            incoming = [m for m in messages if not getattr(m, 'out', False)]
            return incoming
        except Exception:
            return []

    async def _handle_language_step(self, min_delay: float, max_delay: float) -> bool:
        """معالجة خطوة اختيار اللغة"""
        try:
            messages = await self._get_recent_messages(3)
            for msg in messages:
                buttons = self.parser.extract_buttons(msg)
                for button in buttons:
                    if 'english' in button.lower():
                        await msg.click(text=button)
                        self.step_history.append({'step_type': 'click', 'clicked_button': button})
                        await asyncio.sleep(random.uniform(min_delay, max_delay))
                        return True

            # إذا لم يجد زر English، جرب أي زر أول
            for msg in messages:
                buttons = self.parser.extract_buttons(msg)
                if buttons:
                    await msg.click(text=buttons[0])
                    self.step_history.append({'step_type': 'click', 'clicked_button': buttons[0]})
                    return True

            return False
        except Exception:
            return False

    async def _handle_subscribe_step(self, channels: List[str], min_delay: float, max_delay: float) -> bool:
        """معالجة خطوة الاشتراك - v2.0.7: ذكية، تنتظر رد البوت، تنضم وتتحقق"""
        try:
            logger.info(f"SUBSCRIBE_STEP: channels={channels} | auto mode (waits for bot reply)")
            joined_any = False
            pressed_any = False

            # 0) أرسل /start لتحفيز البوت على إرسال رسالة الاشتراك
            try:
                await self.client.send_message(self.bot_entity, '/start')
                await asyncio.sleep(random.uniform(2, 3))
                logger.info("SUBSCRIBE_STEP: sent /start to trigger bot")
            except Exception as e:
                logger.debug(f"SUBSCRIBE_STEP: send /start error: {e}")

            # 1) الانضمام للقنوات المحددة في المهمة (إن وجدت)
            for channel in channels:
                try:
                    entity = await self.client.get_input_entity(channel)
                    await self.client(JoinChannelRequest(entity))
                    self.step_history.append({'step_type': 'subscribe', 'channel': channel})
                    joined_any = True
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                except UserAlreadyParticipantError:
                    joined_any = True
                except FloodWaitError as e:
                    logger.warning(f"FloodWait joining {channel}: {e.seconds}s")
                    await asyncio.sleep(min(e.seconds, 30))
                except Exception as e:
                    logger.error(f"Error joining {channel}: {e}")

            # 2) انتظار وصول رسالة البوت (حتى 6 محاولات)
            messages = []
            for attempt in range(6):
                messages = await self._get_recent_messages(5)
                if messages:
                    break
                await asyncio.sleep(random.uniform(2, 4))
            if not messages:
                logger.warning("SUBSCRIBE_STEP: no bot messages received after waiting")
                return False

            # 3) اكتشاف أزرار الاشتراك في رسائل البوت والانضمام للقنوات
            found_links = set()
            for msg in messages:
                markup = getattr(msg, 'reply_markup', None)
                if markup is None:
                    continue
                rows = getattr(markup, 'rows', None)
                if not rows:
                    continue
                for row in rows:
                    for btn in row.buttons:
                        btn_text = getattr(btn, 'text', '') or ''
                        low = btn_text.lower()
                        url = getattr(btn, 'url', None)

                        # زر اشتراك برابط قناة -> استخرج القناة وانضم لها
                        # v2.2.1: أي زر برابط t.me (وليس bot/خدمة) = قناة يجب الانضمام لها
                        # (نصوص الأزرار قد لا تحتوي كلمة "اشترك" مثل: Amer🔥ichancy)
                        _is_channel_link = False
                        if url and 't.me/' in str(url):
                            _u = str(url)
                            _u_name = _u.split('t.me/')[-1].split('?')[0].split('/')[0].strip().lower()
                            if _u_name and not _u_name.endswith('bot') and _u_name not in ('share', 'joinchat', 'addtheme', 'addstickers', 'proxy', 'socks', 'telegram'):
                                _is_channel_link = True
                        if _is_channel_link:
                            try:
                                ch_name = str(url).split('t.me/')[-1].split('?')[0].split('/')[0].strip()
                                if ch_name and ch_name not in found_links:
                                    found_links.add(ch_name)
                                    entity = await self.client.get_input_entity(ch_name)
                                    await self.client(JoinChannelRequest(entity))
                                    self.step_history.append({'step_type': 'subscribe', 'channel': ch_name})
                                    joined_any = True
                                    await asyncio.sleep(random.uniform(0.5, 1.5))
                                    logger.info(f"SUBSCRIBE_STEP: joined channel from url: {ch_name}")
                            except UserAlreadyParticipantError:
                                joined_any = True
                            except Exception as e:
                                logger.debug(f"SUBSCRIBE_STEP: join from url error {url}: {e}")

                        # زر اشتراك بدون رابط -> اضغطه مباشرة
                        elif any(k in low for k in ('اشترك', 'subscribe', 'join')) and not any(k in low for k in ('تحقق', 'verify', 'check')):
                            try:
                                await msg.click(text=btn_text)
                                self.step_history.append({'step_type': 'click', 'clicked_button': btn_text})
                                pressed_any = True
                                await asyncio.sleep(random.uniform(1, 2))
                                logger.info(f"SUBSCRIBE_STEP: clicked subscribe button: {btn_text}")
                            except Exception as e:
                                logger.debug(f"SUBSCRIBE_STEP: click subscribe btn error: {e}")

            # 4) v2.1.7: قراءة روابط t.me من نص رسالة البوت (بوتات تطلب الاشتراك نصياً)
            import re as _re
            for msg in messages:
                _mtext = (msg.text or '') or (getattr(msg, 'message', '') or '')
                _links = _re.findall(r't\.me/([a-zA-Z0-9_]+)', _mtext)
                for _ch in _links:
                    _ch = _ch.strip()
                    if _ch and _ch not in found_links and _ch.lower() not in ('bot', 'start', 'joinchat', 'share'):
                        found_links.add(_ch)
                        try:
                            entity = await self.client.get_input_entity(_ch)
                            await self.client(JoinChannelRequest(entity))
                            self.step_history.append({'step_type': 'subscribe', 'channel': _ch})
                            joined_any = True
                            await asyncio.sleep(random.uniform(0.5, 1.5))
                            logger.info(f"SUBSCRIBE_STEP: joined channel from text: {_ch}")
                        except UserAlreadyParticipantError:
                            joined_any = True
                        except Exception as e:
                            logger.debug(f"SUBSCRIBE_STEP: join from text error {_ch}: {e}")

            # 4) انتظار رد البوت بعد الاشتراك ثم الضغط على زر التحقق
            await asyncio.sleep(random.uniform(2, 3))
            messages = await self._get_recent_messages(5)
            for msg in messages:
                buttons = self.parser.extract_buttons(msg)
                for btn_text in buttons:
                    low = btn_text.lower()
                    if any(k in low for k in ('تحقق', 'verify', 'check', 'تأكيد', 'اشتراك', 'subscription')):
                        try:
                            await msg.click(text=btn_text)
                            self.step_history.append({'step_type': 'click', 'clicked_button': btn_text})
                            pressed_any = True
                            await asyncio.sleep(random.uniform(min_delay, max_delay))
                            logger.info(f"SUBSCRIBE_STEP: clicked verify button: {btn_text}")
                            break
                        except Exception as e:
                            logger.debug(f"SUBSCRIBE_STEP: click verify btn error: {e}")

            # 5) إرسال /start لتحديث حالة البوت
            try:
                await self.client.send_message(self.bot_entity, '/start')
                await asyncio.sleep(random.uniform(1, 2))
                logger.info("SUBSCRIBE_STEP: sent /start to refresh state")
            except Exception as e:
                logger.debug(f"SUBSCRIBE_STEP: send /start error: {e}")

            logger.info(f"SUBSCRIBE_STEP: done (joined={joined_any}, pressed={pressed_any})")
            return True
        except Exception as e:
            logger.error(f"Error in subscribe step: {e}")
            return False


    async def _handle_check_step(self, min_delay: float, max_delay: float) -> bool:
        """معالجة خطوة التحقق - v2.1.5: ذكية (AI analyzer + 10 رسائل + احتياط متعدد)"""
        try:
            check_keywords = [
                'check', 'verify', 'confirm', 'done', 'continue', 'next', 'ok', 'yes',
                'تحقق', 'تأكيد', 'تم', 'استمر', 'متابعة', 'التالي', 'كمل', 'ابدأ', 'تمام', 'استلام', 'نعم',
                '✅', '✔️', '☑️'
            ]
            # تهيئة AI analyzer إن توفر
            _analyzer = None
            try:
                from ai_agent import MessageAnalyzer as _MA
                if _MA:
                    _analyzer = _MA()
            except Exception:
                _analyzer = None

            messages = []
            # انتظار وصول رسالة البوت (حتى 5 محاولات، 10 رسائل)
            for attempt in range(5):
                messages = await self._get_recent_messages(10)
                if messages:
                    break
                await asyncio.sleep(random.uniform(2, 4))
            if not messages:
                logger.warning("Check step: no messages received from bot")
                return False

            # 1) محاولة AI أولاً: تصنيف أدق لأزرار التحقق
            if _analyzer is not None:
                for msg in messages:
                    try:
                        analysis = _analyzer.analyze((msg.text or "") or "", raw_message=msg)
                        if analysis is not None and getattr(analysis, 'has_verify', False):
                            vbtns = getattr(analysis, 'verify_buttons', [])
                            if vbtns:
                                target = vbtns[0].text
                                await msg.click(text=target)
                                self.step_history.append({'step_type': 'click', 'clicked_button': target})
                                await asyncio.sleep(random.uniform(min_delay, max_delay))
                                logger.info(f"Check step: AI verify click: {target}")
                                return True
                    except Exception:
                        continue

            # 2) البحث بالكلمات الموسعة
            for msg in messages:
                buttons = self.parser.extract_buttons(msg)
                text_preview = (msg.text or '')[:120].replace('\n', ' ')
                logger.info(f"Check step: bot said: {text_preview!r} | buttons: {buttons[:10]}")
                for button in buttons:
                    if any(kw in button.lower() for kw in check_keywords):
                        await msg.click(text=button)
                        self.step_history.append({'step_type': 'click', 'clicked_button': button})
                        await asyncio.sleep(random.uniform(min_delay, max_delay))
                        return True

            # 3) أفضل زر متاح كاحتياط
            for msg in messages:
                buttons = self.parser.extract_buttons(msg)
                if buttons:
                    best = self.parser.guess_best_action(buttons, msg.text or '')
                    if best:
                        await msg.click(text=best)
                        self.step_history.append({'step_type': 'click', 'clicked_button': best})
                        await asyncio.sleep(random.uniform(min_delay, max_delay))
                        return True

            logger.warning("Check step: no clickable buttons found")
            return False
        except Exception as e:
            logger.error(f"Check step error: {e}")
            return False

    async def _handle_math_step(self, min_delay: float, max_delay: float) -> bool:
        """معالجة خطوة حل الرياضيات - الإرسال للبوت مباشرة"""
        try:
            messages = await self._get_recent_messages(5)
            for msg in messages:
                if msg.text:
                    answer = self.parser.solve_math_expression(msg.text)
                    if answer is not None:
                        buttons = self.parser.extract_buttons(msg)
                        # البحث عن الزر الذي يحتوي على الإجابة
                        for button in buttons:
                            if str(answer) in button:
                                await msg.click(text=button)
                                self.step_history.append({'step_type': 'solve_math', 'answer': str(answer), 'method': 'click'})
                                return True

                        # إذا لم يوجد زر، أرسل الإجابة للبوت
                        await self.client.send_message(self.bot_entity, str(answer))
                        self.step_history.append({'step_type': 'send_text', 'sent_text': str(answer), 'method': 'send'})
                        await asyncio.sleep(random.uniform(min_delay, max_delay))
                        return True
            return False
        except Exception:
            return False

    async def _handle_emoji_step(self, min_delay: float, max_delay: float) -> bool:
        """معالجة خطوة مطابقة الإيموجي"""
        try:
            messages = await self._get_recent_messages(5)
            for msg in messages:
                result = self.parser.solve_emoji_challenge(msg)
                if result:
                    buttons = self.parser.extract_buttons(msg)
                    for button in buttons:
                        if result in button:
                            await msg.click(text=button)
                            self.step_history.append({'step_type': 'match_emoji', 'clicked_button': button})
                            return True
            return False
        except Exception:
            return False

    async def _handle_phone_step(self, phone_link: str, min_delay: float, max_delay: float, phone_mode: str = 'auto') -> bool:
        """معالجة خطوة مشاركة الرقم - v2.1.0: فصل صريح بين الطرق"""
        try:
            mode = (phone_mode or 'auto').strip().lower()
            logger.info(f"PHONE_STEP: mode={mode} link={phone_link or 'none'}")

            # ===== v2.1.5: انتظار طلب البوت للرقم قبل الإرسال (لا إرسال أعمى) =====
            PHONE_REQUEST_SIGNALS = (
                'شارك رقم', 'مشاركة رقم', 'شارك جهة', 'مشاركة جهة', 'أرسل رقم', 'ارسل رقم',
                'رقم هاتفك', 'رقم الهاتف', 'هاتفك', 'رقمك', 'شارك هاتف', 'مشاركة الهاتف',
                'phone number', 'share your phone', 'share phone', 'send your number',
                'share your number', 'send phone number', 'share contact', 'send contact',
                'share your contact', 'telephone', 'رقم الاتصال', 'مشاركة الاتصال'
            )
            request_found = False
            for _attempt in range(5):
                _msgs = await self._get_recent_messages(8)
                for _m in _msgs:
                    _mtext = (_m.text or '') or (getattr(_m, 'message', '') or '')
                    _mlow = _mtext.lower()
                    # إشارة نصية في الرسالة
                    if any(sig in _mlow for sig in PHONE_REQUEST_SIGNALS):
                        request_found = True
                        break
                    # زر request_contact أو زر نصه يشير للرقم
                    _markup = getattr(_m, 'reply_markup', None)
                    if _markup is not None:
                        _rows = getattr(_markup, 'rows', None)
                        if _rows:
                            for _row in _rows:
                                for _btn in _row.buttons:
                                    _btext = (getattr(_btn, 'text', '') or '').lower()
                                    if getattr(_btn, 'request_contact', False) or any(sig in _btext for sig in PHONE_REQUEST_SIGNALS):
                                        request_found = True
                                        break
                                if request_found:
                                    break
                    if request_found:
                        break
                if request_found:
                    logger.info("PHONE_STEP: bot requested phone - proceeding")
                    break
                await asyncio.sleep(random.uniform(2, 3))
            if not request_found:
                logger.warning("PHONE_STEP: bot did not request phone after waiting - aborting (will retry later)")
                return False

            # ===== الوضع forward: تحويل من مجموعة عامة فقط =====
            if mode == 'forward':
                if not (phone_link and 't.me/' in phone_link):
                    logger.warning("PHONE_STEP: forward mode but no valid link")
                    return False
                try:
                    from telethon.tl.types import InputMediaContact, MessageMediaContact

                    parts = phone_link.split('/')
                    channel = parts[-2]
                    msg_id = int(parts[-1])

                    entity = await self.client.get_input_entity(channel)
                    msg = await self.client.get_messages(entity, ids=msg_id)
                    if not msg:
                        logger.warning(f"PHONE_STEP: message {msg_id} not found in {channel}")
                        return False

                    # 1) إذا كانت الرسالة جهة اتصال -> أعد إرسالها كبطاقة اتصال جديدة
                    #    (بدون ترويسة "محولة من" = يقبلها البوت مثل التحويل اليدوي)
                    media = getattr(msg, 'media', None)
                    if isinstance(media, MessageMediaContact) or (media is not None and getattr(media, 'phone_number', None)):
                        phone_number = media.phone_number
                        first_name = getattr(media, 'first_name', '') or 'User'
                        last_name = getattr(media, 'last_name', '') or ''
                        vcard = getattr(media, 'vcard', '') or ''
                        await self.client.send_file(self.bot_entity, InputMediaContact(
                            phone_number=phone_number,
                            first_name=first_name,
                            last_name=last_name,
                            vcard=vcard
                        ))
                        self.step_history.append({'step_type': 'send_contact', 'phone': phone_number, 'from': phone_link})
                        await asyncio.sleep(random.uniform(min_delay, max_delay))
                        logger.info(f"PHONE_STEP: contact reshared as NEW contact: {phone_number}")
                        return True

                    # 2) احتياط: إذا لم تكن جهة اتصال -> forward عادي
                    await self.client.forward_messages(self.bot_entity, [msg_id], from_peer=entity)
                    self.step_history.append({'step_type': 'forward', 'from': phone_link})
                    await asyncio.sleep(random.uniform(min_delay, max_delay))
                    logger.info(f"PHONE_STEP: forwarded (non-contact) {phone_link}")
                    return True
                except Exception as e:
                    logger.error(f"PHONE_STEP: forward error: {e}")
                    return False

            # ===== الوضع button: ضغط زر مشاركة الرقم فقط =====
            if mode == 'button':
                messages = await self._get_recent_messages(5)
                phone_keywords = ('شارك', 'مشاركة', 'رقم', 'هاتف', 'phone', 'contact', 'number', 'share')
                for msg in messages:
                    markup = getattr(msg, 'reply_markup', None)
                    if markup is None:
                        continue
                    rows = getattr(markup, 'rows', None)
                    if not rows:
                        continue
                    for row in rows:
                        for btn in row.buttons:
                            btn_text = getattr(btn, 'text', '') or ''
                            low = btn_text.lower()
                            has_contact_req = getattr(btn, 'request_contact', False)
                            if has_contact_req or any(k in low for k in phone_keywords):
                                try:
                                    await msg.click(text=btn_text)
                                    self.step_history.append({'step_type': 'click', 'clicked_button': btn_text})
                                    await asyncio.sleep(random.uniform(min_delay, max_delay))
                                    logger.info(f"PHONE_STEP: clicked phone button: {btn_text}")
                                    return True
                                except Exception as e:
                                    logger.debug(f"PHONE_STEP: click phone btn error: {e}")
                logger.warning("PHONE_STEP: button mode but no phone button found")
                return False

            # ===== الوضع direct: إرسال رقم الجلسة مباشرة فقط =====
            if mode == 'direct':
                try:
                    from telethon.tl.types import InputMediaContact
                    me = await self.client.get_me()
                    phone = getattr(me, 'phone', None)
                    if phone:
                        await self.client.send_file(self.bot_entity, InputMediaContact(
                            phone_number=phone,
                            first_name=getattr(me, 'first_name', '') or 'User',
                            last_name=getattr(me, 'last_name', '') or '',
                            vcard=''
                        ))
                        self.step_history.append({'step_type': 'send_phone', 'phone': phone})
                        await asyncio.sleep(random.uniform(min_delay, max_delay))
                        logger.info(f"PHONE_STEP: sent contact {phone} to bot")
                        return True
                except Exception as e:
                    logger.error(f"PHONE_STEP: direct contact error: {e}")
                return False

            # ===== الوضع auto (افتراضي): forward إن وُجد رابط، ثم زر، ثم مباشر =====
            # 1) forward من الرابط إن وُجد
            if phone_link and 't.me/' in phone_link:
                try:
                    from telethon.tl.types import InputMediaContact, MessageMediaContact
                    parts = phone_link.split('/')
                    channel = parts[-2]
                    msg_id = int(parts[-1])
                    entity = await self.client.get_input_entity(channel)
                    msg = await self.client.get_messages(entity, ids=msg_id)
                    if not msg:
                        return False
                    # جهة اتصال -> إعادة إرسال كبطاقة جديدة (بدون محولة من)
                    media = getattr(msg, 'media', None)
                    if isinstance(media, MessageMediaContact) or (media is not None and getattr(media, 'phone_number', None)):
                        await self.client.send_file(self.bot_entity, InputMediaContact(
                            phone_number=media.phone_number,
                            first_name=getattr(media, 'first_name', '') or 'User',
                            last_name=getattr(media, 'last_name', '') or '',
                            vcard=getattr(media, 'vcard', '') or ''
                        ))
                        self.step_history.append({'step_type': 'send_contact', 'phone': media.phone_number, 'from': phone_link})
                        await asyncio.sleep(random.uniform(min_delay, max_delay))
                        logger.info(f"PHONE_STEP: auto -> contact reshared as NEW: {media.phone_number}")
                        return True
                    # احتياط: forward عادي
                    await self.client.forward_messages(self.bot_entity, [msg_id], from_peer=entity)
                    self.step_history.append({'step_type': 'forward', 'from': phone_link})
                    await asyncio.sleep(random.uniform(min_delay, max_delay))
                    logger.info(f"PHONE_STEP: auto -> forwarded (non-contact) {phone_link}")
                    return True
                except Exception as e:
                    logger.debug(f"PHONE_STEP: auto forward error: {e}")

            # 2) زر مشاركة الرقم
            messages = await self._get_recent_messages(5)
            phone_keywords = ('شارك', 'مشاركة', 'رقم', 'هاتف', 'phone', 'contact', 'number', 'share')
            for msg in messages:
                markup = getattr(msg, 'reply_markup', None)
                if markup is None:
                    continue
                rows = getattr(markup, 'rows', None)
                if not rows:
                    continue
                for row in rows:
                    for btn in row.buttons:
                        btn_text = getattr(btn, 'text', '') or ''
                        low = btn_text.lower()
                        has_contact_req = getattr(btn, 'request_contact', False)
                        if has_contact_req or any(k in low for k in phone_keywords):
                            try:
                                await msg.click(text=btn_text)
                                self.step_history.append({'step_type': 'click', 'clicked_button': btn_text})
                                await asyncio.sleep(random.uniform(min_delay, max_delay))
                                logger.info(f"PHONE_STEP: auto -> clicked phone button: {btn_text}")
                                return True
                            except Exception as e:
                                logger.debug(f"PHONE_STEP: auto click phone btn error: {e}")

            # 3) إرسال رقم الجلسة مباشرة
            try:
                from telethon.tl.types import InputMediaContact
                me = await self.client.get_me()
                phone = getattr(me, 'phone', None)
                if phone:
                    await self.client.send_file(self.bot_entity, InputMediaContact(
                        phone_number=phone,
                        first_name=getattr(me, 'first_name', '') or 'User',
                        last_name=getattr(me, 'last_name', '') or '',
                        vcard=''
                    ))
                    self.step_history.append({'step_type': 'send_phone', 'phone': phone})
                    await asyncio.sleep(random.uniform(min_delay, max_delay))
                    logger.info(f"PHONE_STEP: auto -> sent contact {phone}")
                    return True
            except Exception as e:
                logger.debug(f"PHONE_STEP: auto direct error: {e}")

            logger.warning("PHONE_STEP: could not share phone in auto mode")
            return False
        except FloodWaitError as e:
            logger.warning(f"FloodWait phone step: {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 30))
            return False
        except Exception as e:
            logger.error(f"Phone step error: {e}")
            return False


    async def _handle_visit_step(self, min_delay: float, max_delay: float) -> bool:
        """معالجة خطوة زيارة رابط"""
        try:
            messages = await self._get_recent_messages(5)
            visit_keywords = ['visit', 'open', 'website', 'link', 'زيارة', 'افتح', 'رابط']

            for msg in messages:
                buttons = self.parser.extract_buttons(msg)
                for button in buttons:
                    if any(kw in button.lower() for kw in visit_keywords):
                        await msg.click(text=button)
                        self.step_history.append({'step_type': 'click', 'clicked_button': button})
                        await asyncio.sleep(random.uniform(min_delay, max_delay))
                        return True

            # البحث عن أزرار تحتوي على روابط
            for msg in messages:
                if hasattr(msg.reply_markup, 'rows'):
                    for row in msg.reply_markup.rows:
                        for button in row.buttons:
                            if button.url:
                                await msg.click(text=button.text)
                                self.step_history.append({'step_type': 'click', 'clicked_button': button.text, 'url': button.url})
                                return True
            return False
        except Exception:
            return False

    async def _handle_click_step(self, target_text: str, min_delay: float, max_delay: float) -> bool:
        """معالجة خطوة النقر العامة"""
        try:
            messages = await self._get_recent_messages(5)
            for msg in messages:
                buttons = self.parser.extract_buttons(msg)

                if target_text:
                    # البحث عن الزر المحدد
                    for button in buttons:
                        if target_text.lower() in button.lower():
                            await msg.click(text=button)
                            self.step_history.append({'step_type': 'click', 'clicked_button': button})
                            return True
                else:
                    # تخمين أفضل زر
                    best = self.parser.guess_best_action(buttons, msg.text or '')
                    if best:
                        await msg.click(text=best)
                        self.step_history.append({'step_type': 'click', 'clicked_button': best})
                        return True
            return False
        except Exception:
            return False

    async def _handle_start_step(self, ref_id: str, min_delay: float, max_delay: float) -> bool:
        """خطوة start - إرسال /start (مع ref إن وجد)"""
        try:
            if ref_id:
                await self.client.send_message(self.bot_entity, f'/start {ref_id}')
                self.step_history.append({'step_type': 'send', 'sent_text': f'/start {ref_id}'})
            else:
                await self.client.send_message(self.bot_entity, '/start')
                self.step_history.append({'step_type': 'send', 'sent_text': '/start'})
            await asyncio.sleep(random.uniform(min_delay, max_delay))
            return True
        except Exception as e:
            logger.error(f"Error in start step: {e}")
            return False

    async def _handle_text_step(self, text_to_send: str, min_delay: float, max_delay: float) -> bool:
        """خطوة إرسال نص محدد"""
        try:
            if not text_to_send:
                return False
            await self.client.send_message(self.bot_entity, text_to_send)
            self.step_history.append({'step_type': 'send_text', 'sent_text': text_to_send})
            await asyncio.sleep(random.uniform(min_delay, max_delay))
            return True
        except Exception as e:
            logger.error(f"Error in text step: {e}")
            return False

    async def _handle_forward_step(self, target_link: str, min_delay: float, max_delay: float) -> bool:
        """خطوة إعادة توجيه رسالة إلى البوت"""
        try:
            if not target_link or 't.me/' not in target_link:
                return False
            parts = target_link.split('/')
            channel = parts[-2]
            msg_id = int(parts[-1])
            entity = await self.client.get_input_entity(channel)
            msg = await self.client.get_messages(entity, ids=msg_id)
            if msg:
                await self.client.forward_messages(self.bot_entity, msg)
                self.step_history.append({'step_type': 'forward', 'from': target_link})
                return True
            return False
        except FloodWaitError as e:
            logger.warning(f"FloodWait forward step: {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 30))
            return False
        except Exception as e:
            logger.error(f"Error in forward step: {e}")
            return False

    async def _handle_react_step(self, target_link: str, emoji: str = '👍') -> bool:
        """خطوة تفاعل على منشور"""
        try:
            if not target_link or 't.me/' not in target_link:
                return False
            parts = target_link.split('/')
            channel = parts[-2]
            msg_id = int(parts[-1])
            entity = await self.client.get_input_entity(channel)
            if emoji == 'random':
                emoji = random.choice(['👍', '❤️', '🔥', '👏', '😊', '💯', '⚡', '🎉'])
            await self.client.send_reaction(entity, msg_id, emoji)
            self.step_history.append({'step_type': 'react', 'target': target_link, 'emoji': emoji})
            return True
        except Exception as e:
            logger.error(f"Error in react step: {e}")
            return False

    async def _handle_vote_step(self, target_link: str, option: str = '0') -> bool:
        """خطوة تصويت في استفتاء"""
        try:
            if not target_link or 't.me/' not in target_link:
                return False
            parts = target_link.split('/')
            channel = parts[-2]
            msg_id = int(parts[-1])
            entity = await self.client.get_input_entity(channel)
            msg = await self.client.get_messages(entity, ids=msg_id)
            if msg and msg.poll:
                await msg.click(text=option)
                self.step_history.append({'step_type': 'vote', 'target': target_link, 'option': option})
                return True
            return False
        except Exception as e:
            logger.error(f"Error in vote step: {e}")
            return False

    async def _execute_smart_ai_loop(self, session_id: str, bot_username: str, speed: str = "medium") -> bool:
        """حلقة AI ذكية للمهام التلقائية - يحلل ويقرر حتى النجاح.
        إذا لم يتوفر AI، تنخفض تلقائياً إلى حلقة حسّية (parser + guess).
        """
        try:
            analyzer = MessageAnalyzer() if MessageAnalyzer else None
            decision_engine = DecisionEngine() if DecisionEngine else None

            # v2.1.3: إرسال /start أولاً لتحفيز البوت على الرد (خاصة الحسابات الجديدة)
            try:
                ref_id = None
                target_link = self.task.get('target_bot_link', '')
                if '?start=' in target_link:
                    ref_id = target_link.split('?start=')[-1]
                if ref_id:
                    await self.client.send_message(self.bot_entity, f'/start {ref_id}')
                    logger.info(f"SMART_LOOP: sent /start {ref_id}")
                else:
                    await self.client.send_message(self.bot_entity, '/start')
                    logger.info("SMART_LOOP: sent /start")
                await asyncio.sleep(random.uniform(2, 4))
            except Exception as e:
                logger.debug(f"SMART_LOOP: send /start error: {e}")

            # محاولة استرجاع قالب محفوظ
            template = None
            try:
                if hasattr(self.template_engine, 'find_template'):
                    template = await self.template_engine.find_template(bot_username)
            except Exception:
                pass

            max_iterations = 15
            for iteration in range(max_iterations):
                # جلب آخر رسائل البوت
                msgs = await self._get_recent_messages(limit=3)
                if not msgs:
                    # v2.1.3: أعد إرسال /start كل 3 محاولات فارغة (حساب جديد)
                    if iteration > 0 and iteration % 3 == 0:
                        try:
                            await self.client.send_message(self.bot_entity, '/start')
                            logger.info(f"SMART_LOOP: re-sent /start (iter {iteration})")
                            await asyncio.sleep(random.uniform(2, 3))
                        except Exception:
                            pass
                    await asyncio.sleep(random.uniform(2, 4))
                    continue

                msg = msgs[0]
                text = msg.message or msg.text or ""

                # --- DIAGNOSTICS v2.0.5: سجل تفصيلي لرسالة البوت ---
                try:
                    _btns = self.parser.extract_buttons(msg)
                    _raw = getattr(msg, 'reply_markup', None)
                    _btn_detail = ""
                    if _raw is not None and hasattr(_raw, 'rows'):
                        for _row in _raw.rows:
                            for _b in _row.buttons:
                                _btn_detail += f"[{getattr(_b, 'text', '?')}|url={getattr(_b, 'url', None)}|contact={getattr(_b, 'request_contact', False)}] "
                    logger.info(f"DIAG: iter={iteration} out={getattr(msg, 'out', False)} text={text[:150]!r}")
                    logger.info(f"DIAG: buttons={_btn_detail.strip() or 'NONE'} | extract={_btns[:8]}")
                except Exception as _e:
                    logger.info(f"DIAG: error reading buttons: {_e}")

                # ===== v2.3.3: حل المعادلات مباشرة (أولوية قصوى - قبل أي تحليل) =====
                # أي رسالة تحتوي معادلة -> نحلها ونرسل الجواب فوراً
                try:
                    _direct_ans = self.parser.solve_math_expression(text)
                    if _direct_ans is not None:
                        await self.client.send_message(self.bot_entity, str(_direct_ans))
                        self.step_history.append({'step_type': 'send_text', 'sent_text': str(_direct_ans)})
                        await asyncio.sleep(random.uniform(*self._get_delay(speed)))
                        logger.info(f"Smart loop: direct math solved: {_direct_ans}")
                        continue
                except Exception:
                    pass

                # ===== فحص النجاح - v2.3.0 (منطق نظيف وحاسم) =====
                lower = text.lower()
                # 1) كلمات النجاح الحقيقية (النهاية الفعلية للمهمة)
                success_keywords = [
                    'success', 'congratulation', 'completed', 'مبروك', 'تم بنجاح', 'نجاح',
                    'تم تفعيل', 'تم التسجيل', 'تم تسجيل', 'تمت العملية', 'اكتملت العملية',
                    'تم منحك', 'تم منح', 'تمت إحالتك', 'تمت احالتك', 'تم تفعيل إحالتك', 'تم تفعيل احالتك',
                    'مبروك عليك', 'أحسنت', 'احسنت', 'الإجابة صحيحة', 'الاجابة صحيحة'
                ]
                is_success = any(k in lower for k in success_keywords)

                # 2) رسالة اشتراك إجباري (فيها أزرار قنوات بروابط t.me) -> نفّذ الاشتراك
                if not is_success:
                    try:
                        markup = getattr(msg, 'reply_markup', None)
                        has_sub_links = False
                        if markup is not None:
                            rows = getattr(markup, 'rows', None)
                            if rows:
                                for _row in rows:
                                    for _btn in _row.buttons:
                                        _url = getattr(_btn, 'url', None)
                                        if _url and 't.me/' in str(_url):
                                            _uname = str(_url).split('t.me/')[-1].split('?')[0].split('/')[0].strip().lower()
                                            if _uname and not _uname.endswith('bot'):
                                                has_sub_links = True
                        if has_sub_links:
                            logger.info("Smart loop: subscribe-required detected -> executing subscribe")
                            _sub_ok = await self._handle_subscribe_step([], *self._get_delay(speed))
                            if _sub_ok:
                                await asyncio.sleep(random.uniform(2, 3))
                                continue
                    except Exception:
                        pass

                # 3) "مسجل مسبقاً" -> يعتبر نجاحاً (لا تكرار)
                if not is_success:
                    registered_keywords = [
                        'already registered', 'already joined', 'already subscribed', 'already exists',
                        'registered before', 'duplicate', 'تم التسجيل مسبقاً', 'مسجل مسبقاً',
                        'مسجل مسبقا', 'سبق لك التسجيل', 'سجلت من قبل', 'قمت بالتسجيل من قبل',
                        'بالفعل مسجل', 'انت مسجل', 'أنت مسجل', 'تم التسجيل سابقاً', 'موجود مسبقاً'
                    ]
                    if any(k in lower for k in registered_keywords):
                        is_success = True
                        logger.info(f"Smart loop: already-registered detected -> success (dedup)")

                if is_success:
                    logger.info(f"Smart loop success detected for {bot_username}")
                    await record_completion(session_id, bot_username, 'composite',
                                            self.task.get('parent_task_id'))
                    try:
                        await self.template_engine.analyze_and_learn(bot_username, self.step_history)
                    except Exception as e:
                        logger.debug(f"Template learning error (non-fatal): {e}")
                    return True

                # --- الوضع بدون AI: محلل حسي ---
                if analyzer is None:
                    executed = False
                    # محاولة حل رياضيات
                    answer = self.parser.solve_math_expression(text)
                    if answer is not None:
                        try:
                            await self.client.send_message(self.bot_entity, str(answer))
                            self.step_history.append({'step_type': 'send_text', 'sent_text': str(answer)})
                            executed = True
                        except Exception:
                            pass
                    if not executed:
                        # مطابقة إيموجي
                        try:
                            emoji_ans = self.parser.solve_emoji_challenge(msg)
                            if emoji_ans:
                                await msg.click(text=emoji_ans)
                                self.step_history.append({'step_type': 'match_emoji', 'clicked_button': emoji_ans})
                                executed = True
                        except Exception:
                            pass
                    if not executed:
                        # أفضل زر متاح
                        buttons = self.parser.extract_buttons(msg)
                        best = self.parser.guess_best_action(buttons, text)
                        if best:
                            try:
                                await msg.click(text=best)
                                self.step_history.append({'step_type': 'click', 'clicked_button': best})
                                executed = True
                            except Exception:
                                pass
                    await asyncio.sleep(random.uniform(*self._get_delay(speed)))
                    continue

                # --- تحليل AI ---
                try:
                    analysis = analyzer.analyze(text, raw_message=msg)
                except Exception as e:
                    logger.debug(f"Analyze error: {e}")
                    analysis = None

                if analysis is None:
                    # حلقة احتياطية: انقر أفضل زر من parser
                    buttons = self.parser.extract_buttons(msg)
                    best = self.parser.guess_best_action(buttons, text)
                    if best:
                        try:
                            await msg.click(text=best)
                            self.step_history.append({'step_type': 'click', 'clicked_button': best})
                        except Exception:
                            pass
                    await asyncio.sleep(random.uniform(*self._get_delay(speed)))
                    continue

                decision = await ai_decide(decision_engine, analysis, bot_username,
                                           self.step_history, template)
                if decision is None:
                    # لا قرار: انقر أفضل زر كاحتياط
                    buttons = getattr(analysis, 'buttons', [])
                    if buttons:
                        try:
                            await msg.click(text=buttons[0].text)
                            self.step_history.append({'step_type': 'click', 'clicked_button': buttons[0].text})
                        except Exception:
                            pass
                    await asyncio.sleep(random.uniform(*self._get_delay(speed)))
                    continue

                action = getattr(decision, 'action', 'retry')
                confidence = getattr(decision, 'confidence', 0.0)
                reason = getattr(decision, 'reason', '')
                fallback_needed = False  # fallback معطّل نهائياً - يكمل تلقائياً
                logger.info(f"AI decision {iteration}: {action} conf={confidence} reason={reason}")

                # v2.2.0: كشف التكرار الذكي - فقط نفس الرسالة + نفس القرار 4 مرات
                # (إن تغير نص الرسالة فهذا تقدم حقيقي وليس تكراراً)
                current_sig = (action, (text or '')[:120])
                last_sig = getattr(self, '_last_sig', None)
                if current_sig == last_sig:
                    self._repeat_count = getattr(self, '_repeat_count', 0) + 1
                else:
                    self._repeat_count = 0
                    self._last_sig = current_sig
                if self._repeat_count >= 4:
                    logger.warning(f"Smart loop: same message+action 4x for {bot_username} -> real stall, failing (will retry)")
                    # فشل حقيقي وليس نجاحاً كاذباً - المهمة ستعيد المحاولة في دورة قادمة
                    return False

                # Fallback
                if fallback_needed:
                    try:
                        bot_token = os.getenv('BOT_TOKEN')
                        admin_group = os.getenv('ADMIN_GROUP_ID')
                        from ai_agent import FallbackManager

                        # إنشاء طلب fallback
                        buttons = [
                            {"text": b.text, "type": getattr(b, 'button_type', 'callback')}
                            for b in getattr(analysis, 'buttons', [])
                        ]
                        fb = FallbackManager(supabase, None, None)
                        req_id = await fb.create_request(self.task.get('id') or self.task.get('parent_task_id') or 'unknown',
                                                         session_id, bot_username, text, buttons)

                        # إشعار للآدمن عبر Bot API إذا متاح
                        if bot_token and admin_group and req_id:
                            try:
                                from aiogram import Bot
                                bot_obj = Bot(token=bot_token)
                                fb2 = FallbackManager(supabase, bot_obj, int(admin_group))
                                await fb2._notify_admin(req_id, bot_username, text, buttons)
                                await bot_obj.session.close()
                            except Exception:
                                pass

                        # انتظر إجابة 5 دقائق
                        answer = await fb.wait_for_answer(req_id, timeout=300)
                        if answer:
                            # كلمة خاصة: إعلان إتمام المهمة (من الآدمن)
                            if str(answer).strip().lower() in ('complete', 'done', 'finish', 'success', 'انتهت', 'تم', 'اكتملت', 'خلصت', 'تمت المهمة', 'نجحت'):
                                logger.info(f"Smart loop: admin marked task complete for {bot_username}")
                                await record_completion(session_id, bot_username, 'composite',
                                                        self.task.get('parent_task_id'))
                                return True
                            # نفذ الإجابة
                            if answer.isdigit():
                                idx = int(answer) - 1
                                buttons_list = getattr(analysis, 'buttons', [])
                                if 0 <= idx < len(buttons_list):
                                    await msg.click(text=buttons_list[idx].text)
                                    self.step_history.append({'step_type': 'click', 'clicked_button': buttons_list[idx].text})
                                    await asyncio.sleep(random.uniform(1, 3))
                                    continue
                            else:
                                # نص
                                await self.client.send_message(self.bot_entity, answer)
                                self.step_history.append({'step_type': 'send_text', 'sent_text': answer})
                                continue
                    except Exception as e:
                        logger.error(f"Fallback handling error: {e}")

                    # إذا لم يجب الآدمن، جرب أفضل زر
                    best = getattr(analysis, 'buttons', [])
                    if best:
                        try:
                            await msg.click(text=best[0].text)
                            self.step_history.append({'step_type': 'click', 'clicked_button': best[0].text})
                        except Exception:
                            pass
                    await asyncio.sleep(random.uniform(2, 4))
                    continue

                # تنفيذ القرار العادي
                executed = False
                if action == 'subscribe_all':
                    executed = await self._handle_subscribe_step([], *self._get_delay(speed))
                elif action == 'solve_math':
                    executed = await self._handle_math_step(*self._get_delay(speed))
                elif action == 'click_verify':
                    executed = await self._handle_check_step(*self._get_delay(speed))
                elif action == 'share_phone':
                    executed = await self._handle_phone_step("", *self._get_delay(speed))
                elif action == 'match_emoji':
                    executed = await self._handle_emoji_step(*self._get_delay(speed))
                elif action == 'complete':
                    await record_completion(session_id, bot_username, 'composite',
                                            self.task.get('parent_task_id'))
                    return True
                elif action in ('click_best', 'retry'):
                    # خمن أفضل زر
                    if getattr(analysis, 'buttons', []):
                        best = analysis.buttons[0].text
                        try:
                            await msg.click(text=best)
                            self.step_history.append({'step_type': 'click', 'clicked_button': best})
                            executed = True
                        except Exception:
                            executed = False

                if not executed:
                    # جرب ضغط أفضل زر كاحتياط
                    try:
                        if getattr(analysis, 'buttons', []):
                            await msg.click(text=analysis.buttons[0].text)
                            self.step_history.append({'step_type': 'click', 'clicked_button': analysis.buttons[0].text})
                    except Exception:
                        pass

                await asyncio.sleep(random.uniform(*self._get_delay(speed)))

            logger.warning(f"Smart loop max iterations reached for {bot_username}")
            return False
        except Exception as e:
            logger.error(f"Smart AI loop error: {e}")
            return False

    def _get_delay(self, speed: str) -> Tuple[float, float]:
        ranges = {'slow': (3, 7), 'medium': (1.5, 4), 'fast': (0.5, 2)}
        return ranges.get(speed, (1.5, 4))


# ============================================
# TASK PROCESSOR (محسن)
# ============================================
class TaskProcessor:
    """Processes all types of automation tasks"""

    def __init__(self, client: TelegramClient, session_id: str, template_engine: TemplateLearningEngine):
        self.client = client
        self.session_id = session_id
        self.template_engine = template_engine
        self.parser = SmartTaskParser()
        self.me = None
        # v3.0: تهيئة مكونات AI (مع حماية من عدم توفرها)
        self.ai_analyzer = None
        self.ai_executor = None
        self.ai_decision = None
        if AI_AVAILABLE:
            try:
                self.ai_analyzer = MessageAnalyzer() if MessageAnalyzer else None
            except Exception as e:
                logger.warning(f"MessageAnalyzer init failed: {e}")
            try:
                self.ai_executor = ActionExecutor() if ActionExecutor else None
            except Exception as e:
                logger.warning(f"ActionExecutor init failed: {e}")
            try:
                self.ai_decision = DecisionEngine() if DecisionEngine else None
            except Exception as e:
                logger.warning(f"DecisionEngine init failed: {e}")

    async def initialize(self) -> bool:
        """تهيئة المعالج"""
        try:
            if not self.client.is_connected():
                await self.client.connect()
            if not await self.client.is_user_authorized():
                return False
            self.me = await self.client.get_me()
            logger.info(f"TaskProcessor initialized for {self.me.first_name} (@{self.me.username})")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize TaskProcessor: {e}")
            return False

    async def process_task(self, task: Dict[str, Any]) -> bool:
        """معالجة مهمة واحدة - مع إعادة محاولة حقيقية (max 3)"""
        tid = task.get('id')
        if not tid:
            logger.error("Task without id received, skipping")
            return False

        try:
            task_type = task.get('task_type', 'composite')
            target_bot = task.get('target_bot_link', '')

            # استخراج اسم البوت من الرابط
            bot_username = target_bot
            if 't.me/' in target_bot:
                bot_username = target_bot.split('t.me/')[-1].split('?')[0].split('/')[0]

            # التحقق من إكمال المهمة مسبقاً (مع parent_task_id لمنع التخطي الخاطئ)
            if await self._is_already_completed(bot_username, task.get('parent_task_id')):
                await async_supabase_query(
                    lambda: supabase.table('tasks_queue').update({
                        'status': 'completed',
                        'completed_at': datetime.now(timezone.utc).isoformat()
                    }).eq('id', tid).execute()
                )
                logger.info(f"Task {tid[:8]} already completed for {bot_username}")
                return True

            # تحديث حالة المهمة إلى قيد المعالجة
            await async_supabase_query(
                lambda: supabase.table('tasks_queue').update({
                    'status': 'processing',
                    'started_at': datetime.now(timezone.utc).isoformat()
                }).eq('id', tid).execute()
            )

            success = False

            # الحصول على كيان البوت
            try:
                bot_entity = await self.client.get_input_entity(bot_username)
            except Exception:
                bot_entity = bot_username

            # إنشاء منفذ المهام المركبة
            composite_executor = CompositeTaskExecutor(
                self.client, self.template_engine, bot_entity, task
            )

            # توزيع أنواع المهام
            if task_type in ('composite', 'smart', 'manual'):
                success = await composite_executor.execute_composite_task(
                    self.session_id, bot_username
                )
            elif task_type == 'join':
                success = await self._handle_join(task)
            elif task_type == 'follow_channel':
                success = await self._handle_follow_channel(task)
            elif task_type == 'react_post':
                success = await self._handle_react_post(task)
            elif task_type == 'vote_poll':
                success = await self._handle_vote_poll(task)
            elif task_type == 'forward':
                success = await self._handle_forward_task(task)
            elif task_type in ('verify', 'check'):
                success = await self._handle_verify(task)
            elif task_type == 'click':
                success = await self._handle_click(task)
            elif task_type in ('solve', 'math'):
                success = await self._handle_solve(task)
            elif task_type == 'start':
                success = await self._handle_start(task)
            elif task_type == 'subscribe':
                success = await self._handle_subscribe(task)
            elif task_type == 'phone':
                success = await self._handle_phone(task)
            elif task_type == 'emoji':
                success = await self._handle_emoji(task)
            elif task_type == 'language':
                success = await self._handle_language(task)
            elif task_type == 'text':
                success = await self._handle_text(task)
            elif task_type == 'visit':
                success = await self._handle_visit(task)
            else:
                # أنواع غير معروفة: تفويض للحلقة الذكية (AI أو حسّية)
                logger.warning(f"Unknown task type: {task_type} - delegating to smart loop")
                success = await composite_executor.execute_smart_task(
                    self.session_id, bot_username, task.get('speed', 'medium')
                )

            # تحديث الحالة النهائية مع نظام إعادة محاولة حقيقي
            now_iso = datetime.now(timezone.utc).isoformat()
            if success:
                await async_supabase_query(
                    lambda: supabase.table('tasks_queue').update({
                        'status': 'completed',
                        'completed_at': now_iso
                    }).eq('id', tid).execute()
                )
                await record_completion(self.session_id, bot_username, task_type,
                                        task.get('parent_task_id'))
                logger.info(f"Task {tid[:8]} completed successfully")
            else:
                next_retry = task.get('retry_count', 0) + 1
                update_data: Dict[str, Any] = {
                    'retry_count': next_retry,
                    'error_message': f'Attempt {next_retry} failed',
                    'completed_at': now_iso
                }
                if next_retry >= MAX_RETRIES:
                    update_data['status'] = 'failed'
                    logger.warning(f"Task {tid[:8]} failed permanently after {MAX_RETRIES} attempts")
                else:
                    update_data['status'] = 'pending'  # سيعاد التقاطها في الدورة القادمة
                    logger.warning(f"Task {tid[:8]} failed (attempt {next_retry}/{MAX_RETRIES}), will retry")
                await async_supabase_query(
                    lambda: supabase.table('tasks_queue').update(update_data).eq('id', tid).execute()
                )

            return success

        except FloodWaitError as e:
            logger.warning(f"FloodWait in process_task: {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 120))
            await async_supabase_query(
                lambda: supabase.table('tasks_queue').update({
                    'status': 'pending',
                    'retry_count': task.get('retry_count', 0) + 1,
                    'error_message': f'FloodWait: {e.seconds}s',
                    'completed_at': datetime.now(timezone.utc).isoformat()
                }).eq('id', tid).execute()
            )
            return False
        except Exception as e:
            logger.error(f"Error processing task {tid}: {e}")
            await async_supabase_query(
                lambda: supabase.table('tasks_queue').update({
                    'status': 'failed',
                    'error_message': str(e)[:500],
                    'completed_at': datetime.now(timezone.utc).isoformat()
                }).eq('id', tid).execute()
            )
            return False

    async def _is_already_completed(self, bot_username: str, parent_task_id: Optional[str] = None) -> bool:
        """التحقق من إكمال المهمة مسبقاً.
        الإصلاح: الفحص يشمل parent_task_id حتى لا تتخطى المهام المتكررة لنفس البوت.
        """
        try:
            q = supabase.table('completed_tasks_history') \
                .select('id') \
                .eq('session_id', self.session_id) \
                .eq('bot_username', bot_username)
            if parent_task_id:
                q = q.eq('parent_task_id', parent_task_id)
            else:
                q = q.is_('parent_task_id', 'null')
            response = await async_supabase_query(lambda: q.execute())
            return len(response.data) > 0 if response.data else False
        except Exception:
            return False

    async def _handle_join(self, task: Dict[str, Any]) -> bool:
        """معالجة مهمة الانضمام"""
        try:
            target_link = task.get('target_bot_link', '')
            ref_id = None

            # استخراج ref_id من الرابط
            if 't.me/' in target_link:
                entity_part = target_link.split('t.me/')[-1]
                if '?' in entity_part:
                    entity = entity_part.split('?')[0]
                    if '?start=' in target_link:
                        ref_id = target_link.split('?start=')[-1]
                else:
                    entity = entity_part
            else:
                entity = target_link
                if '?start=' in entity:
                    ref_id = entity.split('?start=')[-1]
                    entity = entity.split('?')[0]

            # إذا كان بوت، أرسل /start
            if entity.lower().endswith('bot'):
                payload = f'/start {ref_id}' if ref_id else '/start'
                await self.client.send_message(entity, payload)
                return True

            # إذا كان مجموعة برابط دعوة
            if entity.startswith('+'):
                await self.client(ImportChatInviteRequest(entity[1:]))
            else:
                await self.client(JoinChannelRequest(entity))

            return True

        except UserAlreadyParticipantError:
            return True
        except FloodWaitError as e:
            logger.warning(f"FloodWait joining: {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 60))
            return False
        except Exception as e:
            logger.error(f"Error joining: {e}")
            return False

    async def _handle_follow_channel(self, task: Dict[str, Any]) -> bool:
        """معالجة مهمة متابعة قناة - v2.0.2: يدعم channel_list (1-15 قناة)"""
        try:
            channels = []
            # 1) قائمة القنوات من channel_list
            raw = task.get('channel_list', '[]')
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, list):
                    channels = [str(c).strip() for c in parsed if str(c).strip()]
            except Exception:
                channels = []
            # 2) الهدف الرئيسي (إن وجد)
            target = task.get('target_bot_link', '')
            if 't.me/' in target:
                target = target.split('t.me/')[-1].split('?')[0].split('/')[0]
            if target:
                channels.insert(0, target)
            # إزالة التكرار والحفاظ على الترتيب
            channels = list(dict.fromkeys(channels))
            if not channels:
                logger.warning(f"Follow channel: no channels in task {task.get('id')}")
                return False
            joined = 0
            for ch in channels:
                try:
                    entity = await self.client.get_input_entity(ch)
                    await self.client(JoinChannelRequest(entity))
                    joined += 1
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                except UserAlreadyParticipantError:
                    joined += 1
                except FloodWaitError as e:
                    logger.warning(f"FloodWait follow channel: {e.seconds}s")
                    await asyncio.sleep(min(e.seconds, 60))
                except Exception as e:
                    logger.error(f"Error joining {ch}: {e}")
            return joined > 0
        except Exception as e:
            logger.error(f"Follow channel error: {e}")
            return False

    async def _handle_react_post(self, task: Dict[str, Any]) -> bool:
        """معالجة مهمة التفاعل على منشور"""
        try:
            msg_link = task.get('target_message_link', '')
            emoji = task.get('emoji_target', '👍')

            if msg_link:
                parts = msg_link.split('/')
                channel = parts[-2]
                msg_id = int(parts[-1])

                if emoji == 'random':
                    emojis = ['👍', '❤️', '🔥', '👏', '😊', '💯', '⚡', '🎉']
                    emoji = random.choice(emojis)

                entity = await self.client.get_input_entity(channel)
                await self.client.send_reaction(entity, msg_id, emoji)
                return True
            return False
        except FloodWaitError as e:
            logger.warning(f"FloodWait react: {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 60))
            return False
        except Exception:
            return False

    async def _handle_vote_poll(self, task: Dict[str, Any]) -> bool:
        """معالجة مهمة التصويت"""
        try:
            msg_link = task.get('target_message_link', '')
            option = task.get('vote_option', '0')

            if msg_link:
                parts = msg_link.split('/')
                channel = parts[-2]
                msg_id = int(parts[-1])

                entity = await self.client.get_input_entity(channel)
                msg = await self.client.get_messages(entity, ids=msg_id)

                if msg and msg.poll:
                    await msg.click(text=option)
                    return True
            return False
        except Exception:
            return False

    async def _handle_forward_task(self, task: Dict[str, Any]) -> bool:
        """معالجة مهمة إعادة التوجيه"""
        try:
            target_bot = task['target_bot_link']
            source_link = task.get('target_message_link', '')

            if 't.me/' in target_bot:
                target_bot = target_bot.split('t.me/')[-1].split('?')[0]

            if source_link:
                parts = source_link.split('/')
                source_channel = parts[-2]
                source_msg_id = int(parts[-1])

                source_entity = await self.client.get_input_entity(source_channel)
                target_entity = await self.client.get_input_entity(target_bot)

                msg = await self.client.get_messages(source_entity, ids=source_msg_id)
                if msg:
                    await self.client.forward_messages(target_entity, msg)
                    return True
            return False
        except FloodWaitError as e:
            logger.warning(f"FloodWait forward: {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 60))
            return False
        except Exception:
            return False

    async def _handle_verify(self, task: Dict[str, Any]) -> bool:
        """معالجة مهمة التحقق"""
        try:
            target_bot = task['target_bot_link'].split('t.me/')[-1].split('?')[0]
            bot_entity = await self.client.get_input_entity(target_bot)

            await self.client.send_message(bot_entity, '/start')
            await asyncio.sleep(random.uniform(2, 5))

            messages = await self.client.get_messages(bot_entity, limit=5)
            for msg in messages:
                if msg.reply_markup:
                    for row in msg.reply_markup.rows:
                        for button in row.buttons:
                            if any(kw in (button.text or '').lower()
                                   for kw in ['verify', 'تحقق', 'confirm', 'تأكيد']):
                                await button.click()
                                return True
            return False
        except Exception:
            return False

    async def _handle_click(self, task: Dict[str, Any]) -> bool:
        """معالجة مهمة النقر"""
        try:
            target_bot = task['target_bot_link'].split('t.me/')[-1]
            bot_entity = await self.client.get_input_entity(target_bot)

            messages = await self.client.get_messages(bot_entity, limit=5)
            for msg in messages:
                if msg.reply_markup:
                    for row in msg.reply_markup.rows:
                        for button in row.buttons:
                            try:
                                if button.url:
                                    continue
                                await button.click()
                                await asyncio.sleep(random.uniform(1, 3))
                            except Exception:
                                pass
            return True
        except Exception:
            return False

    async def _handle_solve(self, task: Dict[str, Any]) -> bool:
        """معالجة مهمة الحل الآلي - v3.0 AI"""
        try:
            target_bot = task['target_bot_link'].split('t.me/')[-1].split('?')[0]
            bot_entity = await self.client.get_input_entity(target_bot)
            messages = await self.client.get_messages(bot_entity, limit=10)
            for msg in messages:
                if not msg.text:
                    continue
                # v3.0 use AI analyzer if available
                if AI_AVAILABLE and self.ai_analyzer:
                    try:
                        analysis = self.ai_analyzer.analyze(msg.message or "", raw_message=msg)
                    except Exception:
                        analysis = None
                    if analysis is not None and getattr(analysis, 'has_math', False) \
                            and getattr(analysis, 'math_answer', None) is not None:
                        answer = str(analysis.math_answer)
                        for btn in getattr(analysis, 'buttons', []):
                            if answer in btn.text:
                                await msg.click(text=btn.text)
                                return True
                        await self.client.send_message(bot_entity, answer)
                        return True
                else:
                    answer = self.parser.solve_math_expression(msg.text)
                    if answer:
                        buttons = self.parser.extract_buttons(msg)
                        for button in buttons:
                            if str(answer) in button:
                                await msg.click(text=button)
                                return True
                        await self.client.send_message(bot_entity, str(answer))
                        return True
            return False
        except Exception:
            return False

    async def _handle_start(self, task: Dict[str, Any]) -> bool:
        """4.1 مهمة start - إرسال /start مع ref_id"""
        try:
            target_link = task.get('target_bot_link', '')
            bot_username = target_link.split('t.me/')[-1].split('?')[0] if 't.me/' in target_link else target_link
            ref_id = None
            if '?start=' in target_link:
                ref_id = target_link.split('?start=')[-1]
            entity = await self.client.get_input_entity(bot_username)
            payload = f"/start {ref_id}" if ref_id else "/start"
            await self.client.send_message(entity, payload)
            logger.info(f"Start sent to {bot_username}: {payload}")
            return True
        except Exception as e:
            logger.error(f"Start error: {e}")
            return False

    async def _handle_subscribe(self, task: Dict[str, Any]) -> bool:
        """4.2 اشتراك - v3.0 يدعم 1-15 قناة بذكاء"""
        try:
            if AI_AVAILABLE and self.ai_executor:
                # Use AI executor
                # Get recent message to analyze
                bot_username = task.get('target_bot_link', '').split('t.me/')[-1].split('?')[0] if 't.me/' in task.get('target_bot_link', '') else task.get('target_bot_link', '')
                try:
                    entity = await self.client.get_input_entity(bot_username)
                    msgs = await self.client.get_messages(entity, limit=3)
                    for msg in msgs:
                        analysis = self.ai_analyzer.analyze(msg.message or "", raw_message=msg)
                        if analysis is not None and getattr(analysis, 'has_subscribe', False):
                            return await self.ai_executor.execute_subscribe_all(self.client, entity, analysis, speed=task.get('speed', 'medium'))
                except Exception:
                    pass

            # Fallback to channel_list
            channel_list = task.get('channel_list', '[]')
            if channel_list:
                try:
                    channels = json.loads(channel_list) if isinstance(channel_list, str) else channel_list
                except Exception:
                    channels = []
                if channels:
                    for ch in channels[:15]:
                        try:
                            entity = await self.client.get_input_entity(ch)
                            await self.client(JoinChannelRequest(entity))
                            await asyncio.sleep(random.uniform(0.5, 1.5))
                        except Exception:
                            pass
                    return True

            # Fallback generic
            return await self._handle_join(task)
        except Exception as e:
            logger.error(f"Subscribe error: {e}")
            return False

    async def _handle_phone(self, task: Dict[str, Any]) -> bool:
        """4.5 phone - مشاركة مباشرة أو تحويل"""
        try:
            bot_username = task.get('target_bot_link', '').split('t.me/')[-1].split('?')[0] if 't.me/' in task.get('target_bot_link', '') else task.get('target_bot_link', '')
            entity = await self.client.get_input_entity(bot_username)
            msgs = await self.client.get_messages(entity, limit=3)
            for msg in msgs:
                if AI_AVAILABLE and self.ai_analyzer:
                    try:
                        analysis = self.ai_analyzer.analyze(msg.message or "", raw_message=msg)
                    except Exception:
                        analysis = None
                    if analysis is not None and getattr(analysis, 'has_phone_request', False):
                        phone_link = task.get('target_message_link', '')
                        if AI_AVAILABLE and self.ai_executor:
                            return await self.ai_executor.execute_phone_share(self.client, entity, analysis, phone_link, speed=task.get('speed', 'medium'))

                # Fallback: try click contact button
                try:
                    buttons = self.parser.extract_buttons(msg) if hasattr(self.parser, 'extract_buttons') else []
                    for b in buttons:
                        if 'contact' in b.lower() or 'رقم' in b:
                            await msg.click(text=b)
                            return True
                except Exception:
                    pass
            return False
        except Exception as e:
            logger.error(f"Phone error: {e}")
            return False

    async def _handle_emoji(self, task: Dict[str, Any]) -> bool:
        """4.6 emoji - مطابقة الإيموجي"""
        try:
            if AI_AVAILABLE and self.ai_executor and self.ai_analyzer:
                bot_username = task.get('target_bot_link', '').split('t.me/')[-1].split('?')[0] if 't.me/' in task.get('target_bot_link', '') else task.get('target_bot_link', '')
                entity = await self.client.get_input_entity(bot_username)
                msgs = await self.client.get_messages(entity, limit=5)
                for msg in msgs:
                    analysis = self.ai_analyzer.analyze(msg.message or "", raw_message=msg)
                    if analysis is not None and getattr(analysis, 'has_emoji_challenge', False):
                        return await self.ai_executor.execute_emoji(self.client, entity, analysis, speed=task.get('speed', 'medium'))
            return False
        except Exception:
            return False

    async def _handle_language(self, task: Dict[str, Any]) -> bool:
        """4.7 language - اختيار English افتراضياً"""
        try:
            if AI_AVAILABLE and self.ai_executor and self.ai_analyzer:
                bot_username = task.get('target_bot_link', '').split('t.me/')[-1].split('?')[0] if 't.me/' in task.get('target_bot_link', '') else task.get('target_bot_link', '')
                entity = await self.client.get_input_entity(bot_username)
                msgs = await self.client.get_messages(entity, limit=5)
                for msg in msgs:
                    analysis = self.ai_analyzer.analyze(msg.message or "", raw_message=msg)
                    if analysis is None:
                        continue
                    # Check for language buttons
                    for btn in getattr(analysis, 'buttons', []):
                        if 'english' in btn.text.lower() or getattr(btn, 'button_type', '') == 'language':
                            return await self.ai_executor.execute_language(self.client, entity, analysis, speed=task.get('speed', 'medium'))
            return False
        except Exception:
            return False

    async def _handle_text(self, task: Dict[str, Any]) -> bool:
        """4.8 text - إرسال نص محدد"""
        try:
            bot_username = task.get('target_bot_link', '').split('t.me/')[-1].split('?')[0] if 't.me/' in task.get('target_bot_link', '') else task.get('target_bot_link', '')
            text_to_send = task.get('solve_pattern') or task.get('target_message_link') or "Hello"
            # If composite_steps contains text, use that
            steps = task.get('composite_steps', '[]')
            try:
                steps_json = json.loads(steps) if isinstance(steps, str) else steps
                for s in steps_json:
                    if s.get('type') == 'text' and s.get('text_to_send'):
                        text_to_send = s.get('text_to_send')
                        break
            except Exception:
                pass
            entity = await self.client.get_input_entity(bot_username)
            await self.client.send_message(entity, text_to_send)
            return True
        except Exception as e:
            logger.error(f"Text error: {e}")
            return False

    async def _handle_visit(self, task: Dict[str, Any]) -> bool:
        """4.9 visit - زيارة رابط"""
        try:
            bot_username = task.get('target_bot_link', '').split('t.me/')[-1].split('?')[0] if 't.me/' in task.get('target_bot_link', '') else task.get('target_bot_link', '')
            entity = await self.client.get_input_entity(bot_username)
            msgs = await self.client.get_messages(entity, limit=5)
            for msg in msgs:
                if msg.reply_markup:
                    # Look for url buttons
                    if hasattr(msg.reply_markup, 'rows'):
                        for row in msg.reply_markup.rows:
                            for btn in row.buttons:
                                if getattr(btn, 'url', None):
                                    await msg.click(text=btn.text)
                                    logger.info(f"Visit clicked: {btn.text} -> {btn.url}")
                                    return True
            return False
        except Exception as e:
            logger.error(f"Visit error: {e}")
            return False


# ============================================
# SESSION WORKER (محسن)
# ============================================
class SessionWorker:
    """Manages individual session lifecycle"""

    def __init__(self, session_data: Dict[str, Any], proxy_pool: ProxyPoolManager, memory_manager: MemoryManager, template_engine: TemplateLearningEngine):
        self.session_data = session_data
        self.proxy_pool = proxy_pool
        self.memory_manager = memory_manager
        self.template_engine = template_engine
        self.client = None
        self.processor = None
        self.is_active = False
        self.consecutive_errors = 0
        self.max_errors = 5

    async def initialize(self) -> bool:
        """تهيئة الجلسة"""
        try:
            proxy_config = await self.proxy_pool.assign_proxy_for_session(
                self.session_data['id'],
                self.session_data.get('phone', '')
            )

            self.client = TelegramClient(
                StringSession(self.session_data['session_string']),
                self.session_data.get('api_id', API_ID),
                self.session_data.get('api_hash', API_HASH),
                proxy=proxy_config,
                connection_retries=3,
                retry_delay=2,
                auto_reconnect=False  # تعطيل إعادة الاتصال التلقائي لتوفير الموارد
            )

            await self.client.connect()

            if not await self.client.is_user_authorized():
                await self._deactivate('Session not authorized')
                return False

            self.processor = TaskProcessor(
                self.client, self.session_data['id'], self.template_engine
            )

            if not await self.processor.initialize():
                return False

            self.is_active = True
            self.consecutive_errors = 0

            await async_supabase_query(
                lambda: supabase.table('client_sessions').update({
                    'last_used_at': datetime.now(timezone.utc).isoformat()
                }).eq('id', self.session_data['id']).execute()
            )

            logger.info(f"Session initialized: {self.session_data.get('phone', 'unknown')}")
            return True

        except UserDeactivatedError:
            await self._deactivate('User deactivated')
            return False
        except AuthKeyError:
            await self._deactivate('Auth key invalid')
            return False
        except PhoneNumberBannedError:
            await self._deactivate('Phone banned')
            return False
        except FloodWaitError as e:
            logger.warning(f"FloodWait initializing session: {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 120))
            return False
        except Exception as e:
            logger.error(f"Failed to initialize session: {e}")
            return False

    async def _deactivate(self, reason: str):
        """تعطيل الجلسة"""
        is_banned = any(w in reason.lower() for w in ['ban', 'deactivate', 'invalid'])

        await async_supabase_query(
            lambda: supabase.table('client_sessions').update({
                'is_active': False,
                'is_banned': is_banned,
                'error_message': reason[:500]
            }).eq('id', self.session_data['id']).execute()
        )

        await self.proxy_pool.release_proxy(self.session_data['id'])
        logger.warning(f"Session deactivated: {reason}")

    async def process_tasks(self) -> Tuple[int, int]:
        """معالجة المهام الخاصة بالجلسة.
        الإصلاح: لا يعدّل retry_count هنا (يتم في process_task)،
        ويعيد (نجحت، فشلت) للإحصائيات.
        """
        if not self.is_active or not self.processor:
            return (0, 0)

        try:
            response = await async_supabase_query(
                lambda: supabase.table('tasks_queue').select('*')
                .eq('session_id', self.session_data['id'])
                .eq('status', 'pending')
                .lt('retry_count', MAX_RETRIES)
                .order('created_at')
                .limit(3)
                .execute()
            )

            if not response.data:
                return (0, 0)

            processed = 0
            failed = 0
            for task in response.data:
                try:
                    success = await self.processor.process_task(task)

                    if success:
                        processed += 1
                        self.consecutive_errors = 0
                    else:
                        failed += 1
                        self.consecutive_errors += 1

                    if self.consecutive_errors >= self.max_errors:
                        await self._deactivate('Too many consecutive errors')
                        break

                    delay = random.uniform(3, 8)
                    await asyncio.sleep(delay)

                except FloodWaitError as e:
                    logger.warning(f"FloodWait processing task: {e.seconds}s")
                    await asyncio.sleep(min(e.seconds, 120))
                    self.consecutive_errors += 1
                except Exception as e:
                    logger.error(f"Error on task {task.get('id')}: {e}")
                    self.consecutive_errors += 1

            return (processed, failed)

        except Exception as e:
            logger.error(f"Error in process_tasks: {e}")
            return (0, 0)

    async def cleanup(self):
        """تنظيف الجلسة"""
        try:
            if self.client:
                await self.client.disconnect()
            self.is_active = False
            await self.proxy_pool.release_proxy(self.session_data['id'])
        except Exception:
            pass

    async def log_task(self, bot_username: str, task_type: str, status: str, message: str, parent_task_id: str = None):
        try:
            await async_supabase_query(
                lambda: supabase.table('task_logs').insert({
                    'session_id': self.session_data['id'],
                    'bot_username': bot_username,
                    'task_type': task_type,
                    'status': status,
                    'message': message[:500] if message else '',
                    'parent_task_id': parent_task_id
                }).execute()
            )
        except Exception:
            pass


# ============================================
# WORKER ENGINE (محسن)
# ============================================
class WorkerEngine:
    """Main orchestrator for session management and task execution"""

    def __init__(self):
        self.memory_manager = MemoryManager(max_memory_mb=250)
        self.proxy_pool = ProxyPoolManager()
        self.template_engine = TemplateLearningEngine()
        self.active_sessions = {}
        self.is_running = False
        self.last_session_time = {}
        self.stats = {
            'tasks_completed': 0,
            'tasks_failed': 0,
            'sessions_used': 0,
            'start_time': datetime.now(timezone.utc)
        }

    async def get_pending_sessions(self) -> List[Dict[str, Any]]:
        """جلب الجلسات النشطة الجاهزة للعمل.
        الإصلاح: يستبعد الجلسات بدون session_string (منع KeyError لاحقاً).
        """
        try:
            response = await async_supabase_query(
                lambda: supabase.table('client_sessions').select('*')
                .eq('is_active', True)
                .eq('is_banned', False)
                .order('added_at', desc=True, nullsfirst=False)
                .execute()
            )
            sessions = [s for s in (response.data or []) if s.get('session_string')]
            return sessions
        except Exception as e:
            logger.error(f"Error fetching sessions: {e}")
            return []

    async def get_pending_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """جلب المهام المعلقة"""
        try:
            response = await async_supabase_query(
                lambda: supabase.table('tasks_queue').select('*')
                .eq('status', 'pending')
                .order('created_at')
                .limit(limit)
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching tasks: {e}")
            return []

    async def get_unassigned_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """جلب المهام غير المعينة - FIXED: is_('session_id', 'null')"""
        try:
            response = await async_supabase_query(
                lambda: supabase.table('tasks_queue').select('*')
                .eq('status', 'pending')
                .is_('session_id', 'null')  # FIXED v2.0.1: 'null' بدلاً من None
                .order('created_at')
                .limit(limit)
                .execute()
            )
            return response.data if response.data else []
        except Exception as e:
            logger.error(f"Error fetching unassigned tasks: {e}")
            return []

    async def _sweep_stuck_tasks(self):
        """تنظيف المهام العالقة: pending مع retry_count >= MAX_RETRIES"""
        try:
            updated = await async_supabase_query(
                lambda: supabase.table('tasks_queue').update({
                    'status': 'failed',
                    'error_message': 'Max retries exceeded (stuck pending)',
                    'completed_at': datetime.now(timezone.utc).isoformat()
                }).eq('status', 'pending').gte('retry_count', MAX_RETRIES).execute()
            )
            if updated.data:
                logger.info(f"Swept {len(updated.data)} stuck tasks (retry >= {MAX_RETRIES})")
        except Exception as e:
            logger.debug(f"Sweep error: {e}")

    async def assign_tasks(self, sessions: List[Dict[str, Any]], tasks: List[Dict[str, Any]]):
        """توزيع المهام على الجلسات - FIXED v3.0 مع parent_task_id"""
        if not tasks or not sessions:
            return

        for task in tasks:
            # تخطي المهام التي تم تعيينها مسبقاً أو هي child
            if task.get('session_id') or task.get('parent_task_id'):
                continue

            tid = task.get('id')
            if not tid:
                continue

            # استخراج اسم البوت
            bot_username = task.get('target_bot_link', '')
            if 't.me/' in bot_username:
                bot_username = bot_username.split('t.me/')[-1].split('?')[0].split('/')[0]
            # للمهام التي تستخدم target_message_link (react, vote, forward)
            if not bot_username and task.get('target_message_link'):
                bot_username = task.get('target_message_link', '').split('t.me/')[-1].split('/')[0] if 't.me/' in task.get('target_message_link', '') else 'unknown'
            parent_id = tid

            # 1. تصفية الجلسات: كل حساب يفحص سجله الخاص فقط مع parent_task_id
            eligible_sessions = []
            for session in sessions:
                already_done = await self._is_task_completed(session['id'], bot_username, parent_id)
                if not already_done:
                    eligible_sessions.append(session)

            if not eligible_sessions:
                logger.info(f"Task {parent_id[:8]} already completed by all sessions. Marking parent completed.")
                await async_supabase_query(
                    lambda: supabase.table('tasks_queue').update({
                        'status': 'completed',
                        'completed_at': datetime.now(timezone.utc).isoformat()
                    }).eq('id', parent_id).execute()
                )
                continue

            # 2. تحديد عدد الحسابات المطلوبة
            target_count = task.get('required_accounts') or len(eligible_sessions)
            try:
                target_count = int(target_count)
            except (TypeError, ValueError):
                target_count = len(eligible_sessions)
            actual_count = min(target_count, len(eligible_sessions))

            # 3. تحديث المهمة الأصلية لتصبح parent (multi_account)
            await async_supabase_query(
                lambda: supabase.table('tasks_queue').update({
                    'multi_account': True if actual_count > 1 else False,
                    'status': 'processing'  # parent قيد التوزيع
                }).eq('id', parent_id).execute()
            )

            # 4. استنساخ لكل حساب مع parent_task_id
            skip_keys = {'id', 'created_at', 'updated_at', 'started_at', 'completed_at'}
            for i in range(actual_count):
                session = eligible_sessions[i]
                # بناء المهمة الفرعية
                new_task = {k: v for k, v in task.items() if k not in skip_keys}
                new_task['session_id'] = session['id']
                new_task['parent_task_id'] = parent_id
                new_task['status'] = 'pending'
                new_task['multi_account'] = False
                try:
                    await async_supabase_query(
                        lambda s=session, nt=new_task: supabase.table('tasks_queue').insert(nt).execute()
                    )
                    logger.debug(f"Cloned child task for {session.get('phone', 'unknown')} parent {parent_id[:8]}")
                except Exception as e:
                    logger.error(f"Error cloning for {session.get('phone')}: {e}")

            logger.info(f"Task {parent_id[:8]} distributed to {actual_count} accounts (parent).")
            # لا نعلم parent completed الآن - سيتم بعد انتهاء كل الأطفال

    async def _is_task_completed(self, session_id: str, bot_username: str, parent_task_id: str = None) -> bool:
        """التحقق من إكمال المهمة - v3.0 يفحص سجل الحساب الخاص مع parent_task_id"""
        try:
            query = supabase.table('completed_tasks_history').select('id') \
                .eq('session_id', session_id).eq('bot_username', bot_username)
            if parent_task_id:
                query = query.eq('parent_task_id', parent_task_id)
            response = await async_supabase_query(lambda: query.execute())
            return len(response.data) > 0 if response.data else False
        except Exception:
            return False

    async def _check_parent_completion(self, parent_task_id: str):
        """فحص هل كل الأطفال اكتملوا، وإذا نعم علم الأب completed وأرسل تقرير.
        الإصلاح: يعمل لكل الآباء (حساب واحد أو عدة)، ويعلّم الأب failed
        إذا لم يجد أطفالاً إطلاقاً (مهمة معطوبة بدل تعليق للأبد).
        """
        try:
            # جلب كل الأطفال
            children = await async_supabase_query(
                lambda: supabase.table('tasks_queue').select('id,status,session_id,error_message')
                .eq('parent_task_id', parent_task_id).execute()
            )
            if not children.data:
                # لا يوجد أطفال: مهمة معطوبة - علّمها failed بدل تركها للأبد
                await async_supabase_query(
                    lambda: supabase.table('tasks_queue').update({
                        'status': 'failed',
                        'error_message': 'No child tasks found',
                        'completed_at': datetime.now(timezone.utc).isoformat()
                    }).eq('id', parent_task_id).execute()
                )
                logger.warning(f"Parent {parent_task_id[:8]} has no children - marked failed")
                return

            total = len(children.data)
            completed = sum(1 for c in children.data if c['status'] in ['completed', 'failed'])
            if completed < total:
                return  # ما زال في أطفال قيد التنفيذ

            # كل الأطفال انتهوا
            # جلب معلومات الأب
            parent_resp = await async_supabase_query(
                lambda: supabase.table('tasks_queue').select('target_bot_link,task_type').eq('id', parent_task_id).execute()
            )
            bot_username = parent_resp.data[0].get('target_bot_link', 'unknown') if parent_resp.data else 'unknown'
            if 't.me/' in bot_username:
                bot_username = bot_username.split('t.me/')[-1].split('?')[0]

            # حساب النجاح
            success_count = sum(1 for c in children.data if c['status'] == 'completed')

            # تحديث الأب
            await async_supabase_query(
                lambda: supabase.table('tasks_queue').update({
                    'status': 'completed',
                    'completed_at': datetime.now(timezone.utc).isoformat()
                }).eq('id', parent_task_id).execute()
            )
            logger.info(f"Parent {parent_task_id[:8]} completed: {success_count}/{total}")

            # إرسال تقرير
            try:
                if AI_AVAILABLE:
                    from ai_agent import ReportGenerator
                    bot_token = os.getenv('BOT_TOKEN')
                    admin_group = os.getenv('ADMIN_GROUP_ID')
                    if bot_token and admin_group:
                        # جمع تفاصيل كل حساب
                        results = []
                        for child in children.data:
                            sess_id = child.get('session_id')
                            status = child['status']
                            # جلب رقم الهاتف
                            phone = 'unknown'
                            try:
                                sess = await async_supabase_query(lambda: supabase.table('client_sessions').select('phone').eq('id', sess_id).execute())
                                if sess.data:
                                    phone = sess.data[0].get('phone', 'unknown')
                            except Exception:
                                pass
                            results.append({
                                'phone': phone,
                                'success': status == 'completed',
                                'reason': child.get('error_message', '') if status == 'failed' else ''
                            })

                        # حساب الوقت
                        rg = ReportGenerator(supabase, None, None)
                        # حاول إرسال عبر Bot إذا متاح
                        try:
                            from aiogram import Bot
                            bot_obj = Bot(token=bot_token)
                            rg2 = ReportGenerator(supabase, bot_obj, int(admin_group))
                            await rg2.send_task_report(parent_task_id, bot_username, results, 0, proxy_count=0)
                            await bot_obj.session.close()
                        except Exception as e:
                            logger.debug(f"Report send error: {e}")
            except Exception as e:
                logger.debug(f"Parent report error: {e}")
        except Exception as e:
            logger.error(f"Parent completion check error: {e}")

    async def process_session(self, session_data: Dict[str, Any]) -> Tuple[int, int]:
        """معالجة المهام لجلسة واحدة - v3.0
        الإصلاح: يسجل الجلسة في active_sessions (إدارة ذاكرة حقيقية)
        ويعيد (نجحت، فشلت) لتحديث الإحصائيات.
        """
        phone = session_data.get('phone', 'unknown')
        session_id = session_data['id']

        # التحقق من cooldown v3.0: بين الحسابات 30-300 ثانية عشوائي
        last_time = self.last_session_time.get(session_id)
        if last_time:
            elapsed = (datetime.now(timezone.utc) - last_time).total_seconds()
            try:
                min_c = 30
                max_c = 300
                min_env = os.getenv('AI_DELAY_BETWEEN_ACCOUNTS_MIN')
                max_env = os.getenv('AI_DELAY_BETWEEN_ACCOUNTS_MAX')
                if min_env and max_env:
                    min_c = int(min_env)
                    max_c = int(max_env)
                min_cooldown = random.uniform(min_c, max_c)
            except Exception:
                min_cooldown = random.uniform(30, 300)
            if elapsed < min_cooldown:
                wait = min_cooldown - elapsed
                logger.debug(f"Cooldown v3 for {phone}: {wait:.1f}s (30-300)")
                await asyncio.sleep(wait)

        worker = SessionWorker(
            session_data, self.proxy_pool, self.memory_manager, self.template_engine
        )
        tasks_done = 0
        tasks_failed = 0

        # تسجيل الجلسة لمدير الذاكرة
        self.active_sessions[session_id] = worker

        try:
            if await worker.initialize():
                tasks_done, tasks_failed = await worker.process_tasks()
                self.last_session_time[session_id] = datetime.now(timezone.utc)

                if tasks_done > 0:
                    self.stats['sessions_used'] += 1
        except Exception as e:
            logger.error(f"Error processing session {phone}: {e}")
        finally:
            await worker.cleanup()
            self.active_sessions.pop(session_id, None)

        # تنظيف الذاكرة بعد كل جلسة
        await self.memory_manager.cleanup(self.active_sessions)

        self.stats['tasks_completed'] += tasks_done
        self.stats['tasks_failed'] += tasks_failed

        return (tasks_done, tasks_failed)

    async def run(self):
        """الحلقة الرئيسية للمحرك"""
        logger.info("=" * 60)
        logger.info("Worker Engine Starting...")
        logger.info(f"Time: {datetime.now(timezone.utc)}")
        logger.info(f"Max Memory: {self.memory_manager.max_memory_mb}MB")
        logger.info("=" * 60)

        self.is_running = True

        while self.is_running:
            try:
                # التحقق من اتصال قاعدة البيانات
                try:
                    await async_supabase_query(
                        lambda: supabase.table('settings').select('key').limit(1).execute()
                    )
                except Exception as e:
                    logger.error(f"Database connection lost: {e}")
                    await asyncio.sleep(30)
                    continue

                # تنظيف المهام العالقة
                if STUCK_TASK_SWEEP:
                    await self._sweep_stuck_tasks()

                # جلب الجلسات والمهام
                sessions = await self.get_pending_sessions()

                if not sessions:
                    logger.info("No active sessions, waiting...")
                    await asyncio.sleep(60)
                    continue

                # جلب المهام غير المعينة
                unassigned_tasks = await self.get_unassigned_tasks(20)

                # توزيع المهام
                if unassigned_tasks:
                    await self.assign_tasks(sessions, unassigned_tasks)

                # جلب جميع المهام المعلقة
                tasks = await self.get_pending_tasks(20)

                if not tasks:
                    logger.info("No pending tasks, waiting...")
                    await asyncio.sleep(30)
                    continue

                logger.info(f"Processing: {len(sessions)} sessions, {len(tasks)} tasks")

                # معالجة كل جلسة
                for session_data in sessions:  # v2.1.5: معالجة كل الجلسات (لا حد أقصى)
                    try:
                        done, failed = await self.process_session(session_data)
                        if done > 0 or failed > 0:
                            logger.info(f"Session {session_data.get('phone')}: {done} done, {failed} failed")
                    except Exception as e:
                        logger.error(f"Session loop error: {e}")

                    # تأخير بين الجلسات
                    await asyncio.sleep(random.uniform(8, 15))

                # v3.0: فحص اكتمال الآباء وإرسال تقارير
                # FIXED: بدون فلتر multi_account حتى تُغلق مهام الحساب الواحد أيضاً
                try:
                    parents = await async_supabase_query(
                        lambda: supabase.table('tasks_queue').select('id')
                        .eq('status', 'processing')
                        .is_('parent_task_id', 'null')  # FIXED v2.0.1: 'null' بدلاً من None
                        .limit(5)
                        .execute()
                    )
                    for p in (parents.data or []):
                        await self._check_parent_completion(p['id'])
                except Exception as e:
                    logger.debug(f"Parent check loop error: {e}")

                # طباعة الإحصائيات
                total_tasks = self.stats['tasks_completed'] + self.stats['tasks_failed']
                if total_tasks > 0 and total_tasks % 10 == 0:
                    uptime = datetime.now(timezone.utc) - self.stats['start_time']
                    logger.info(
                        f"Stats: {self.stats['tasks_completed']} completed, "
                        f"{self.stats['tasks_failed']} failed | "
                        f"Memory: {self.memory_manager.get_current_usage_mb():.1f}MB | "
                        f"Uptime: {uptime}"
                    )

                await asyncio.sleep(5)

            except KeyboardInterrupt:
                logger.info("Worker stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}")
                await asyncio.sleep(30)

        logger.info("Worker engine stopped")

    async def stop(self):
        """إيقاف المحرك بشكل آمن"""
        self.is_running = False
        # إيقاف جميع الجلسات النشطة
        for sid, worker in list(self.active_sessions.items()):
            try:
                await worker.cleanup()
            except Exception:
                pass
            self.active_sessions.pop(sid, None)
        logger.info("Stopping worker engine...")


# ============================================
# BACKGROUND TASKS
# ============================================
async def heartbeat():
    """إرسال نبضات دورية لقاعدة البيانات"""
    while True:
        try:
            await async_supabase_query(
                lambda: supabase.table('settings').upsert({
                    'key': 'worker_last_heartbeat',
                    'value': datetime.now(timezone.utc).isoformat(),
                    'updated_at': datetime.now(timezone.utc).isoformat()
                }, on_conflict='key').execute()
            )
            logger.debug("Heartbeat sent")
        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
        await asyncio.sleep(60)


async def clean_expired_sessions():
    """تنظيف الجلسات المنتهية الصلاحية"""
    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()
            response = await async_supabase_query(
                lambda: supabase.table('inventory').select('*')
                .eq('status', 'sold')
                .lt('session_expires_at', now)
                .execute()
            )

            if response.data:
                for item in response.data:
                    await async_supabase_query(
                        lambda: supabase.table('inventory').update({
                            'status': 'expired',
                            'session_expires_at': None
                        }).eq('id', item['id']).execute()
                    )
                    logger.info(f"Expired session: {item['phone_number']}")
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
        await asyncio.sleep(300)


# ============================================
# MAIN
# ============================================
async def main():
    """نقطة الدخول الرئيسية"""
    logger.info("=" * 60)
    logger.info("Starting Worker Engine v2.3.3 (Professional)")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Platform: {sys.platform}")
    logger.info("=" * 60)

    if not SUPABASE_URL or not SUPABASE_KEY:
        logger.error("Missing Supabase configuration")
        sys.exit(1)
    if not API_ID or not API_HASH:
        logger.error("Missing API credentials")
        sys.exit(1)

    # التحقق من اتصال قاعدة البيانات
    try:
        await async_supabase_query(
            lambda: supabase.table('settings').select('key').limit(1).execute()
        )
        logger.info("Database connection successful")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        sys.exit(1)

    engine = WorkerEngine()

    # تشغيل المهام الخلفية
    heartbeat_task = asyncio.create_task(heartbeat())
    cleaner_task = asyncio.create_task(clean_expired_sessions())

    try:
        await engine.run()
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
    finally:
        await engine.stop()
        heartbeat_task.cancel()
        cleaner_task.cancel()
        try:
            await heartbeat_task
            await cleaner_task
        except asyncio.CancelledError:
            pass
        logger.info("Worker shutdown complete")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
