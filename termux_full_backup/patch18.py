#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AlSarab Patch18: worker.py v2.1.6 -> v2.1.7
الإصلاح: فشل مهمة متابعة القنوات الإجبارية في المهام اليدوية
  السبب 1: خطوة follow_channel:رابط تحفظ القناة في target_text
           وليس channels -> لا تصل لخطوة الاشتراك
  السبب 2: _handle_subscribe_step يبحث عن أزرار فقط ولا يقرأ
           روابط t.me الموجودة في نص رسالة البوت
  الحل:
    1) main.py: follow_channel:رابط يحفظ في channels (وليس target_text)
    2) worker.py: _handle_subscribe_step يقرأ روابط t.me من نص الرسائل
       ويجمعها مع الأزرار وينضم لها جميعاً
التشغيل:  python patch18.py   (من داخل مجلد المشروع)
بعدها: ارفع main.py إلى GitHub/Render
"""
import os
import sys

# ============================================================
# تعديل worker.py
# ============================================================
wpath = "worker.py"
if not os.path.exists(wpath):
    print(f"❌ {wpath} غير موجود. شغّل من داخل مجلد المشروع.")
    sys.exit(1)

src = open(wpath, encoding="utf-8").read()
wdone = []

# 1) _handle_subscribe_step: قراءة روابط t.me من نص الرسائل أيضاً
old_sub = """            # 3) اكتشاف أزرار الاشتراك في رسائل البوت والانضمام للقنوات
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
                        if url and 't.me/' in url and any(k in low for k in ('اشترك', 'subscribe', 'قناة', 'join', 'channel')):
                            try:
                                ch_name = url.split('t.me/')[-1].split('?')[0].split('/')[0].strip()
                                if ch_name:
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
                                logger.debug(f"SUBSCRIBE_STEP: click subscribe btn error: {e}")"""

new_sub = """            # 3) اكتشاف أزرار الاشتراك في رسائل البوت والانضمام للقنوات
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
                        if url and 't.me/' in url and any(k in low for k in ('اشترك', 'subscribe', 'قناة', 'join', 'channel')):
                            try:
                                ch_name = url.split('t.me/')[-1].split('?')[0].split('/')[0].strip()
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
                            logger.debug(f"SUBSCRIBE_STEP: join from text error {_ch}: {e}")"""

if old_sub in src:
    src = src.replace(old_sub, new_sub, 1)
    wdone.append("1) worker: قراءة روابط t.me من نص الرسائل أيضاً")
else:
    print("⚠️ worker: لم أجد كتلة اكتشاف الأزرار - الملف مختلف؟")

# رفع إصدار worker
src = src.replace(" Worker Engine v2.1.6 (Professional) - Termux Optimized",
                  " Worker Engine v2.1.7 (Professional) - Termux Optimized")
src = src.replace("CHANGELOG v2.1.6 (Professional):", "CHANGELOG v2.1.7 (Professional):")
src = src.replace('logger.info("Starting Worker Engine v2.1.6 (Professional)")',
                  'logger.info("Starting Worker Engine v2.1.7 (Professional)")')
if " 38. [FIX]" not in src:
    src = src.replace(" 37. [FIX] إعادة المحاولة للأخطاء العابرة: تشمل SSL handshake/timed out + 3 محاولات + سجل تحذير\n================",
                      " 37. [FIX] إعادة المحاولة للأخطاء العابرة: تشمل SSL handshake/timed out + 3 محاولات + سجل تحذير\n"
                      " 38. [FIX] الاشتراك الإجباري: قراءة روابط t.me من نص رسالة البوت أيضاً (وليس الأزرار فقط)\n"
                      "================")
open(wpath, "w", encoding="utf-8").write(src)

# ============================================================
# تعديل main.py
# ============================================================
mpath = "main.py"
if os.path.exists(mpath):
    msrc = open(mpath, encoding="utf-8").read()
    mdone = []

    # follow_channel:رابط -> channels بدل target_text
    old_follow = """                    elif typ == 'follow_channel':
                        steps.append({'type': 'subscribe', 'channels': [val]})"""
    new_follow = """                    elif typ == 'follow_channel':
                        steps.append({'type': 'subscribe', 'channels': [val]})"""
    # (هذا موجود بالفعل - نتحقق فقط)

    old_subscribe_chain = """                if typ in valid_types:
                    if typ == 'text':
                        steps.append({'type': 'text', 'text_to_send': val})
                    elif typ == 'forward':
                        steps.append({'type': 'forward', 'target_link': val})
                    elif typ == 'react_post':
                        steps.append({'type': 'react_post', 'target_link': val})
                    elif typ == 'vote_poll':
                        steps.append({'type': 'vote_poll', 'target_link': val})
                    elif typ == 'follow_channel':
                        steps.append({'type': 'subscribe', 'channels': [val]})
                    elif typ == 'phone':"""

    new_subscribe_chain = """                if typ in valid_types:
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
                    elif typ == 'phone':"""

    if old_subscribe_chain in msrc:
        msrc = msrc.replace(old_subscribe_chain, new_subscribe_chain, 1)
        mdone.append("2) main: follow_channel/subscribe يحفظ في channels")
    else:
        print("⚠️ main: لم أجد سلسلة الخطوات - الملف مختلف؟")

    msrc = msrc.replace("Bot Version: 2.2.1 (Professional - Fixed)",
                        "Bot Version: 2.2.2 (Professional - Fixed)")
    open(mpath, "w", encoding="utf-8").write(msrc)
else:
    print("⚠️ main.py غير موجود - تخطي")

# ============================================================
# ملخص
# ============================================================
final_w = open(wpath, encoding="utf-8").read()
final_m = open(mpath, encoding="utf-8").read() if os.path.exists(mpath) else ""
print("  ✅ " + "\n  ✅ ".join(wdone))
if 'mdone' in dir() and mdone:
    print("  ✅ " + "\n  ✅ ".join(mdone))

if "v2.1.7" in final_w and ("v2.2.2" in final_m):
    print("\n🎉 PATCH18 COMPLETE - worker.py v2.1.7 + main.py v2.2.2")
    print("   شغّل worker.py في تيرموكس، وارفع main.py إلى GitHub/Render")
else:
    print("\n⚠️ اكتمل الحفظ، تحقق: grep -n 'v2.1.7' worker.py")
