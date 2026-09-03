#!/usr/bin/env python3
"""
🚀 AlSarab ShopBot v3.0 - AI Agent System (FIXED v3.0.2)
================================================
القاعدة الذهبية: كل ما يواجهه البوت لأول مرة يتعلمه، وكل ما يتعلمه ينفذه تلقائياً في المرات القادمة

المكونات:
1. MessageAnalyzer  - العيون (تحليل الرسائل)
2. DecisionEngine   - العقل (اتخاذ القرارات)
3. TemplateLearner  - الذاكرة (حفظ الأنماط)
4. ActionExecutor   - الأيدي (تنفيذ الإجراءات)

CHANGELOG v3.0.1:
  [FIX] أنماط الرياضيات: \\s المزدوجة (حرفية) كانت تكسر solve:/احسب:/реши:
  [FIX] solve_math: كشف العملية من النص المطابق (يدعم + و - و × و *)
  [FIX] إجابة صفر (0) أصبحت تُرجع int ولا تُعتبر None
  [FIX] أولوية classify_button واضحة (contact > t.me url > كلمات)
  [FIX] execute_with_retry: تصحيح حساب التأخير الأسي base_delay * (2 ** attempt)
  [FIX] حماية كل الاستدعاءات الداخلية من رسائل بدون أزرار

التوافق: Python 3.10+
"""

import asyncio
import logging
import random
import re
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger('AIAgent')

# ============================================================
# أنواع البيانات المساعدة
# ============================================================

@dataclass
class ButtonInfo:
    """معلومات زر واحد"""
    text: str
    url: Optional[str] = None
    has_contact: bool = False
    button_type: str = "unknown"  # subscribe, verify, math_answer, share_phone, url, language, unknown
    confidence: float = 0.0


@dataclass
class AnalysisResult:
    """نتيجة تحليل رسالة"""
    message_text: str
    buttons: List[ButtonInfo] = field(default_factory=list)
    has_math: bool = False
    math_question: Optional[str] = None
    math_answer: Optional[int] = None
    has_subscribe: bool = False
    subscribe_buttons: List[ButtonInfo] = field(default_factory=list)
    has_verify: bool = False
    verify_buttons: List[ButtonInfo] = field(default_factory=list)
    has_phone_request: bool = False
    phone_buttons: List[ButtonInfo] = field(default_factory=list)
    has_url: bool = False
    url_buttons: List[ButtonInfo] = field(default_factory=list)
    has_emoji_challenge: bool = False
    target_emoji: Optional[str] = None
    language_detected: str = "unknown"  # ar, en, ru
    overall_confidence: float = 0.0
    suggested_action: str = "unknown"
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    """قرار محرك القرارات"""
    action: str  # subscribe_all, solve_math, share_phone, click_verify, match_emoji, complete, retry, click_best, fallback
    target_button: Optional[ButtonInfo] = None
    target_text: Optional[str] = None
    confidence: float = 0.0
    reason: str = ""
    use_template: bool = False
    template_id: Optional[str] = None
    fallback_needed: bool = False
    fallback_context: Optional[Dict[str, Any]] = None


# ============================================================
# المكون 1: MessageAnalyzer - العيون
# ============================================================

class MessageAnalyzer:
    """
    محلل الرسائل الذكي - يدعم العربية والإنجليزية والروسية
    يكتشف: أزرار الاشتراك، المسائل الرياضية، طلبات الرقم، أزرار التحقق
    """

    # كلمات مفتاحية بلغات متعددة
    SUBSCRIBE_KEYWORDS = {
        'ar': ['اشتراك', 'اشترك', 'انضم', 'انضمام', 'قناة', 'مجموعة', 'تابع'],
        'en': ['subscribe', 'join', 'channel', 'group', 'follow'],
        'ru': ['подписаться', 'подпишись', 'канал', 'группа', 'вступить']
    }
    VERIFY_KEYWORDS = {
        'ar': ['تحقق', 'تأكيد', 'تأكد', 'فحص', 'تم', 'استمرار', 'متابعة', 'التالي', '✅'],
        'en': ['verify', 'check', 'confirm', 'done', 'continue', 'next', '✅'],
        'ru': ['проверка', 'подтвердить', 'проверить', 'готово', 'далее', '✅']
    }
    LANGUAGE_KEYWORDS = {
        'english': ['english', 'الإنجليزية', 'английский'],
        'arabic': ['العربية', 'arabic', 'арабский'],
        'russian': ['русский', 'russian', 'الروسية']
    }
    PHONE_KEYWORDS = {
        'ar': ['رقم', 'هاتف', 'مشاركة', 'اتصال', 'جوال'],
        'en': ['phone', 'number', 'contact', 'share'],
        'ru': ['номер', 'телефон', 'контакт', 'поделиться']
    }

    # أنماط الرياضيات (FIXED v3.0.1: بدون شرطات مزدوجة خاطئة)
    MATH_PATTERNS = [
        r'(\d+)\s*\+\s*(\d+)\s*=\s*\?',
        r'(\d+)\s*-\s*(\d+)\s*=\s*\?',
        r'(\d+)\s*[×*]\s*(\d+)\s*=\s*\?',
        r'(\d+)\s*\+\s*(\d+)',
        r'(\d+)\s*-\s*(\d+)',
        r'(\d+)\s*[×*]\s*(\d+)',
        r'solve:?\s*(\d+)\s*\+\s*(\d+)',
        r'احسب:?\s*(\d+)\s*\+\s*(\d+)',
        r'реши:?\s*(\d+)\s*\+\s*(\d+)',
        r'(\d+)\s*[\+\-\*×]\s*(\d+)',
    ]

    # إيموجي للكشف
    EMOJI_PATTERN = re.compile(
        r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF'
        r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF'
        r'\u2600-\u26FF\u2700-\u27BF]'
    )

    def __init__(self):
        # تجميع كل كلمات الاشتراك والتحقق والهاتف
        self.all_subscribe = [w for lst in self.SUBSCRIBE_KEYWORDS.values() for w in lst]
        self.all_verify = [w for lst in self.VERIFY_KEYWORDS.values() for w in lst]
        self.all_phone = [w for lst in self.PHONE_KEYWORDS.values() for w in lst]

    # ------------------------------------------------------------------
    def analyze(self, message_text: str = "", buttons: List[Dict[str, Any]] = None, raw_message=None) -> AnalysisResult:
        """
        تحليل شامل لرسالة
        buttons: قائمة أزرار بصيغة dict {text, url, request_contact}
        raw_message: كائن Telethon message الأصلي (اختياري)
        """
        if buttons is None:
            buttons = []
        if message_text is None:
            message_text = ""

        result = AnalysisResult(message_text=message_text)

        # 1. استخراج الأزرار من raw_message إذا وجد
        if raw_message is not None and not buttons:
            buttons = self._extract_buttons_from_message(raw_message)

        # 2. تحليل كل زر وتصنيفه
        button_infos = []
        for btn in buttons:
            btn_text = btn.get('text', '') if isinstance(btn, dict) else str(btn)
            btn_url = btn.get('url') if isinstance(btn, dict) else None
            has_contact = btn.get('request_contact', False) if isinstance(btn, dict) else False
            btype, conf = self._classify_button(btn_text, btn_url, has_contact, message_text)
            info = ButtonInfo(text=btn_text, url=btn_url, has_contact=has_contact,
                              button_type=btype, confidence=conf)
            button_infos.append(info)
        result.buttons = button_infos

        # 3. كشف المسائل الرياضية
        math_ans = self.solve_math(message_text)
        if math_ans is not None:
            result.has_math = True
            result.math_answer = math_ans
            for pat in self.MATH_PATTERNS:
                m = re.search(pat, message_text, re.IGNORECASE)
                if m:
                    result.math_question = m.group(0)
                    break

        # 4. تصنيف الأزرار حسب النوع
        for b in button_infos:
            if b.button_type == "subscribe":
                result.has_subscribe = True
                result.subscribe_buttons.append(b)
            elif b.button_type == "verify":
                result.has_verify = True
                result.verify_buttons.append(b)
            elif b.button_type == "share_phone":
                result.has_phone_request = True
                result.phone_buttons.append(b)
            elif b.button_type == "url":
                result.has_url = True
                result.url_buttons.append(b)

        # 5. كشف عام من النص إذا لم توجد أزرار مصنفة
        lower_text = message_text.lower()
        if not result.has_subscribe and any(k in lower_text for k in self.all_subscribe):
            result.has_subscribe = True
        if any(k in lower_text for k in self.all_phone) \
                or "share" in lower_text or "contact" in lower_text:
            result.has_phone_request = True

        # 6. كشف تحدي الإيموجي
        if raw_message:
            emoji_info = self._detect_emoji_challenge(message_text, raw_message)
            if emoji_info:
                result.has_emoji_challenge = True
                result.target_emoji = emoji_info

        # 7. كشف اللغة
        result.language_detected = self._detect_language(message_text)

        # 8. حساب الثقة العامة واقتراح الإجراء
        result.overall_confidence, result.suggested_action = self._calculate_confidence(result)

        return result

    # ------------------------------------------------------------------
    def _extract_buttons_from_message(self, message) -> List[Dict[str, Any]]:
        """استخراج الأزرار من كائن Telethon"""
        buttons = []
        try:
            if hasattr(message, 'reply_markup') and message.reply_markup:
                # Telethon: message.reply_markup.rows
                if hasattr(message.reply_markup, 'rows'):
                    for row in message.reply_markup.rows:
                        for btn in row.buttons:
                            buttons.append({
                                'text': getattr(btn, 'text', ''),
                                'url': getattr(btn, 'url', None),
                                'request_contact': getattr(btn, 'request_contact', False) or False
                            })
                # aiogram style
                elif hasattr(message.reply_markup, 'inline_keyboard'):
                    for row in message.reply_markup.inline_keyboard:
                        for btn in row:
                            buttons.append({
                                'text': getattr(btn, 'text', ''),
                                'url': getattr(btn, 'url', None),
                                'request_contact': False
                            })
                # ReplyKeyboard
                elif hasattr(message.reply_markup, 'keyboard'):
                    for row in message.reply_markup.keyboard:
                        for btn in row:
                            buttons.append({
                                'text': getattr(btn, 'text', ''),
                                'url': None,
                                'request_contact': getattr(btn, 'request_contact', False)
                            })
        except Exception as e:
            logger.debug(f"Extract buttons error: {e}")
        return buttons

    # ------------------------------------------------------------------
    def _classify_button(self, text: str, url: Optional[str], has_contact: bool, message_text: str) -> Tuple[str, float]:
        """تصنيف زر واحد - FIXED v3.0.1: أولويات واضحة"""
        lower = (text or "").lower().strip()

        # 1) زر مشاركة رقم
        if has_contact or any(k in lower for k in self.all_phone):
            return "share_phone", 95.0

        # 2) رابط (t.me = اشتراك، رابط خارجي = url)
        #    يشمل الحالة التي يكون فيها نص الزر هو الرابط نفسه
        if url or "t.me/" in lower:
            if "t.me/" in (url or lower):
                return "subscribe", 90.0
            return "url", 85.0

        # 3) كلمات الاشتراك
        if any(k in lower for k in self.all_subscribe):
            return "subscribe", 92.0

        # 4) كلمات التحقق
        if any(k in lower for k in self.all_verify):
            return "verify", 90.0

        # 5) زر إجابة رياضية: زر يحتوي على رقم فقط
        if re.match(r'^\s*\d+\s*$', text or ''):
            if self.solve_math(message_text) is not None:
                return "math_answer", 88.0
            return "math_answer", 60.0

        # 6) زر لغة
        for lang, keywords in self.LANGUAGE_KEYWORDS.items():
            if any(k.lower() in lower for k in keywords):
                return "language", 85.0

        return "unknown", 30.0

    # ------------------------------------------------------------------
    def solve_math(self, text: str) -> Optional[int]:
        """حل المسائل الرياضية (+، -، ×) - FIXED v3.0.1"""
        if not text:
            return None
        try:
            for pattern in self.MATH_PATTERNS:
                match = re.search(pattern, text, re.IGNORECASE)
                if not match:
                    continue
                try:
                    num1 = int(match.group(1))
                    num2 = int(match.group(2))
                except (IndexError, ValueError):
                    continue
                chunk = match.group(0)
                if '+' in chunk:
                    return num1 + num2
                if '-' in chunk:
                    return num1 - num2
                if '×' in chunk or '*' in chunk:
                    return num1 * num2
            return None
        except Exception as e:
            logger.debug(f"Math solve error: {e}")
            return None

    # ------------------------------------------------------------------
    def _detect_emoji_challenge(self, message_text: str, raw_message) -> Optional[str]:
        """كشف تحدي مطابقة الإيموجي"""
        try:
            if not raw_message or not hasattr(raw_message, 'reply_markup'):
                return None
            text_emojis = self.EMOJI_PATTERN.findall(message_text or "")
            if not text_emojis:
                return None
            target = text_emojis[0]
            # تحقق هل الأزرار تحتوي على إيموجي (تحدي حقيقي = أزرار للمطابقة)
            buttons = self._extract_buttons_from_message(raw_message)
            for btn in buttons:
                if target in btn.get('text', ''):
                    return target
            # v2.2.3: لا نعتبره تحدياً إذا لم يوجد الإيموجي في الأزرار
            # (رسالة ترحيب فيها 🚀 ليست تحدياً)
            return None
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    def _detect_language(self, text: str) -> str:
        """كشف لغة النص"""
        if not text:
            return "unknown"
        if re.search(r'[\u0600-\u06FF]', text):
            return "ar"
        if re.search(r'[\u0400-\u04FF]', text):
            return "ru"
        return "en"

    # ------------------------------------------------------------------
    def _calculate_confidence(self, result: AnalysisResult) -> Tuple[float, str]:
        """حساب الثقة العامة واقتراح إجراء"""
        if result.has_math and result.math_answer is not None:
            return 95.0, "solve_math"
        if result.has_phone_request and result.phone_buttons:
            return 92.0, "share_phone"
        if result.has_subscribe and result.subscribe_buttons:
            return 88.0, "subscribe_all"
        if result.has_verify and result.verify_buttons:
            return 90.0, "click_verify"
        if result.has_emoji_challenge:
            return 85.0, "match_emoji"
        if result.buttons:
            return 55.0, "click_best"
        lower = (result.message_text or "").lower()
        if "success" in lower or "نجاح" in lower or "успех" in lower:
            return 80.0, "complete"
        if "error" in lower or "خطأ" in lower or "ошибка" in lower:
            return 70.0, "retry"
        return 40.0, "fallback"


# ============================================================
# المكون 2: DecisionEngine - العقل
# ============================================================

class DecisionEngine:
    """
    محرك القرارات الذكي
    الأولوية:
    1. القوالب المحفوظة (نجاح > 80%)
    2. تحليل الموقف الحالي
    3. Fallback إذا confidence < 70%
    """

    def __init__(self, template_learner=None):
        self.template_learner = template_learner

    async def decide(self, analysis: AnalysisResult, bot_username: str,
                     history: List[Dict[str, Any]] = None,
                     template: Optional[Dict[str, Any]] = None) -> Decision:
        """اتخاذ القرار - التوافق مع توقيعين (4 وسائط أو 2 وسيط)"""
        if history is None:
            history = []

        # 1. تحقق من القوالب المحفوظة (نجاح > 80%)
        if template:
            success_rate = self._calc_success_rate(template)
            if success_rate > 80 and analysis.overall_confidence >= 60:
                predicted = await self._predict_from_template(template, analysis)
                if predicted:
                    return Decision(
                        action=predicted['action'],
                        target_button=predicted.get('button'),
                        target_text=predicted.get('text'),
                        confidence=success_rate,
                        reason=f"تم استخدام قالب محفوظ (نجاح {success_rate}%)",
                        use_template=True,
                        template_id=template.get('id')
                    )

        # 2. تحليل الموقف الحالي حسب جدول القرارات
        action_map = {
            "subscribe_all": ("subscribe_all", 88.0),
            "solve_math": ("solve_math", 95.0),
            "share_phone": ("share_phone", 92.0),
            "click_verify": ("click_verify", 90.0),
            "match_emoji": ("match_emoji", 85.0),
            "complete": ("complete", 80.0),
            "retry": ("retry", 70.0),
            "click_best": ("click_best", 55.0),
            "fallback": ("fallback", 40.0),
        }

        suggested = analysis.suggested_action
        if suggested in action_map:
            action, base_conf = action_map[suggested]
            conf = min(analysis.overall_confidence, base_conf)

            # إذا ثقة منخفضة < 70% → fallback
            if conf < 70 and action not in ("complete", "retry"):
                return Decision(
                    action="fallback",
                    confidence=conf,
                    reason=f"ثقة منخفضة ({conf}%) - يحتاج تدخل آدمن",
                    fallback_needed=True,
                    fallback_context={
                        "bot_username": bot_username,
                        "message_text": analysis.message_text,
                        "buttons": [{"text": b.text, "type": b.button_type} for b in analysis.buttons],
                        "suggested": suggested,
                        "analysis": analysis
                    }
                )

            # قرار عادي - اختيار زر هدف حسب النوع
            target_btn = None
            if action == "subscribe_all" and analysis.subscribe_buttons:
                target_btn = analysis.subscribe_buttons[0]
            elif action == "click_verify" and analysis.verify_buttons:
                target_btn = analysis.verify_buttons[0]
            elif action == "share_phone" and analysis.phone_buttons:
                target_btn = analysis.phone_buttons[0]

            return Decision(
                action=action,
                target_button=target_btn,
                target_text=str(analysis.math_answer) if action == "solve_math" else None,
                confidence=conf,
                reason=f"تحليل مباشر: {suggested}"
            )

        # 3. fallback افتراضي
        return Decision(
            action="fallback",
            confidence=analysis.overall_confidence,
            reason="غير معروف - يحتاج تعلم",
            fallback_needed=True,
            fallback_context={
                "bot_username": bot_username,
                "message_text": analysis.message_text,
                "buttons": [{"text": b.text, "type": b.button_type} for b in analysis.buttons],
                "analysis": analysis
            }
        )

    # ------------------------------------------------------------------
    def _calc_success_rate(self, template: Dict[str, Any]) -> float:
        try:
            succ = template.get('success_count', 0)
            fail = template.get('fail_count', 0)
            total = succ + fail
            if total == 0:
                return 0.0
            return round(succ / total * 100, 1)
        except Exception:
            return 0.0

    async def _predict_from_template(self, template: Dict[str, Any], analysis: AnalysisResult) -> Optional[Dict[str, Any]]:
        """توقع الإجراء من القالب"""
        try:
            steps_json = template.get('steps', '[]')
            steps = json.loads(steps_json) if isinstance(steps_json, str) else steps_json
            if not steps:
                return None
            for step in steps[:3]:  # جرب أول 3 خطوات
                stype = step.get('type', 'click')
                target = step.get('target_text', '').lower()
                if stype == 'click' and target:
                    for btn in analysis.buttons:
                        if target in btn.text.lower():
                            return {'action': 'click_best', 'button': btn, 'text': btn.text}
                elif stype == 'solve_math' and analysis.has_math:
                    return {'action': 'solve_math', 'text': str(analysis.math_answer)}
            return None
        except Exception as e:
            logger.debug(f"Predict error: {e}")
            return None


# ============================================================
# المكون 3: TemplateLearner - الذاكرة
# ============================================================

class TemplateLearner:
    """
    متعلم القوالب - يحفظ أنماط تفاعل كل بوت
    """

    def __init__(self, supabase_client=None):
        self.supabase = supabase_client
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.RETRAIN_THRESHOLD = 3  # إذا فشل 3 مرات متتالية

    async def get_template(self, bot_username: str) -> Optional[Dict[str, Any]]:
        """استرجاع قالب محفوظ"""
        if bot_username in self.cache:
            return self.cache[bot_username]
        if not self.supabase:
            return None
        try:
            response = await asyncio.to_thread(
                lambda: self.supabase.table('bot_templates').select('*').eq('bot_username', bot_username).execute()
            )
            if response.data:
                self.cache[bot_username] = response.data[0]
                return response.data[0]
            return None
        except Exception as e:
            logger.error(f"Get template error: {e}")
            return None

    async def save_template(self, bot_username: str, steps: List[Dict[str, Any]], success: bool = True):
        """حفظ أو تحديث قالب"""
        if not self.supabase:
            logger.warning("Supabase not set for TemplateLearner")
            return
        try:
            existing = await self.get_template(bot_username)
            now = datetime.now(timezone.utc).isoformat()
            if existing:
                new_succ = existing.get('success_count', 0) + (1 if success else 0)
                new_fail = existing.get('fail_count', 0) + (0 if success else 1)
                await asyncio.to_thread(
                    lambda: self.supabase.table('bot_templates').update({
                        'steps': json.dumps(steps, ensure_ascii=False),
                        'total_steps': len(steps),
                        'success_count': new_succ,
                        'fail_count': new_fail,
                        'last_used_at': now,
                        'updated_at': now
                    }).eq('id', existing['id']).execute()
                )
                existing['steps'] = json.dumps(steps, ensure_ascii=False)
                existing['success_count'] = new_succ
                existing['fail_count'] = new_fail
                self.cache[bot_username] = existing
                logger.info(f"Template updated for {bot_username}: success={new_succ} fail={new_fail}")
            else:
                resp = await asyncio.to_thread(
                    lambda: self.supabase.table('bot_templates').insert({
                        'bot_username': bot_username,
                        'template_name': f'Auto-learned: {bot_username}',
                        'steps': json.dumps(steps, ensure_ascii=False),
                        'total_steps': len(steps),
                        'success_count': 1 if success else 0,
                        'fail_count': 0 if success else 1,
                        'created_at': now,
                        'updated_at': now,
                        'last_used_at': now
                    }).execute()
                )
                if resp.data:
                    self.cache[bot_username] = resp.data[0]
                logger.info(f"Template created for {bot_username}: {len(steps)} steps")
        except Exception as e:
            logger.error(f"Save template error: {e}")

    async def record_success(self, bot_username: str):
        """تسجيل نجاح"""
        tmpl = await self.get_template(bot_username)
        if tmpl:
            await self.save_template(bot_username, json.loads(tmpl.get('steps', '[]')), success=True)

    async def record_failure(self, bot_username: str):
        """تسجيل فشل"""
        tmpl = await self.get_template(bot_username)
        if tmpl:
            await self.save_template(bot_username, json.loads(tmpl.get('steps', '[]')), success=False)

    def should_retrain(self, bot_username: str) -> bool:
        """هل يحتاج إعادة تعلم؟"""
        tmpl = self.cache.get(bot_username)
        if not tmpl:
            return False
        return tmpl.get('fail_count', 0) >= self.RETRAIN_THRESHOLD

    async def learn_from_history(self, bot_username: str, history: List[Dict[str, Any]], success: bool = True):
        """تعلم من سجل تفاعل"""
        try:
            steps = []
            for h in history:
                stype = h.get('step_type', 'click')
                entry = {'type': stype}
                if stype == 'click':
                    entry['target_text'] = h.get('clicked_button', '')
                elif stype == 'solve_math':
                    entry['target_text'] = 'math'
                    entry['answer'] = h.get('answer', '')
                elif stype == 'subscribe':
                    entry['target_text'] = 'subscribe'
                    entry['channel'] = h.get('channel', '')
                elif stype == 'send_text':
                    entry['text_to_send'] = h.get('sent_text', '')
                steps.append(entry)
            await self.save_template(bot_username, steps, success=success)
        except Exception as e:
            logger.error(f"Learn from history error: {e}")


# ============================================================
# المكون 4: ActionExecutor - الأيدي
# ============================================================

class ActionExecutor:
    """
    منفذ الإجراءات الفعلي على تيليجرام
    - تأخير عشوائي
    - توزيع البروكسي
    - معالجة الأخطاء
    - إعادة المحاولة الذكية
    """

    def __init__(self, supabase_client=None):
        self.supabase = supabase_client

    def _random_delay(self, speed: str = "medium") -> Tuple[float, float]:
        """إرجاع مجال تأخير حسب السرعة"""
        ranges = {
            "slow": (3, 7),
            "medium": (1.5, 4),
            "fast": (0.5, 2)
        }
        return ranges.get(speed, (1.5, 4))

    async def random_sleep(self, speed: str = "medium"):
        """نوم عشوائي"""
        low, high = self._random_delay(speed)
        await asyncio.sleep(random.uniform(low, high))

    async def sleep_between_accounts(self):
        """نوم بين الحسابات 30-300 ثانية"""
        await asyncio.sleep(random.uniform(30, 300))

    def _extract_buttons(self, message) -> List[str]:
        try:
            analyzer = MessageAnalyzer()
            btns = analyzer._extract_buttons_from_message(message)
            return [b.get('text', '') for b in btns]
        except Exception:
            return []

    # ------------------------------------------------------------------
    async def execute_subscribe_all(self, client, bot_entity, analysis: AnalysisResult, speed: str = "medium") -> bool:
        """4.2 اشتراك في كل القنوات بذكاء"""
        try:
            # جمع كل قنوات الاشتراك
            channels = []
            for btn in analysis.subscribe_buttons:
                if btn.url and "t.me/" in btn.url:
                    try:
                        ch = btn.url.split("t.me/")[-1].split("?")[0].split("/")[0].strip()
                        if ch and ch not in channels:
                            channels.append(ch)
                    except Exception:
                        pass

            # من النص (استخراج روابط t.me)
            text_channels = re.findall(r't\.me/([a-zA-Z0-9_]+)', analysis.message_text or "")
            for ch in text_channels:
                if ch not in channels and ch.lower() not in ("bot", "start"):
                    channels.append(ch)

            if not channels and analysis.subscribe_buttons:
                # لا يوجد رابط، جرب الضغط على الأزرار مباشرة
                for btn in analysis.subscribe_buttons:
                    try:
                        msgs = await client.get_messages(bot_entity, limit=3)
                        for msg in msgs:
                            buds = self._extract_buttons(msg)
                            for b in buds:
                                if btn.text in b:
                                    await msg.click(text=b)
                                    await self.random_sleep(speed)
                                    logger.info(f"Clicked subscribe button: {btn.text}")
                                    break
                    except Exception as e:
                        logger.debug(f"Click subscribe error: {e}")

            # الانضمام لكل قناة
            from telethon.tl.functions.channels import JoinChannelRequest
            from telethon.tl.functions.messages import ImportChatInviteRequest
            from telethon.errors import UserAlreadyParticipantError, FloodWaitError

            for ch in channels:
                try:
                    if ch.startswith("+") or ch.startswith("joinchat"):
                        hash_part = ch.replace("+", "").replace("joinchat/", "")
                        await client(ImportChatInviteRequest(hash_part))
                        logger.info(f"Joined via invite: {ch}")
                    else:
                        entity = await client.get_input_entity(ch)
                        await client(JoinChannelRequest(entity))
                        logger.info(f"Joined channel: {ch}")
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                except UserAlreadyParticipantError:
                    logger.info(f"Already joined: {ch}")
                except FloodWaitError as e:
                    logger.warning(f"FloodWait joining {ch}: {e.seconds}s")
                    await asyncio.sleep(min(e.seconds, 30))
                except Exception as e:
                    logger.error(f"Join error {ch}: {e}")

            # بعد الاشتراك، ابحث عن زر تحقق واضغطه
            await self.random_sleep(speed)
            try:
                msgs = await client.get_messages(bot_entity, limit=5)
                analyzer = MessageAnalyzer()
                for msg in msgs:
                    btns = analyzer._extract_buttons_from_message(msg)
                    for btn in btns:
                        lower = btn.get('text', '').lower()
                        if any(k in lower for k in analyzer.all_verify):
                            for m in msgs:
                                try:
                                    await m.click(text=btn.get('text'))
                                    logger.info(f"Clicked verify after subscribe: {btn.get('text')}")
                                    return True
                                except Exception:
                                    pass
                # إذا لم يوجد زر تحقق، أرسل /start
                await client.send_message(bot_entity, "/start")
                logger.info("Sent /start after subscribe (no verify button)")
            except Exception:
                pass

            return True
        except Exception as e:
            logger.error(f"Subscribe all error: {e}")
            return False

    # ------------------------------------------------------------------
    async def execute_math(self, client, bot_entity, analysis: AnalysisResult, speed: str = "medium") -> bool:
        """4.4 حل مسألة رياضية"""
        try:
            if not analysis.has_math or analysis.math_answer is None:
                return False
            answer = str(analysis.math_answer)
            msgs = await client.get_messages(bot_entity, limit=5)
            for msg in msgs:
                analyzer = MessageAnalyzer()
                btns = analyzer._extract_buttons_from_message(msg)
                for btn in btns:
                    if answer in btn.get('text', ''):
                        try:
                            await msg.click(text=btn.get('text'))
                            logger.info(f"Math solved via click: {answer}")
                            await self.random_sleep(speed)
                            return True
                        except Exception:
                            pass
            # لم يوجد زر، أرسل الإجابة كنص
            await client.send_message(bot_entity, answer)
            logger.info(f"Math solved via send: {answer}")
            await self.random_sleep(speed)
            return True
        except Exception as e:
            logger.error(f"Math execute error: {e}")
            return False

    # ------------------------------------------------------------------
    async def execute_verify(self, client, bot_entity, analysis: AnalysisResult, speed: str = "medium") -> bool:
        """4.3 ضغط تحقق"""
        try:
            if analysis.verify_buttons:
                btn_text = analysis.verify_buttons[0].text
                msgs = await client.get_messages(bot_entity, limit=5)
                for msg in msgs:
                    try:
                        await msg.click(text=btn_text)
                        logger.info(f"Verify clicked: {btn_text}")
                        await self.random_sleep(speed)
                        return True
                    except Exception:
                        continue
            # fallback: جرب أي زر تحقق
            msgs = await client.get_messages(bot_entity, limit=5)
            analyzer = MessageAnalyzer()
            for msg in msgs:
                btns = analyzer._extract_buttons_from_message(msg)
                for btn in btns:
                    lower = btn.get('text', '').lower()
                    if any(k in lower for k in analyzer.all_verify):
                        try:
                            await msg.click(text=btn.get('text'))
                            logger.info(f"Verify fallback clicked: {btn.get('text')}")
                            return True
                        except Exception:
                            pass
            # لا يوجد زر، أرسل /start
            await client.send_message(bot_entity, "/start")
            return True
        except Exception as e:
            logger.error(f"Verify error: {e}")
            return False

    # ------------------------------------------------------------------
    async def execute_phone_share(self, client, bot_entity, analysis: AnalysisResult,
                                  phone_forward_link: str = None, speed: str = "medium") -> bool:
        """4.5 مشاركة رقم: مباشر أو تحويل"""
        try:
            # النوع أ: مشاركة مباشرة (request_contact)
            if analysis.phone_buttons:
                for btn in analysis.phone_buttons:
                    if btn.has_contact:
                        try:
                            msgs = await client.get_messages(bot_entity, limit=5)
                            for msg in msgs:
                                await msg.click(text=btn.text)
                                logger.info(f"Phone share clicked: {btn.text}")
                                await self.random_sleep(speed)
                                return True
                        except Exception as e:
                            logger.debug(f"Phone share click error: {e}")

            # النوع ب: تحويل من مجموعة عامة
            if phone_forward_link and "t.me/" in phone_forward_link:
                try:
                    parts = phone_forward_link.split("/")
                    ch = parts[-2]
                    msg_id = int(parts[-1])
                    entity = await client.get_input_entity(ch)
                    msg = await client.get_messages(entity, ids=msg_id)
                    if msg:
                        await client.forward_messages(bot_entity, msg)
                        logger.info(f"Phone forwarded from {phone_forward_link}")
                        return True
                except Exception as e:
                    logger.error(f"Phone forward error: {e}")

            return False
        except Exception as e:
            logger.error(f"Phone share error: {e}")
            return False

    # ------------------------------------------------------------------
    async def execute_emoji(self, client, bot_entity, analysis: AnalysisResult, speed: str = "medium") -> bool:
        """4.6 مطابقة إيموجي"""
        try:
            if not analysis.has_emoji_challenge or not analysis.target_emoji:
                return False
            target = analysis.target_emoji
            msgs = await client.get_messages(bot_entity, limit=5)
            for msg in msgs:
                analyzer = MessageAnalyzer()
                btns = analyzer._extract_buttons_from_message(msg)
                for btn in btns:
                    if target in btn.get('text', ''):
                        try:
                            await msg.click(text=btn.get('text'))
                            logger.info(f"Emoji matched: {target}")
                            await self.random_sleep(speed)
                            return True
                        except Exception:
                            pass
            return False
        except Exception as e:
            logger.error(f"Emoji error: {e}")
            return False

    # ------------------------------------------------------------------
    async def execute_language(self, client, bot_entity, analysis: AnalysisResult, speed: str = "medium") -> bool:
        """4.7 اختيار لغة English افتراضياً"""
        try:
            msgs = await client.get_messages(bot_entity, limit=5)
            for msg in msgs:
                analyzer = MessageAnalyzer()
                btns = analyzer._extract_buttons_from_message(msg)
                for btn in btns:
                    lower = btn.get('text', '').lower()
                    if 'english' in lower or 'английский' in lower:
                        try:
                            await msg.click(text=btn.get('text'))
                            logger.info(f"Language selected: {btn.get('text')}")
                            await self.random_sleep(speed)
                            return True
                        except Exception:
                            pass
                # fallback: أول زر لغة
                for btn in btns:
                    if any(k in btn.get('text', '').lower() for k in ('english', 'arabic', 'русский')):
                        try:
                            await msg.click(text=btn.get('text'))
                            return True
                        except Exception:
                            pass
            return False
        except Exception as e:
            logger.error(f"Language error: {e}")
            return False

    # ------------------------------------------------------------------
    async def execute_with_retry(self, coro, max_retries: int = 3, base_delay: float = 2.0):
        """إعادة محاولة ذكية مع زيادة التأخير - FIXED v3.0.1"""
        for attempt in range(max_retries):
            try:
                result = await coro()
                if result:
                    return True
            except Exception as e:
                if "FloodWait" in str(e):
                    m = re.search(r'(\d+)', str(e))
                    wait = int(m.group(1)) if m else 30
                    logger.warning(f"FloodWait retry {attempt + 1}/{max_retries}: {wait}s")
                    await asyncio.sleep(min(wait, 120))
                else:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Retry {attempt + 1}/{max_retries} after {delay:.1f}s: {e}")
                    await asyncio.sleep(delay)
        return False


# ============================================================
# نظام Fallback
# ============================================================

class FallbackManager:
    """إدارة طلبات Fallback - يسأل الآدمن عند عدم الفهم"""

    def __init__(self, supabase_client=None, bot=None, admin_group_id=None):
        self.supabase = supabase_client
        self.bot = bot
        self.admin_group_id = admin_group_id

    async def create_request(self, parent_task_id: str, session_id: str, bot_username: str,
                             message_text: str, buttons: List[Dict[str, Any]]) -> Optional[str]:
        """إنشاء طلب fallback"""
        try:
            data = {
                'parent_task_id': parent_task_id,
                'session_id': session_id,
                'bot_username': bot_username,
                'message_text': message_text[:1000] if message_text else "",
                'buttons': json.dumps(buttons, ensure_ascii=False),
                'status': 'pending',
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            if self.supabase:
                resp = await asyncio.to_thread(
                    lambda: self.supabase.table('fallback_requests').insert(data).execute()
                )
                req_id = resp.data[0]['id'] if resp.data else None
                if req_id:
                    await self._notify_admin(req_id, bot_username, message_text, buttons)
                    return req_id
            # fallback: إرسال مباشر للآدمن عبر البوت
            await self._notify_admin("direct", bot_username, message_text, buttons)
            return "direct"
        except Exception as e:
            logger.error(f"Fallback create error: {e}")
            return None

    async def _notify_admin(self, req_id: str, bot_username: str, message_text: str,
                            buttons: List[Dict[str, Any]]):
        """إرسال رسالة للآدمن"""
        try:
            if not self.bot or not self.admin_group_id:
                logger.warning("Bot or admin_group_id not set for fallback notify")
                return
            btn_text = ""
            for i, btn in enumerate(buttons, 1):
                btn_text += f"   [{i}] {btn.get('text', '')} ({btn.get('type', 'unknown')})\n"
            if not btn_text:
                btn_text = "   لا توجد أزرار\n"
            text = (
                f"🤖 *البوت يحتاج مساعدتك*\n\n"
                f"📍 *البوت:* @{bot_username}\n\n"
                f"📝 *الرسالة:* \"{message_text[:500]}\"\n\n"
                f"🔘 *الأزرار المتاحة:*\n{btn_text}\n"
                f"❓ *ماذا أفعل؟ (أرسل رقم الخيار)*\n"
                f"🆔 الطلب: `{req_id}`\n\n"
                f"💡 رد برقم: `1` أو `2` ... أو أرسل نصاً مثل `اضغط تحقق`"
            )
            await self.bot.send_message(self.admin_group_id, text, parse_mode="Markdown")
            logger.info(f"Fallback notification sent for {bot_username} req {req_id}")
        except Exception as e:
            logger.error(f"Notify admin error: {e}")

    async def wait_for_answer(self, req_id: str, timeout: int = 300) -> Optional[str]:
        """انتظار إجابة الآدمن (polling)"""
        if req_id == "direct" or not self.supabase:
            return None
        start = datetime.now(timezone.utc)
        while (datetime.now(timezone.utc) - start).total_seconds() < timeout:
            try:
                resp = await asyncio.to_thread(
                    lambda: self.supabase.table('fallback_requests')
                    .select('status,admin_response').eq('id', req_id).execute()
                )
                if resp.data and resp.data[0].get('status') == 'answered':
                    return resp.data[0].get('admin_response')
            except Exception:
                pass
            await asyncio.sleep(5)
        return None

    async def answer_request(self, req_id: str, admin_response: str) -> bool:
        """الآدمن يجيب على الطلب"""
        try:
            if not self.supabase:
                return False
            await asyncio.to_thread(
                lambda: self.supabase.table('fallback_requests').update({
                    'status': 'answered',
                    'admin_response': admin_response,
                    'answered_at': datetime.now(timezone.utc).isoformat()
                }).eq('id', req_id).execute()
            )
            return True
        except Exception as e:
            logger.error(f"Answer fallback error: {e}")
            return False


# ============================================================
# نظام التقارير
# ============================================================

class ReportGenerator:
    """توليد تقارير المهام للآدمن"""

    def __init__(self, supabase_client=None, bot=None, admin_group_id=None):
        self.supabase = supabase_client
        self.bot = bot
        self.admin_group_id = admin_group_id

    async def send_task_report(self, parent_task_id: str, bot_username: str,
                               results: List[Dict[str, Any]], duration_seconds: float,
                               proxy_count: int = 0):
        """إرسال تقرير بعد كل مهمة"""
        try:
            total = len(results)
            success = sum(1 for r in results if r.get('success'))
            failed = total - success

            details = ""
            for r in results[:15]:
                phone = str(r.get('phone', 'unknown'))
                icon = "🟢" if r.get('success') else "🔴"
                reason = r.get('reason', '' if r.get('success') else 'فشل')
                masked = phone[:4] + "xxxxx" if len(phone) > 4 else phone
                status = "✅" if r.get('success') else f"❌ {str(reason)[:20]}"
                details += f"{icon} {masked} {status}\n"
            if total > 15:
                details += f"... و {total - 15} حساب آخر\n"

            minutes = int(duration_seconds // 60)
            seconds = int(duration_seconds % 60)
            text = (
                f"✅ *المهمة:* @{bot_username}\n\n"
                f"📊 *النتيجة:* {success}/{total} نجاح\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"{details}"
                f"━━━━━━━━━━━━━━━━\n"
                f"⏱ *الوقت:* {minutes} دقائق و {seconds} ثانية\n"
                f"🌐 *البروكسي:* {proxy_count} مستخدمين\n"
                f"🆔 المهمة: `{str(parent_task_id)[:8]}`"
            )
            if self.bot and self.admin_group_id:
                await self.bot.send_message(self.admin_group_id, text, parse_mode="Markdown")
                logger.info(f"Report sent for {bot_username}: {success}/{total}")
            else:
                logger.info(f"Report (no bot): {text}")
        except Exception as e:
            logger.error(f"Report error: {e}")
