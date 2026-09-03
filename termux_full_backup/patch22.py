#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AlSarab Patch22: إصلاح جذري لمشكلتين سببهما تطويرات سابقة
============================================================
المشكلة 1: "منع التكرار (dedup)" كان يعلّم بقية الحسابات "مكتملة"
           فور نجاح حساب واحد -> الحسابات الأخرى لم تنفذ المهمة أبداً
           (المستخدم يريد كل حساب يجمع مكافأته الخاصة)
  الحل: إزالة كتلة dedup نهائياً - كل حساب ينفذ المهمة بنفسه

المشكلة 2: كشف تحدي الإيموجي كان يعتبر أي رسالة فيها إيموجي
           (مثل 🚀 في رسالة ترحيب) "تحدي إيموجي" -> قرار خاطئ match_emoji
  الحل: تحدي الإيموجي يُكشف فقط إذا وُجد الإيموجي في أزرار الرسالة
        (أزرار فيها إيموجيات للمطابقة) - وليس في النص فقط
التشغيل:  python patch22.py   (من داخل مجلد المشروع)
"""
import os
import sys

# ============================================================
# 1) تعديل worker.py: إزالة dedup
# ============================================================
wpath = "worker.py"
if not os.path.exists(wpath):
    print(f"❌ {wpath} غير موجود. شغّل من داخل مجلد المشروع.")
    sys.exit(1)

src = open(wpath, encoding="utf-8").read()
wdone = []

old_dedup = """                # v2.1.5: منع التكرار - علّم بقية الأطفال لنفس المهمة مكتملة فوراً
                _parent_id = task.get('parent_task_id')
                if _parent_id:
                    try:
                        await async_supabase_query(
                            lambda: supabase.table('tasks_queue').update({
                                'status': 'completed',
                                'completed_at': datetime.now(timezone.utc).isoformat(),
                                'error_message': 'Dedup: completed by sibling account'
                            }).eq('parent_task_id', _parent_id).eq('status', 'pending').execute()
                        )
                        logger.info(f"Task {tid[:8]}: siblings marked completed (dedup)")
                    except Exception as e:
                        logger.debug(f"Dedup siblings error: {e}")
"""

if old_dedup in src:
    src = src.replace(old_dedup, "")
    wdone.append("1) worker: أُزيل dedup - كل حساب ينفذ المهمة بنفسه")
else:
    print("⚠️ worker: لم أجد كتلة dedup - قد تكون أُزيلت بالفعل")

# رفع إصدار worker
src = src.replace(" Worker Engine v2.2.2 (Professional) - Termux Optimized",
                  " Worker Engine v2.2.3 (Professional) - Termux Optimized")
src = src.replace("CHANGELOG v2.2.2 (Professional):", "CHANGELOG v2.2.3 (Professional):")
src = src.replace('logger.info("Starting Worker Engine v2.2.2 (Professional)")',
                  'logger.info("Starting Worker Engine v2.2.3 (Professional)")')
if " 42. [FIX]" not in src:
    src = src.replace(" 41. [FIX] كشف القائمة الذكي: أزرار بدون روابط = نهاية، أزرار قنوات = تنفيذ اشتراك تلقائي + أي زر t.me = قناة\n================",
                      " 41. [FIX] كشف القائمة الذكي: أزرار بدون روابط = نهاية، أزرار قنوات = تنفيذ اشتراك تلقائي + أي زر t.me = قناة\n"
                      " 42. [FIX] إزالة dedup: كل حساب ينفذ المهمة بنفسه (لا يُعلَّم مكتملاً كذباً)\n"
                      "================")
open(wpath, "w", encoding="utf-8").write(src)

# ============================================================
# 2) تعديل ai_agent.py: إصلاح كشف الإيموجي
# ============================================================
apath = "ai_agent.py"
adone = []
if os.path.exists(apath):
    asrc = open(apath, encoding="utf-8").read()

    old_emoji = """            # تحقق هل الأزرار تحتوي على إيموجي
            buttons = self._extract_buttons_from_message(raw_message)
            for btn in buttons:
                if target in btn.get('text', ''):
                    return target
            # حتى لو لم يوجد في الأزرار، نعتبره تحدي إيموجي
            if text_emojis:
                return target
        except Exception:
            pass
        return None"""

    new_emoji = """            # تحقق هل الأزرار تحتوي على إيموجي (تحدي حقيقي = أزرار للمطابقة)
            buttons = self._extract_buttons_from_message(raw_message)
            for btn in buttons:
                if target in btn.get('text', ''):
                    return target
            # v2.2.3: لا نعتبره تحدياً إذا لم يوجد الإيموجي في الأزرار
            # (رسالة ترحيب فيها 🚀 ليست تحدياً)
            return None
        except Exception:
            pass
        return None"""

    if old_emoji in asrc:
        asrc = asrc.replace(old_emoji, new_emoji, 1)
        adone.append("2) ai_agent: تحدي الإيموجي فقط إذا وُجد في الأزرار")
    else:
        print("⚠️ ai_agent: لم أجد كتلة كشف الإيموجي - قد تكون معدلة بالفعل")

    asrc = asrc.replace("AlSarab ShopBot v3.0 - AI Agent System (FIXED v3.0.1)",
                        "AlSarab ShopBot v3.0 - AI Agent System (FIXED v3.0.2)")
    open(apath, "w", encoding="utf-8").write(asrc)
else:
    print("⚠️ ai_agent.py غير موجود")

# ============================================================
# ملخص
# ============================================================
print("  ✅ " + "\n  ✅ ".join(wdone + adone))
final_w = open(wpath, encoding="utf-8").read()
final_a = open(apath, encoding="utf-8").read()
if "v2.2.3" in final_w and "v3.0.2" in final_a:
    print("\n🎉 PATCH22 COMPLETE - worker.py v2.2.3 + ai_agent.py v3.0.2")
    print("   شغّل الآن:  python worker.py")
else:
    print("\n⚠️ تحقق: grep -n 'v2.2.3' worker.py && grep -n 'v3.0.2' ai_agent.py")
