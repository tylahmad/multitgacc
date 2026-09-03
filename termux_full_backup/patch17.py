#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AlSarab Patch17: worker.py v2.1.5 -> v2.1.6
الإصلاح: "Error fetching sessions: SSL handshake timed out"
  السبب: _is_transient_error كان يبحث عن 'timeout' و'timedout' بينما
         خطأ SSL يقول "timed out" (بمسافة) و"handshake" -> لم يُلتقط
         فلم تعد المحاولة تلقائياً وتأخرت الدورة كاملة
  الحل: توسيع الكلمات المفتاحية + زيادة المحاولات إلى 3 + تنبيه السجل
التشغيل:  python patch17.py   (من داخل مجلد المشروع)
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
# 1) توسيع _is_transient_error
# ============================================================
old_fn = """def _is_transient_error(exc: Exception) -> bool:
    \"\"\"هل الخطأ عابر (شبكة/مهلة) ويستحق إعادة المحاولة؟\"\"\"
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    markers = ('connection', 'connecterror', 'timeout', 'timedout',
               'networkerror', 'readtimeout', 'writetimeout', 'resets',
               'econnrefused', 'dnserror')
    return any(m in name or m in msg for m in markers)"""

new_fn = """def _is_transient_error(exc: Exception) -> bool:
    \"\"\"هل الخطأ عابر (شبكة/مهلة/SSL) ويستحق إعادة المحاولة؟\"\"\"
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    markers = (
        'connection', 'connecterror', 'timeout', 'timedout', 'timed out',
        'networkerror', 'readtimeout', 'writetimeout', 'resets',
        'econnrefused', 'dnserror', 'handshake', 'ssl', 'eof',
        'remote disconnected', 'connection reset', 'temporary failure'
    )
    return any(m in name or m in msg for m in markers)"""

if old_fn in src:
    src = src.replace(old_fn, new_fn, 1)
    done.append("1) _is_transient_error: يشمل timed out / handshake / ssl")
else:
    print("⚠️ لم أجد _is_transient_error - الملف مختلف؟")

# ============================================================
# 2) زيادة المحاولات الافتراضية إلى 3 + سجل تنبيه
# ============================================================
old_retry = """async def async_supabase_query(query_func, *args, _retries: int = 2, **kwargs):
    \"\"\"تشغيل استعلامات Supabase بشكل غير متزامن مع إعادة محاولة للأخطاء العابرة\"\"\"
    last_exc: Optional[Exception] = None
    for attempt in range(_retries + 1):
        try:
            return await asyncio.to_thread(lambda: query_func(*args, **kwargs))
        except Exception as e:
            last_exc = e
            if attempt < _retries and _is_transient_error(e):
                backoff = 0.5 * (attempt + 1)
                logger.debug(f"Supabase transient error ({e}); retry in {backoff}s")
                await asyncio.sleep(backoff)
                continue
            raise
    raise last_exc  # pragma: no cover"""

new_retry = """async def async_supabase_query(query_func, *args, _retries: int = 3, **kwargs):
    \"\"\"تشغيل استعلامات Supabase بشكل غير متزامن مع إعادة محاولة للأخطاء العابرة\"\"\"
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
    raise last_exc  # pragma: no cover"""

if old_retry in src:
    src = src.replace(old_retry, new_retry, 1)
    done.append("2) المحاولات 3 + تأخير تصاعدي + سجل تحذير")
else:
    print("⚠️ لم أجد async_supabase_query - الملف مختلف؟")

# ============================================================
# رفع الإصدار
# ============================================================
src = src.replace(" Worker Engine v2.1.5 (Professional) - Termux Optimized",
                  " Worker Engine v2.1.6 (Professional) - Termux Optimized")
src = src.replace("CHANGELOG v2.1.5 (Professional):", "CHANGELOG v2.1.6 (Professional):")
src = src.replace('logger.info("Starting Worker Engine v2.1.5 (Professional)")',
                  'logger.info("Starting Worker Engine v2.1.6 (Professional)")')

if " 37. [FIX]" not in src:
    src = src.replace(" 36. [ADD] عقل ذكي: phone ينتظر طلب البوت + check يستخدم AI + كل الجلسات تُعالج + الأحدث أولاً + منع التكرار (dedup)\n================",
                      " 36. [ADD] عقل ذكي: phone ينتظر طلب البوت + check يستخدم AI + كل الجلسات تُعالج + الأحدث أولاً + منع التكرار (dedup)\n"
                      " 37. [FIX] إعادة المحاولة للأخطاء العابرة: تشمل SSL handshake/timed out + 3 محاولات + سجل تحذير\n"
                      "================")

open(path, "w", encoding="utf-8").write(src)

final = open(path, encoding="utf-8").read()
checks = {
    "v2.1.6": "الإصدار",
    "'timed out'": "كشف timed out",
    "'handshake'": "كشف handshake",
    "_retries: int = 3": "3 محاولات",
}
ok = True
for k, label in checks.items():
    if k in final:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ مفقود: {label}")
        ok = False

if ok:
    print("\n🎉 PATCH17 COMPLETE - worker.py الآن v2.1.6 (Professional)")
    print("   شغّل الآن:  python worker.py")
else:
    print("\n⚠️ بعض العناصر مفقودة")
