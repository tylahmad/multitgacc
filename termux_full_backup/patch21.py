#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AlSarab Patch21: worker.py -> v2.2.2 (الإصلاح الشامل لكشف القائمة والاشتراك)
============================================================
 1) كشف القائمة الرئيسية الذكي:
    - أزرار بدون روابط >= 6 = قائمة رئيسية حقيقية = نهاية
    - أزرار بروابط t.me = رسالة اشتراك إجباري -> تنفيذ الاشتراك تلقائياً
 2) الانضمام للقنوات: أي زر برابط t.me (وليس bot) = قناة انضمام
    (نصوص الأزرار قد لا تحتوي كلمة "اشترك" مثل Amer🔥ichancy)
 3) يضغط زر "تحقق من الاشتراك" بعد الانضمام
التشغيل:  python patch21.py   (من داخل مجلد المشروع)
"""
import os
import sys

path = "worker.py"
if not os.path.exists(path):
    print(f"❌ {path} غير موجود. شغّل من داخل مجلد المشروع.")
    sys.exit(1)

src = open(path, encoding="utf-8").read()
done = []

# ============ 1) كشف القائمة الذكي ============
old_menu = """                # كشف القائمة الرئيسية: رسالة بها >= 5 أزرار = لوحة تحكم = نهاية التدفق
                if not is_success:
                    try:
                        btn_list = self.parser.extract_buttons(msg)
                        if len(btn_list) >= 6:
                            is_success = True
                            logger.info(f"Smart loop: main menu detected ({len(btn_list)} buttons) -> success")
                    except Exception:
                        pass"""

new_menu = """                # v2.2.1: كشف القائمة الرئيسية الذكي
                if not is_success:
                    try:
                        markup = getattr(msg, 'reply_markup', None)
                        non_url_count = 0
                        has_sub_links = False
                        if markup is not None:
                            rows = getattr(markup, 'rows', None)
                            if rows:
                                for _row in rows:
                                    for _btn in _row.buttons:
                                        _url = getattr(_btn, 'url', None)
                                        if _url:
                                            if 't.me/' in str(_url):
                                                has_sub_links = True
                                        else:
                                            non_url_count += 1
                        if non_url_count >= 6 and not has_sub_links:
                            is_success = True
                            logger.info(f"Smart loop: main menu detected ({non_url_count} non-url buttons) -> success")
                        elif has_sub_links:
                            logger.info("Smart loop: subscribe-required detected -> executing subscribe")
                            _sub_ok = await self._handle_subscribe_step([], *self._get_delay(speed))
                            if _sub_ok:
                                await asyncio.sleep(random.uniform(2, 3))
                                continue
                    except Exception:
                        pass"""

if old_menu in src:
    src = src.replace(old_menu, new_menu, 1)
    done.append("1) كشف القائمة الذكي")
else:
    print("⚠️ 1) لم أجد كتلة كشف القائمة - قد يكون مطبقاً بالفعل")

# ============ 2) أي زر برابط t.me = قناة ============
old_link = """                        # زر اشتراك برابط قناة -> استخرج القناة وانضم لها
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
                                logger.debug(f"SUBSCRIBE_STEP: join from url error {url}: {e}")"""

new_link = """                        # زر اشتراك برابط قناة -> استخرج القناة وانضم لها
                        # v2.2.2: أي زر برابط t.me (وليس bot/خدمة) = قناة انضمام
                        _is_channel_link = False
                        if url and 't.me/' in str(url):
                            _u_name = str(url).split('t.me/')[-1].split('?')[0].split('/')[0].strip().lower()
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
                                logger.debug(f"SUBSCRIBE_STEP: join from url error {url}: {e}")"""

if old_link in src:
    src = src.replace(old_link, new_link, 1)
    done.append("2) أي زر t.me = قناة")
else:
    print("⚠️ 2) لم أجد كتلة أزرار القنوات - قد تكون مطبقة بالفعل")

# ============ رفع الإصدار ============
for old_v in ("v2.2.1", "v2.2.0", "v2.1.8", "v2.1.7", "v2.1.6", "v2.1.5"):
    src = src.replace(f" Worker Engine {old_v} (Professional) - Termux Optimized",
                      " Worker Engine v2.2.2 (Professional) - Termux Optimized")
    src = src.replace(f"CHANGELOG {old_v} (Professional):", "CHANGELOG v2.2.2 (Professional):")
    src = src.replace(f'logger.info("Starting Worker Engine {old_v} (Professional)")',
                      'logger.info("Starting Worker Engine v2.2.2 (Professional)")')

if " 41. [FIX]" not in src:
    src = src.replace(" 40. [FIX] إزالة النجاح الكاذب: click_best/retry لم تعد تنهي المهمة - التكرار يُكشف ببصمة الرسالة فقط\n================",
                      " 40. [FIX] إزالة النجاح الكاذب: click_best/retry لم تعد تنهي المهمة - التكرار يُكشف ببصمة الرسالة فقط\n"
                      " 41. [FIX] كشف القائمة الذكي: أزرار بدون روابط = نهاية، أزرار قنوات = تنفيذ اشتراك تلقائي + أي زر t.me = قناة\n"
                      "================")

open(path, "w", encoding="utf-8").write(src)

final = open(path, encoding="utf-8").read()
if "v2.2.2" in final and "subscribe-required detected" in final:
    print("\n".join(done))
    print("\n🎉 PATCH21 COMPLETE - worker.py الآن v2.2.2 (الإصلاح الشامل)")
    print("   شغّل الآن:  python worker.py")
else:
    print("\n⚠️ اكتمل الحفظ - تحقق: grep -n 'v2.2.2' worker.py")
