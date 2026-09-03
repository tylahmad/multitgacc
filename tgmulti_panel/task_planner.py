#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================
 task_planner.py - تحليل وتخطيط المهمة قبل التنفيذ (طبقة فوق ai_agent.py)
========================================================================
الدور:
  يأخذ النص الحر الذي يكتبه المستخدم في الواجهة (رابط بوت، /start، اشترك
  @قناة، خطوات يدوية...) ويحوّله إلى "خطة" مفهومة:
    1) ما الذي فهمه (الهدف، النوع، الخطوات)
    2) ما الذي سينفذه (بلغة عربية واضحة تُعرض في السجل)
    3) أسئلة توضيحية (عند الغموض) مع خيارات مرقّمة - تُعرض في نافذة منبثقة
    4) قاموس مهمة (task dict) بنفس الصيغة التي كان بوت main.py يُدخلها في
       جدول tasks_queue - أي أن worker.py ينفذها بلا أي تغيير

  يستخدم MessageAnalyzer و DecisionEngine من ai_agent.py (بدون تعديلهما)
  لتصنيف الأزرار/الأوامر وشرح ما "سيفعله الذكاء الاصطناعي" أثناء التنفيذ.

الاستخدام:
    planner = TaskPlanner()
    plan = planner.plan("https://t.me/SomeBot?start=REF123\\nsubscribe\\ncheck")
    for line in plan.reasoning: print(line)
    if plan.questions:  # اسأل المستخدم ثم:
        plan = planner.plan(text, answers={q.id: "1"})
    task = plan.task     # يُدرج في worker.supabase.table('tasks_queue')
========================================================================
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

try:
    from ai_agent import MessageAnalyzer, DecisionEngine  # noqa: F401
    AI_AVAILABLE = True
except Exception:  # pragma: no cover
    MessageAnalyzer = None
    DecisionEngine = None
    AI_AVAILABLE = False


# ============================================================
# أنواع البيانات
# ============================================================
@dataclass
class Question:
    """سؤال توضيحي يُعرض للمستخدم في نافذة منبثقة."""
    id: str
    text: str
    options: List[str] = field(default_factory=list)
    allow_custom: bool = True
    default: Optional[str] = None


@dataclass
class Plan:
    """نتيجة التخطيط."""
    task: Dict[str, Any]
    task_type: str
    target: str
    steps: List[Dict[str, Any]]
    reasoning: List[str]
    warnings: List[str] = field(default_factory=list)
    questions: List[Question] = field(default_factory=list)
    mode: str = 'smart'   # smart | manual | follow_channel | react_post | vote_poll | forward | start

    @property
    def needs_help(self) -> bool:
        return bool(self.questions)


# ============================================================
# ثوابت
# ============================================================
VALID_STEP_TYPES = [
    'start', 'language', 'subscribe', 'check', 'math', 'emoji', 'text', 'phone',
    'visit', 'forward', 'follow_channel', 'react_post', 'vote_poll', 'subscribe_channel',
    'click'
]

STEP_LABELS_AR = {
    'start': 'إرسال /start للبوت (مع رمز الإحالة إن وُجد)',
    'language': 'اختيار اللغة (English افتراضياً)',
    'subscribe': 'الاشتراك في القنوات الإجبارية ثم الضغط على زر التحقق',
    'subscribe_channel': 'الاشتراك في القناة المحددة',
    'follow_channel': 'متابعة/الانضمام إلى القناة',
    'check': 'الضغط على زر التحقق/المتابعة',
    'math': 'حل المعادلة الرياضية وإرسال الجواب',
    'emoji': 'مطابقة الإيموجي المطلوب',
    'text': 'إرسال نص محدد للبوت',
    'phone': 'مشاركة رقم الهاتف مع البوت',
    'visit': 'الضغط على زر الزيارة/الرابط',
    'forward': 'إعادة توجيه رسالة إلى البوت',
    'react_post': 'التفاعل على منشور',
    'vote_poll': 'التصويت في استفتاء',
    'click': 'الضغط على زر محدد',
}

TASK_TYPE_LABELS_AR = {
    'composite': 'مهمة ذكية (الذكاء الاصطناعي يحلل رسائل البوت ويقرر تلقائياً)',
    'manual': 'مهمة يدوية (خطوات محددة بالترتيب)',
    'follow_channel': 'متابعة قنوات/مجموعات',
    'react_post': 'تفاعل على منشور',
    'vote_poll': 'تصويت في استفتاء',
    'forward': 'إعادة توجيه رسالة',
    'start': 'إرسال /start فقط',
    'join': 'انضمام إلى قناة/مجموعة',
}

_TME_RE = re.compile(r'(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/([^\s]+)', re.IGNORECASE)
_USERNAME_RE = re.compile(r'^@?([A-Za-z][A-Za-z0-9_]{3,31})$')
_POST_LINK_RE = re.compile(r'(?:https?://)?(?:t\.me|telegram\.me)/(c/\d+|[A-Za-z0-9_]+)/(\d+)', re.IGNORECASE)
_EMOJI_RE = re.compile(
    r'[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF'
    r'\U0001F1E0-\U0001F1FF\u2600-\u26FF\u2700-\u27BF\U0001F900-\U0001F9FF]'
)

# كلمات عربية/إنجليزية تشير إلى نية معينة في النص الحر
INTENT_KEYWORDS = {
    'subscribe': ['اشترك', 'اشتراك', 'انضم', 'انضمام', 'تابع', 'متابعة', 'subscribe', 'join', 'follow'],
    'react_post': ['تفاعل', 'ريأكشن', 'رياكشن', 'react', 'reaction', 'لايك', 'like'],
    'vote_poll': ['صوت', 'تصويت', 'استفتاء', 'vote', 'poll'],
    'forward': ['حول', 'تحويل', 'توجيه', 'forward'],
    'start': ['start', 'ابدأ', 'ابدا', 'تشغيل', 'إحالة', 'احالة', 'referral', 'ref'],
    'phone': ['رقم', 'هاتف', 'phone', 'contact', 'جهة اتصال'],
    'math': ['معادلة', 'حساب', 'math', 'captcha', 'كابتشا'],
}

SPEED_LABELS_AR = {'slow': 'بطيئة', 'medium': 'متوسطة', 'fast': 'سريعة'}


# ============================================================
# المخطط
# ============================================================
class TaskPlanner:
    """يحلل نص المهمة ويبني خطة + قاموس مهمة جاهز للمحرك."""

    def __init__(self):
        self.analyzer = MessageAnalyzer() if MessageAnalyzer else None

    # ------------------------------------------------------------------
    # الواجهة العامة
    # ------------------------------------------------------------------
    def plan(self, text: str, answers: Optional[Dict[str, str]] = None,
             accounts: int = 1, speed: str = 'medium') -> Plan:
        """تحليل النص وبناء الخطة. answers = إجابات الأسئلة السابقة (id -> نص)."""
        answers = answers or {}
        raw = (text or '').strip()
        reasoning: List[str] = []
        warnings: List[str] = []
        questions: List[Question] = []

        if not raw:
            questions.append(Question(
                id='empty',
                text='لم تكتب أي مهمة. ماذا تريد أن تنفذ؟',
                options=['رابط بوت إحالة (سأرسل /start مع رمز الإحالة)',
                         'الاشتراك في قناة (@channel)',
                         'خطوات يدوية (start / subscribe / check ...)'],
            ))
            return Plan(task={}, task_type='composite', target='', steps=[], reasoning=[
                '⚠️ لم أجد نصاً للمهمة.'], questions=questions, mode='smart')

        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        reasoning.append(f"📝 قرأت {len(lines)} سطر/أسطر من نص المهمة.")

        # 1) استخراج الروابط والمعرّفات
        links = self._extract_links(raw)
        bot_links = [l for l in links if l['kind'] == 'bot']
        channel_links = [l for l in links if l['kind'] == 'channel']
        post_links = [l for l in links if l['kind'] == 'post']
        invite_links = [l for l in links if l['kind'] == 'invite']

        if bot_links:
            reasoning.append("🤖 وجدت بوت/بوتات: " + "، ".join(f"@{b['username']}" for b in bot_links))
        if channel_links:
            reasoning.append("📢 وجدت قنوات/معرّفات: " + "، ".join(f"@{c['username']}" for c in channel_links))
        if post_links:
            reasoning.append("🔗 وجدت روابط منشورات: " + "، ".join(p['raw'] for p in post_links))
        if invite_links:
            reasoning.append("🔒 وجدت روابط دعوة خاصة: " + "، ".join(i['raw'] for i in invite_links))

        # 2) الخطوات اليدوية (أسطر بصيغة start / subscribe / text:... )
        manual_steps, unknown_lines = self._parse_manual_steps(lines)

        # 3) النوايا من النص الحر
        intents = self._detect_intents(raw)
        if intents:
            reasoning.append("🧠 النوايا المكتشفة من النص: " + "، ".join(intents))

        # 4) تحديد الهدف الرئيسي
        target, target_kind = self._resolve_target(bot_links, channel_links, post_links, invite_links,
                                                   lines, answers, questions, reasoning)

        # 5) تحديد نوع المهمة
        mode, task_type = self._resolve_mode(target_kind, manual_steps, intents, post_links,
                                             channel_links, bot_links, answers, questions, reasoning)

        # 6) بناء الخطوات النهائية
        steps = list(manual_steps)
        if mode == 'manual' and channel_links and not any(s.get('type') in ('subscribe', 'subscribe_channel') for s in steps):
            # قنوات مذكورة مع خطوات يدوية بدون خطوة اشتراك -> أضفها
            steps.insert(0, {'type': 'subscribe', 'channels': [c['username'] for c in channel_links]})
            reasoning.append("➕ أضفت خطوة اشتراك للقنوات المذكورة قبل الخطوات اليدوية.")

        # 7) أسطر غير مفهومة
        if unknown_lines:
            shown = "، ".join(f"«{u[:40]}»" for u in unknown_lines[:3])
            key = 'unknown_lines'
            ans = answers.get(key)
            if ans is None:
                questions.append(Question(
                    id=key,
                    text=f"لم أفهم هذه الأسطر: {shown}\nكيف أتعامل معها؟",
                    options=['تجاهلها',
                             'أرسلها كنص للبوت (خطوة text)',
                             'اعتبرها أسماء أزرار يجب الضغط عليها (خطوة click)'],
                    default='1'
                ))
            else:
                choice = self._normalize_choice(ans, 3)
                if choice == 2:
                    for u in unknown_lines:
                        steps.append({'type': 'text', 'text_to_send': u})
                    reasoning.append("✍️ سأرسل الأسطر غير المفهومة كنصوص للبوت.")
                    if mode == 'smart':
                        mode, task_type = 'manual', 'manual'
                elif choice == 3:
                    for u in unknown_lines:
                        steps.append({'type': 'click', 'target_text': u})
                    reasoning.append("🖱 سأضغط على الأزرار المذكورة بالاسم.")
                    if mode == 'smart':
                        mode, task_type = 'manual', 'manual'
                else:
                    reasoning.append("⏭ تجاهلت الأسطر غير المفهومة.")

        # 8) معطيات إضافية حسب النوع
        emoji_target = '👍'
        vote_option = '0'
        target_message_link = ''
        channel_list: List[str] = [c['username'] for c in channel_links] + [i['raw'] for i in invite_links]

        if mode == 'react_post':
            target_message_link = post_links[0]['raw'] if post_links else ''
            found = _EMOJI_RE.findall(raw)
            key = 'emoji'
            if found:
                emoji_target = found[0]
                reasoning.append(f"😊 الإيموجي المطلوب: {emoji_target}")
            elif 'random' in raw.lower() or 'عشوائي' in raw:
                emoji_target = 'random'
                reasoning.append("🎲 سيتم اختيار إيموجي عشوائي لكل حساب.")
            elif answers.get(key):
                a = answers[key].strip()
                emoji_target = {'1': '👍', '2': '❤️', '3': '🔥', '4': 'random'}.get(a, a)
                reasoning.append(f"😊 الإيموجي المختار: {emoji_target}")
            else:
                questions.append(Question(id=key, text='أي إيموجي تريد للتفاعل على المنشور؟',
                                          options=['👍', '❤️', '🔥', 'عشوائي (random)'], default='1'))

        if mode == 'vote_poll':
            target_message_link = post_links[0]['raw'] if post_links else ''
            m = re.search(r'(?:خيار|option|الخيار)\s*[:#]?\s*(\d+|\S+)', raw, re.IGNORECASE)
            key = 'vote_option'
            if m:
                vote_option = m.group(1)
                reasoning.append(f"🗳 خيار التصويت: {vote_option}")
            elif answers.get(key):
                vote_option = answers[key].strip()
                reasoning.append(f"🗳 خيار التصويت: {vote_option}")
            else:
                questions.append(Question(id=key, text='ما هو خيار التصويت؟ (رقم الخيار أو نصه)',
                                          options=['1', '2', '3'], default='1'))

        if mode == 'forward':
            target_message_link = post_links[0]['raw'] if post_links else ''
            if not bot_links and not channel_links:
                key = 'forward_target'
                if answers.get(key):
                    target = answers[key].strip().lstrip('@')
                else:
                    questions.append(Question(id=key, text='إلى أي بوت/مجموعة أعيد توجيه الرسالة؟ (اكتب المعرّف)',
                                              options=[], allow_custom=True))

        # 9) ملخص ما سيُنفَّذ
        plan_lines = self._describe_execution(mode, task_type, target, steps, channel_list,
                                              emoji_target, vote_option, target_message_link,
                                              accounts, speed)
        reasoning.extend(plan_lines)

        # 10) تحذيرات
        if target_kind == 'bot' and '?start=' not in raw and mode in ('smart', 'manual'):
            warnings.append("ℹ️ لا يوجد رمز إحالة (?start=...) في الرابط - سيُرسل /start بدون رمز.")
        if accounts > 1 and mode in ('smart', 'manual'):
            warnings.append(f"⏱ سيتم الانتظار عشوائياً بين الحسابات (كما في المحرك الأصلي) - {accounts} حساب.")
        if not AI_AVAILABLE:
            warnings.append("⚠️ ai_agent غير متاح - سيعمل المحرك بالمحلل الحسي فقط.")

        # 11) قاموس المهمة (مطابق لما كان main.py يُدخله في tasks_queue)
        task = {
            'target_bot_link': target or (target_message_link or 'unknown'),
            'target_message_link': target_message_link or None,
            'task_type': task_type,
            'status': 'pending',
            'speed': speed if speed in SPEED_LABELS_AR else 'medium',
            'composite_steps': json.dumps(steps, ensure_ascii=False) if steps else '[]',
            'emoji_target': emoji_target,
            'vote_option': vote_option,
            'channel_list': json.dumps(channel_list, ensure_ascii=False),
            'required_accounts': max(1, int(accounts or 1)),
            'multi_account': bool(accounts and accounts > 1),
            'parent_task_id': None,
        }
        if mode == 'follow_channel' and channel_list:
            task['target_bot_link'] = channel_list[0]

        return Plan(task=task, task_type=task_type, target=task['target_bot_link'], steps=steps,
                    reasoning=reasoning, warnings=warnings, questions=questions, mode=mode)

    # ------------------------------------------------------------------
    # ما سيفعله الذكاء الاصطناعي أثناء التنفيذ (شرح تعليمي للمستخدم)
    # ------------------------------------------------------------------
    def explain_ai_behaviour(self) -> List[str]:
        return [
            "🧠 أثناء التنفيذ سيقرأ الذكاء الاصطناعي كل رسالة يرسلها البوت ويصنّف أزرارها:",
            "   • أزرار بروابط t.me ← اشتراك في القنوات ثم ضغط «تحقق»",
            "   • معادلة رياضية ← حلّها وإرسال الجواب",
            "   • طلب رقم هاتف ← مشاركة جهة الاتصال",
            "   • تحدي إيموجي ← الضغط على الإيموجي المطابق",
            "   • رسالة نجاح/مسجل مسبقاً ← اعتبار المهمة مكتملة",
            "   • عند انخفاض الثقة أو التعثر ← سيسألك عبر نافذة (إن كان خيار المساعدة مفعّلاً)",
        ]

    # ------------------------------------------------------------------
    # شرح رسالة بوت (يُستخدم في نافذة المساعدة أثناء التشغيل)
    # ------------------------------------------------------------------
    def explain_bot_message(self, message_text: str, buttons: List[Dict[str, Any]]) -> List[str]:
        """شرح عربي لما فهمه المحلل من رسالة البوت (للعرض في نافذة المساعدة)."""
        lines: List[str] = []
        if not self.analyzer:
            return lines
        try:
            analysis = self.analyzer.analyze(message_text or '', buttons=buttons or [])
        except Exception:
            return lines
        lang = {'ar': 'العربية', 'en': 'الإنجليزية', 'ru': 'الروسية'}.get(analysis.language_detected, 'غير معروفة')
        lines.append(f"🌐 لغة الرسالة: {lang}")
        if analysis.has_math:
            lines.append(f"🔢 معادلة مكتشفة: {analysis.math_question} ← الجواب {analysis.math_answer}")
        if analysis.has_subscribe:
            lines.append(f"📢 رسالة اشتراك إجباري ({len(analysis.subscribe_buttons)} زر اشتراك)")
        if analysis.has_verify:
            lines.append(f"✅ يوجد زر تحقق: {', '.join(b.text for b in analysis.verify_buttons[:3])}")
        if analysis.has_phone_request:
            lines.append("📱 البوت يطلب رقم الهاتف")
        if analysis.has_emoji_challenge:
            lines.append(f"😊 تحدي إيموجي: {analysis.target_emoji}")
        action_ar = {
            'subscribe_all': 'الاشتراك في كل القنوات', 'solve_math': 'حل المعادلة',
            'share_phone': 'مشاركة الرقم', 'click_verify': 'ضغط زر التحقق',
            'match_emoji': 'مطابقة الإيموجي', 'complete': 'اعتبارها مكتملة',
            'retry': 'إعادة المحاولة', 'click_best': 'ضغط أفضل زر', 'fallback': 'غير متأكد - يحتاج مساعدتك',
        }.get(analysis.suggested_action, analysis.suggested_action)
        lines.append(f"💡 اقتراح الذكاء الاصطناعي: {action_ar} (ثقة {analysis.overall_confidence:.0f}%)")
        return lines

    # ------------------------------------------------------------------
    # أدوات داخلية
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_choice(answer: str, n_options: int) -> int:
        """تحويل إجابة المستخدم إلى رقم خيار (1..n) - 0 إن لم تكن رقماً."""
        a = (answer or '').strip()
        if a.isdigit():
            v = int(a)
            if 1 <= v <= n_options:
                return v
        return 0

    def _extract_links(self, text: str) -> List[Dict[str, Any]]:
        links: List[Dict[str, Any]] = []
        seen = set()

        for m in _TME_RE.finditer(text):
            raw = m.group(0).rstrip('.,;)')
            path = m.group(1).rstrip('.,;)')
            if raw in seen:
                continue
            seen.add(raw)
            if path.startswith('+') or path.lower().startswith('joinchat/'):
                links.append({'kind': 'invite', 'raw': raw if raw.startswith('http') else f"https://{raw}",
                              'username': path})
                continue
            pm = _POST_LINK_RE.match(raw)
            if pm and not path.split('?')[0].endswith('bot'):
                links.append({'kind': 'post', 'raw': raw if raw.startswith('http') else f"https://{raw}",
                              'username': pm.group(1), 'msg_id': int(pm.group(2))})
                continue
            username = path.split('?')[0].split('/')[0]
            ref = None
            if '?start=' in path:
                ref = path.split('?start=')[-1].split('&')[0]
            kind = 'bot' if username.lower().endswith('bot') or ref is not None else 'channel'
            full = raw if raw.startswith('http') else f"https://{raw}"
            links.append({'kind': kind, 'raw': full, 'username': username, 'ref': ref})

        # معرّفات @username بدون رابط
        for token in re.findall(r'(?<![\w/])@([A-Za-z][A-Za-z0-9_]{3,31})', text):
            if token in seen:
                continue
            seen.add(token)
            kind = 'bot' if token.lower().endswith('bot') else 'channel'
            links.append({'kind': kind, 'raw': f"https://t.me/{token}", 'username': token, 'ref': None})
        return links

    def _parse_manual_steps(self, lines: List[str]) -> Tuple[List[Dict[str, Any]], List[str]]:
        """نفس قواعد process_composite_steps في main.py القديم (بدون تعديل الدلالات)."""
        steps: List[Dict[str, Any]] = []
        unknown: List[str] = []
        step_prefix = re.compile(
            r'^(text|forward|react_post|vote_poll|follow_channel|subscribe|subscribe_channel|phone|click|'
            r'اضغط|انقر|زر|نص|ارسل|أرسل)\s*:', re.IGNORECASE)
        for line in lines:
            # سطر يحتوي رابطاً أو معرّفاً (@name) بدون بادئة خطوة -> استُهلك في استخراج
            # الروابط/النوايا وليس خطوة يدوية (مثل: "اشترك @channel" أو "رابط تفاعل 🔥")
            if (_TME_RE.search(line) or re.search(r'(?<![\w/])@[A-Za-z][A-Za-z0-9_]{3,31}', line)) \
                    and not step_prefix.match(line):
                continue
            if line.startswith('/start'):
                steps.append({'type': 'start'})
                continue
            # سطر نوايا فقط بالعربية/الإنجليزية (تفاعل/تصويت/حوّل/اشترك ...) -> ليس خطوة
            low_line = line.lower()
            if any(w in low_line for words in INTENT_KEYWORDS.values() for w in words) \
                    and len(line.split()) <= 4 and not step_prefix.match(line) \
                    and low_line not in VALID_STEP_TYPES:
                # نتحقق أولاً من الكلمات المفردة التي تقابل خطوات (تُعالج أدناه)
                ar_single = {'اشترك', 'اشتراك', 'تحقق', 'لغة', 'معادلة', 'رياضيات', 'ايموجي', 'إيموجي',
                             'رقم', 'هاتف', 'زيارة', 'ابدأ', 'ابدا'}
                if low_line not in ar_single:
                    continue
            if ':' in line:
                typ, val = line.split(':', 1)
                typ = typ.strip().lower()
                val = val.strip()
                if typ in VALID_STEP_TYPES:
                    if typ == 'text':
                        steps.append({'type': 'text', 'text_to_send': val})
                    elif typ == 'forward':
                        steps.append({'type': 'forward', 'target_link': val})
                    elif typ == 'react_post':
                        steps.append({'type': 'react_post', 'target_link': val})
                    elif typ == 'vote_poll':
                        steps.append({'type': 'vote_poll', 'target_link': val})
                    elif typ in ('follow_channel', 'subscribe', 'subscribe_channel'):
                        ch = val.replace('https://t.me/', '').replace('@', '').split('/')[0].strip()
                        steps.append({'type': 'subscribe', 'channels': [ch] if ch else []})
                    elif typ == 'phone':
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
                    elif typ == 'click':
                        steps.append({'type': 'click', 'target_text': val})
                    else:
                        steps.append({'type': typ, 'target_text': val})
                    continue
                # "اضغط: زر" بالعربية
                if typ in ('اضغط', 'انقر', 'زر'):
                    steps.append({'type': 'click', 'target_text': val})
                    continue
                if typ in ('نص', 'ارسل', 'أرسل'):
                    steps.append({'type': 'text', 'text_to_send': val})
                    continue
                unknown.append(line)
                continue
            low = line.lower()
            if low in VALID_STEP_TYPES:
                steps.append({'type': low})
                continue
            # "click Zeta" / "اضغط تحقق" / "text hello" بدون نقطتين (تسهيل للكتابة اليدوية)
            m = re.match(r'^(click|text|اضغط|انقر|زر|نص|ارسل|أرسل)\s+(.+)$', line, re.IGNORECASE)
            if m:
                key, val = m.group(1).lower(), m.group(2).strip()
                if key in ('click', 'اضغط', 'انقر', 'زر'):
                    steps.append({'type': 'click', 'target_text': val})
                else:
                    steps.append({'type': 'text', 'text_to_send': val})
                continue
            # كلمات عربية مفردة تقابل خطوات
            ar_map = {
                'اشترك': 'subscribe', 'اشتراك': 'subscribe', 'تحقق': 'check', 'لغة': 'language',
                'معادلة': 'math', 'رياضيات': 'math', 'ايموجي': 'emoji', 'إيموجي': 'emoji',
                'رقم': 'phone', 'هاتف': 'phone', 'زيارة': 'visit', 'ابدأ': 'start', 'ابدا': 'start',
            }
            if low in ar_map:
                steps.append({'type': ar_map[low]})
                continue
            unknown.append(line)
        return steps, unknown

    def _detect_intents(self, text: str) -> List[str]:
        low = text.lower()
        found = []
        for intent, words in INTENT_KEYWORDS.items():
            if any(w in low for w in words):
                found.append(intent)
        return found

    def _resolve_target(self, bot_links, channel_links, post_links, invite_links, lines,
                        answers, questions, reasoning) -> Tuple[str, str]:
        """تحديد الهدف الرئيسي ونوعه: bot / channel / post / invite / none."""
        key = 'target'
        if len(bot_links) > 1:
            ans = answers.get(key)
            if ans is None:
                questions.append(Question(
                    id=key,
                    text='وجدت أكثر من بوت في النص. أيّها هو الهدف الرئيسي للمهمة؟',
                    options=[f"@{b['username']}" + (f" (إحالة: {b['ref']})" if b.get('ref') else '') for b in bot_links],
                    default='1'))
                chosen = bot_links[0]
            else:
                idx = self._normalize_choice(ans, len(bot_links))
                if idx:
                    chosen = bot_links[idx - 1]
                else:
                    name = ans.strip().lstrip('@')
                    chosen = next((b for b in bot_links if b['username'].lower() == name.lower()), bot_links[0])
                reasoning.append(f"🎯 اخترت البوت الهدف: @{chosen['username']}")
            return chosen['raw'], 'bot'
        if bot_links:
            b = bot_links[0]
            reasoning.append(f"🎯 الهدف الرئيسي: البوت @{b['username']}" + (f" برمز إحالة «{b['ref']}»" if b.get('ref') else ''))
            return b['raw'], 'bot'
        if post_links:
            reasoning.append(f"🎯 الهدف الرئيسي: المنشور {post_links[0]['raw']}")
            return post_links[0]['raw'], 'post'
        if channel_links:
            names = ", ".join('@' + c['username'] for c in channel_links)
            reasoning.append(f"🎯 الهدف الرئيسي: القناة/القنوات {names}")
            return channel_links[0]['username'], 'channel'
        if invite_links:
            reasoning.append(f"🎯 الهدف الرئيسي: رابط دعوة خاص {invite_links[0]['raw']}")
            return invite_links[0]['raw'], 'invite'
        # لا روابط: ربما اسم مستخدم بدون @
        for l in lines:
            m = _USERNAME_RE.match(l)
            if m:
                name = m.group(1)
                kind = 'bot' if name.lower().endswith('bot') else 'channel'
                reasoning.append(f"🎯 اعتبرت «{name}» معرّف {'بوت' if kind == 'bot' else 'قناة'}.")
                return (f"https://t.me/{name}" if kind == 'bot' else name), kind
        ans = answers.get('no_target')
        if ans:
            name = ans.strip()
            m = _TME_RE.search(name)
            if m:
                path = m.group(1).split('?')[0].split('/')[0]
                kind = 'bot' if path.lower().endswith('bot') or '?start=' in name else 'channel'
                return (name if kind == 'bot' else path), kind
            name = name.lstrip('@')
            kind = 'bot' if name.lower().endswith('bot') else 'channel'
            return (f"https://t.me/{name}" if kind == 'bot' else name), kind
        questions.append(Question(
            id='no_target',
            text='لم أجد رابط بوت أو قناة في النص. اكتب رابط/معرّف الهدف (مثال: https://t.me/SomeBot?start=123 أو @channel)',
            options=[], allow_custom=True))
        reasoning.append("❓ لم أتعرف على هدف (بوت/قناة/منشور) في النص.")
        return '', 'none'

    def _resolve_mode(self, target_kind, manual_steps, intents, post_links, channel_links,
                      bot_links, answers, questions, reasoning) -> Tuple[str, str]:
        """تحديد وضع المهمة ونوعها في المحرك."""
        # منشور -> تفاعل/تصويت/تحويل
        if target_kind == 'post':
            if 'vote_poll' in intents:
                reasoning.append("📋 نوع المهمة: تصويت في استفتاء.")
                return 'vote_poll', 'vote_poll'
            if 'forward' in intents:
                reasoning.append("📋 نوع المهمة: إعادة توجيه رسالة.")
                return 'forward', 'forward'
            if 'react_post' in intents or _EMOJI_RE.search(' '.join(intents)) is None:
                key = 'post_action'
                ans = answers.get(key)
                if 'react_post' in intents or ans:
                    choice = self._normalize_choice(ans or '1', 3)
                    if choice == 2:
                        reasoning.append("📋 نوع المهمة: تصويت في استفتاء.")
                        return 'vote_poll', 'vote_poll'
                    if choice == 3:
                        reasoning.append("📋 نوع المهمة: إعادة توجيه رسالة.")
                        return 'forward', 'forward'
                    reasoning.append("📋 نوع المهمة: تفاعل على منشور.")
                    return 'react_post', 'react_post'
                questions.append(Question(
                    id=key, text='الرابط يشير إلى منشور. ماذا تريد أن أفعل به؟',
                    options=['تفاعل (إيموجي) على المنشور', 'تصويت في الاستفتاء', 'إعادة توجيه الرسالة إلى بوت'],
                    default='1'))
                return 'react_post', 'react_post'

        # خطوات يدوية صريحة
        if manual_steps:
            names = " ← ".join(STEP_LABELS_AR.get(s.get('type'), s.get('type')) for s in manual_steps)
            reasoning.append(f"📋 نوع المهمة: يدوية بخطوات محددة ({len(manual_steps)}): {names}")
            return 'manual', 'manual'

        # قناة فقط (بدون بوت)
        if target_kind in ('channel', 'invite') and not bot_links:
            reasoning.append("📋 نوع المهمة: متابعة/انضمام للقنوات المذكورة.")
            return 'follow_channel', 'follow_channel'

        # بوت
        if target_kind == 'bot':
            if 'start' in intents and not any(i in intents for i in ('subscribe', 'phone', 'math')) and len(intents) == 1:
                reasoning.append("📋 نوع المهمة: ذكية - تبدأ بـ /start ويكمل الذكاء الاصطناعي بقية الخطوات تلقائياً.")
                return 'smart', 'composite'
            reasoning.append("📋 نوع المهمة: ذكية (الذكاء الاصطناعي يحلل رسائل البوت خطوة بخطوة).")
            return 'smart', 'composite'

        reasoning.append("📋 نوع المهمة: ذكية (افتراضي).")
        return 'smart', 'composite'

    def _describe_execution(self, mode, task_type, target, steps, channel_list, emoji_target,
                            vote_option, target_message_link, accounts, speed) -> List[str]:
        out: List[str] = []
        out.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        out.append(f"📌 الخطة: {TASK_TYPE_LABELS_AR.get(task_type, task_type)}")
        if target:
            out.append(f"🎯 الهدف: {target}")
        if mode == 'smart':
            out.append("1️⃣ إرسال /start (مع رمز الإحالة إن وُجد) لكل حساب")
            out.append("2️⃣ قراءة رد البوت وتحليله بالذكاء الاصطناعي")
            out.append("3️⃣ تنفيذ الإجراء المناسب (اشتراك/تحقق/معادلة/رقم/إيموجي) حتى رسالة النجاح")
            out.append("4️⃣ حفظ الخطوات الناجحة كقالب لاستخدامه مع بقية الحسابات")
        elif mode == 'manual':
            out.append("1️⃣ إرسال /start للبوت")
            for i, s in enumerate(steps, 2):
                label = STEP_LABELS_AR.get(s.get('type'), s.get('type'))
                extra = ''
                if s.get('channels'):
                    extra = f" ({', '.join(s['channels'])})"
                elif s.get('text_to_send'):
                    extra = f" «{s['text_to_send'][:30]}»"
                elif s.get('target_text'):
                    extra = f" «{s['target_text'][:30]}»"
                elif s.get('target_link'):
                    extra = f" ({s['target_link']})"
                out.append(f"{i}️⃣ {label}{extra}")
        elif mode == 'follow_channel':
            out.append(f"1️⃣ الانضمام إلى {len(channel_list) or 1} قناة/مجموعة بكل حساب: {', '.join(channel_list[:5])}")
        elif mode == 'react_post':
            out.append(f"1️⃣ التفاعل بـ {emoji_target} على {target_message_link or target}")
        elif mode == 'vote_poll':
            out.append(f"1️⃣ التصويت بالخيار «{vote_option}» في {target_message_link or target}")
        elif mode == 'forward':
            out.append(f"1️⃣ إعادة توجيه {target_message_link} إلى {target}")
        out.append(f"👥 عدد الحسابات: {accounts} | ⚡ السرعة: {SPEED_LABELS_AR.get(speed, speed)}")
        out.append("━━━━━━━━━━━━━━━━━━━━━━━━")
        return out


__all__ = ['TaskPlanner', 'Plan', 'Question', 'STEP_LABELS_AR', 'TASK_TYPE_LABELS_AR', 'SPEED_LABELS_AR']
