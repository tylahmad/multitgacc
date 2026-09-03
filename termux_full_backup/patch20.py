#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AlSarab Patch20: worker.py v2.1.8 -> v2.2.0 (إعادة الذكاء للحلقة)
============================================================
الإصلاح الجوهري لكشف التكرار الخاطئ (الذي جعل الحلقة "غبية"):
  المشكلة:
    1) click_best (ضغط أفضل زر) كان يُعد "تكراراً بلا تقدم"
       -> ينهي المهمة قبل تنفيذ أي زر!
    2) return True + record_completion = نجاح كاذب يُسجل المهمة مكتملة
       وهي لم تُنجز إطلاقاً
  الحل:
    1) كشف التكرار فقط عند: نفس الرسالة + نفس القرار 4 مرات متتالية
       (تتبع بصمة الرسالة - إن تغير النص فهذا تقدم حقيقي)
    2) عند التكرار الحقيقي: return False (فشل يُعاد بالمحاولة)
       وليس نجاحاً كاذباً
    3) حذف record_completion من مسار التكرار نهائياً
التشغيل:  python patch20.py   (من داخل مجلد المشروع)
"""
import os
import sys

path = "worker.py"
if not os.path.exists(path):
    print(f"❌ {path} غير موجود. شغّل من داخل مجلد المشروع.")
    sys.exit(1)

src = open(path, encoding="utf-8").read()
done = []

# ============================================================
# استبدال كتلة كشف التكرار الخاطئة بالنسخة الذكية
# ============================================================
old_block = """                # v2.1.4: كشف التكرار - نفس القرار 3 مرات متتالية بلا تقدم
                if action == 'retry' or action == 'click_best':
                    self._repeat_count = getattr(self, '_repeat_count', 0) + 1
                    if self._repeat_count >= 3:
                        logger.warning(f"Smart loop: repeated '{action}' 3x without progress -> stopping for {bot_username}")
                        await record_completion(session_id, bot_username, 'composite',
                                                self.task.get('parent_task_id'))
                        return True
                else:
                    self._repeat_count = 0"""

new_block = """                # v2.2.0: كشف التكرار الذكي - فقط نفس الرسالة + نفس القرار 4 مرات
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
                    return False"""

if old_block in src:
    src = src.replace(old_block, new_block, 1)
    done.append("1) كشف التكرار الذكي: بصمة الرسالة + فشل حقيقي (لا نجاح كاذب)")
else:
    print("⚠️ لم أجد كتلة كشف التكرار القديمة - الملف مختلف؟")

# ============================================================
# رفع الإصدار
# ============================================================
src = src.replace(" Worker Engine v2.1.8 (Professional) - Termux Optimized",
                  " Worker Engine v2.2.0 (Professional) - Termux Optimized")
src = src.replace("CHANGELOG v2.1.8 (Professional):", "CHANGELOG v2.2.0 (Professional):")
src = src.replace('logger.info("Starting Worker Engine v2.1.8 (Professional)")',
                  'logger.info("Starting Worker Engine v2.2.0 (Professional)")')

if " 40. [FIX]" not in src:
    src = src.replace(" 39. [FIX] الحلقة الذكية لا تنتهي عند رسالة الترحيب (فصل كلمات البداية عن النهاية)\n================",
                      " 39. [FIX] الحلقة الذكية لا تنتهي عند رسالة الترحيب (فصل كلمات البداية عن النهاية)\n"
                      " 40. [FIX] إزالة النجاح الكاذب: click_best/retry لم تعد تنهي المهمة - التكرار يُكشف ببصمة الرسالة فقط\n"
                      "================")

open(path, "w", encoding="utf-8").write(src)

final = open(path, encoding="utf-8").read()
checks = {
    "v2.2.0": "الإصدار",
    "current_sig": "بصمة الرسالة",
    "return False": "فشل حقيقي (بدل نجاح كاذب)",
}
ok = True
for k, label in checks.items():
    if k in final:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ مفقود: {label}")
        ok = False

# تأكد أن record_completion لم يعد في كتلة التكرار
seg = final[final.find("كشف التكرار الذكي"):final.find("كشف التكرار الذكي") + 600]
if "record_completion" in seg:
    print("  ❌ record_completion ما زال في كتلة التكرار!")
    ok = False
else:
    print("  ✅ record_completion أُزيل من كتلة التكرار")

if ok:
    print("\n🎉 PATCH20 COMPLETE - worker.py الآن v2.2.0 (ذكي فعلاً)")
    print("   شغّل الآن:  python worker.py")
else:
    print("\n⚠️ راجع الملف - بعض العناصر لم تُطبق")
