# -*- coding: utf-8 -*-
"""
════════════════════════════════════════════════════════════════════════
  TeleSession • أداة احترافية لتسجيل جلسات Telethon (.session)
  ─────────────────────────────────────────────────────────────────────
  التقنيات   : Flask + Telethon + asyncio
  التشغيل    : pip install flask telethon
               python sessionsell.py
  الواجهة   : http://127.0.0.1:5000
  ─────────────────────────────────────────────────────────────────────
  قبل الاستخدام:
  1) احصل على API_ID و API_HASH من: https://my.telegram.org
  2) اضبطهما كمتغيرات بيئة ثم شغّل التطبيق:
       ويندوز :  set TELEGRAM_API_ID=123456
                 set TELEGRAM_API_HASH=xxxxxxxx
       لينكس   :  export TELEGRAM_API_ID=123456
                  export TELEGRAM_API_HASH=xxxxxxxx
  ─────────────────────────────────────────────────────────────────────
  الخصوصية:
  ملفات الجلسة تُحفظ مؤقتًا فقط داخل مجلد Temporary الخاص بنظام
  التشغيل، وتُحذف تلقائيًا بعد التحميل مباشرة، أو بعد انقضاء مهلة
  ساعتين، أو عند إغلاق التطبيق. لا يوجد أي تخزين دائم لبيانات حساسة.
════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import asyncio
import atexit
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from telethon import TelegramClient
from telethon import utils as tg_utils
from telethon.errors import (
    AuthKeyUnregisteredError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeEmptyError,
    PhoneCodeExpiredError,
    PhoneCodeHashEmptyError,
    PhoneCodeInvalidError,
    PhoneMigrateError,
    PhoneNumberAppSignupForbiddenError,
    PhoneNumberBannedError,
    PhoneNumberUnoccupiedError,
    RPCError,
    SessionPasswordNeededError,
)

# ═══════════════════════════════ الإعدادات ═══════════════════════════════

# بيانات API من متغيرات البيئة (لا نكتبها داخل الملف حفاظًا على الأمان)
API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or 0)
API_HASH = os.getenv("TELEGRAM_API_HASH", "") or ""

# عنوان الاستماع: افتراضيًا 127.0.0.1 كما هو مطلوب،
# ويمكن تغييره عند الحاجة عبر متغيرات البيئة
APP_HOST = os.getenv("SESSIONSELL_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("SESSIONSELL_PORT", "5000"))

# مهلة بقاء ملف الجلسة في المجلد المؤقت قبل حذفه التلقائي (بالثواني)
SESSION_TTL = 2 * 60 * 60

# مجلد مؤقت خاص بنا داخل مجلد المؤقتات الخاص بنظام التشغيل
SESSIONS_DIR = Path(tempfile.gettempdir()) / "telesell_sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.json.ensure_ascii = False  # إرجاع النصوص العربية كما هي في JSON

# ═══════════════════ حلقة asyncio المستقلة الخاصة بـ Telethon ═══════════════════
# Flask يستقبل الطلبات من خيوط (threads) متعددة، بينما تعمل مكتبة Telethon
# داخل حلقة asyncio واحدة مستقرة. لذلك نطلق حلقة خاصة في خيط مستقل،
# ونرسل إليها مهام Telethon عبر run_coroutine_threadsafe ثم ننتظر النتيجة.

_async_loop = asyncio.new_event_loop()


def _run_async_loop() -> None:
    """دالة الخيط المستقل: تشغيل حلقة asyncio بشكل دائم."""
    asyncio.set_event_loop(_async_loop)
    _async_loop.run_forever()


threading.Thread(target=_run_async_loop, daemon=True, name="telethon-loop").start()


def _run_in_loop(coro, timeout: int = 90):
    """تشغيل مهمة (coroutine) في حلقة Telethon وانتظار نتيجتها."""
    return asyncio.run_coroutine_threadsafe(coro, _async_loop).result(timeout=timeout)


# الجولات الجارية: "الرقم (أرقام فقط)" ← كائن TelegramClient
_active_clients: dict = {}


def _close_client(phone: str) -> None:
    """إغلاق العميل السابق المرتبط بالرقم (إن وُجد)."""
    old = _active_clients.pop(phone, None)
    if old is None:
        return
    try:
        _run_in_loop(old.disconnect(), timeout=10)
    except Exception:
        pass


def _cleanup_old_files() -> None:
    """حذف ملفات الجلسة المؤقتة التي انقضت مهلتها."""
    now = time.time()
    for f in SESSIONS_DIR.glob("*.session"):
        try:
            if now - f.stat().st_mtime > SESSION_TTL:
                f.unlink()
        except OSError:
            pass


@atexit.register
def _shutdown() -> None:
    """عند إغلاق التطبيق: قطع الاتصالات وحذف أي ملفات متبقية."""
    for phone, client in list(_active_clients.items()):
        try:
            asyncio.run_coroutine_threadsafe(client.disconnect(), _async_loop)
        except Exception:
            pass
    _cleanup_old_files()


# ═══════════════════════════════ أدوات مساعدة ═══════════════════════════════

def _clean_phone(raw) -> str | None:
    """تطبيع رقم الهاتف إلى سلسلة أرقام، أو إرجاع None إذا كان غير صالح."""
    try:
        phone = tg_utils.parse_phone(raw)
    except Exception:
        return None
    if not phone or not phone.isdigit() or not (8 <= len(phone) <= 15):
        return None
    return phone


def _rpc_error_response(exc: Exception):
    """تحويل أخطاء Telethon إلى رسائل عربية واضحة داخل استجابة JSON."""
    if isinstance(exc, PhoneCodeEmptyError):
        msg = "رمز التحقق فارغ — أدخل الرمز المكوّن من 5 أو 6 أرقام."
    elif isinstance(exc, PhoneCodeExpiredError):
        msg = "انتهت صلاحية رمز التحقق — اطلب رمزًا جديدًا."
    elif isinstance(exc, (PhoneCodeInvalidError, PhoneCodeHashEmptyError)):
        msg = "رمز التحقق غير صحيح — تأكد من الرمز ثم أعد المحاولة."
    elif isinstance(exc, SessionPasswordNeededError):
        msg = "هذا الحساب محمي بكلمة مرور إضافية (2FA) — أدخلها في الحقل المخصص ثم أعد المحاولة."
    elif isinstance(exc, PasswordHashInvalidError):
        msg = "كلمة المرور الإضافية (2FA) غير صحيحة — حاول مجددًا."
    elif isinstance(exc, PhoneNumberBannedError):
        msg = "عذرًا — هذا الرقم محظور من استخدام تيليجرام."
    elif isinstance(exc, (PhoneNumberUnoccupiedError, PhoneNumberAppSignupForbiddenError)):
        msg = ("هذا الرقم غير مسجّل في تيليجرام. إنشاء حسابات جديدة عبر تطبيقات "
               "طرف ثالث لا يُدعَم حاليًا وفق سياسة تيليجرام.")
    elif isinstance(exc, PhoneMigrateError):
        msg = "وقع خطأ في ترحيل الرقم — أعد المحاولة بعد قليل."
    elif isinstance(exc, AuthKeyUnregisteredError):
        msg = "الجلسة الحالية غير صالحة — اطلب رمزًا جديدًا وابدأ من جديد."
    elif isinstance(exc, FloodWaitError):
        msg = f"تم تجاوز حد الطلبات — انتظر {exc.seconds} ثانية ثم حاول مجددًا."
    else:
        msg = f"حدث خطأ أثناء الاتصال بخوادم تيليجرام: {exc.__class__.__name__}"
    return jsonify(status="error", message=msg)


# ═══════════════════════════════════ المسارات ═══════════════════════════════════

@app.route("/")
def index():
    """الصفحة الرئيسية — واجهة الخطوات الثلاث."""
    return render_template("index.html")


@app.route("/request_code", methods=["POST"])
def request_code():
    """الخطوة 1 — إرسال رمز التحقق إلى رقم الهاتف."""
    data = request.get_json(silent=True) or {}
    phone = _clean_phone(data.get("phone", ""))

    if phone is None:
        return jsonify(
            status="error",
            message="رقم الهاتف غير صالح — أدخله بالصيغة الدولية، مثال: ‎+9665xxxxxxxx",
        )

    if not API_ID or not API_HASH:
        return jsonify(
            status="error",
            message=("⚠️ التطبيق غير مُهيأ بعد — اضبط TELEGRAM_API_ID و TELEGRAM_API_HASH "
                     "(من my.telegram.org) ثم أعد تشغيل التطبيق."),
        )

    # إغلاق أي عميل سابق مرتبط بالرقم نفسه
    _close_client(phone)

    # اسم جلسة فريد لكل طلب حتى لا تتداخل الجولات
    session_name = f"tsess_{phone}_{uuid.uuid4().hex[:8]}"

    async def _send_code():
        client = TelegramClient(str(SESSIONS_DIR / session_name), API_ID, API_HASH)
        await client.connect()
        result = await client.send_code_request(phone)
        return client, result.sent

    try:
        client, code_type = _run_in_loop(_send_code(), timeout=60)
    except RPCError as exc:
        return _rpc_error_response(exc)
    except Exception as exc:
        app.logger.exception("request_code: خطأ غير متوقع")
        return jsonify(status="error", message=f"تعذّر الاتصال بخوادم تيليجرام: {exc}")

    _active_clients[phone] = client

    # نوع قنات وصول الرمز (تطبيق / رسالة / اتصال هاتفي)
    channel = {
        "sms": "رسالة نصية (SMS)",
        "call": "اتصال هاتفي",
        "app": "تطبيق تيليجرام",
    }.get(getattr(code_type, "code_type", ""), "التطبيق")

    return jsonify(status="ok", message=f"تم إرسال رمز التحقق عبر {channel} — تحقق من جوالك.")


@app.route("/verify_code", methods=["POST"])
def verify_code():
    """الخطوة 2 — التحقق من الرمز وتسجيل الدخول، ثم إرجاع معلومات الحساب."""
    data = request.get_json(silent=True) or {}
    phone = _clean_phone(data.get("phone", ""))
    code = str(data.get("code", "") or "").strip().replace(" ", "")
    password = str(data.get("password", "") or "").strip() or None

    if phone is None:
        return jsonify(status="error", message="رقم الهاتف غير صالح.")
    if not code:
        return jsonify(status="error", message="أدخل رمز التحقق أولًا.")

    client = _active_clients.get(phone)
    if client is None:
        return jsonify(
            status="error",
            message="انتهت صلاحية هذه الجولة — اطلب رمز تحقق جديدًا (الخطوة 1).",
        )

    async def _verify():
        # تسجيل الدخول: الرمز للحسابات العادية
        try:
            user = await client.sign_in(phone, code=code)
        except SessionPasswordNeededError:
            # الحساب محمي بـ 2FA — نستخدم كلمة المرور الإضافية إن وُجدت
            if not password:
                raise
            user = await client.sign_in(phone, password=password)

        # التأكد من كتابة ملف الجلسة على القرص
        save = client.session.save()
        if asyncio.iscoroutine(save):
            await save
        session_file = Path(client.session.filename).name

        # القطع عن الخادم — الملف المحلي يكفي من الآن فصاعدًا
        await client.disconnect()
        return user, session_file

    try:
        user, session_file = _run_in_loop(_verify(), timeout=120)
    except SessionPasswordNeededError:
        return jsonify(
            status="password_required",
            message="هذا الحساب محمي بكلمة مرور إضافية (2FA) — أدخلها في الحقل المخصص ثم أعد المحاولة.",
        )
    except RPCError as exc:
        return _rpc_error_response(exc)
    except Exception as exc:
        app.logger.exception("verify_code: خطأ غير متوقع")
        return jsonify(status="error", message=f"فشل تسجيل الدخول: {exc}")

    _active_clients.pop(phone, None)

    full_name = " ".join(p for p in (user.first_name, user.last_name) if p)
    return jsonify(
        status="success",
        message="تم تسجيل الدخول بنجاح!",
        account={
            "id": user.id,
            "name": full_name or "—",
            "username": f"@{user.username}" if user.username else "—",
            "phone": f"+{phone}",
        },
        session_file=session_file,
    )


@app.route("/download/<path:filename>")
def download(filename):
    """تحميل ملف الجلسة — يُحذف الملف من القرص فور تسليمه (خصوصية)."""
    # أمان: قبول اسم ملف فقط بدون أي مسار (منع هروب المسار)
    safe_name = os.path.basename(filename)
    sessions_dir = SESSIONS_DIR.resolve()
    file_path = (sessions_dir / safe_name).resolve()

    try:
        file_path.relative_to(sessions_dir)
    except ValueError:
        return jsonify(status="error", message="طلب غير صالح."), 400

    if not file_path.is_file():
        return jsonify(status="error", message="الملف غير موجود — ربما حُذف بعد انتهاء مهلته."), 404

    # قراءة الملف ثم حذفه فورًا: لا تخزين دائم لبيانات حساسة
    data = file_path.read_bytes()
    try:
        file_path.unlink()
    except OSError:
        pass

    # تخلص من أي عميل مرتبط بهذا الملف
    for p in [p for p, c in list(_active_clients.items())
              if Path(c.session.filename).name == safe_name]:
        _close_client(p)

    return Response(
        data,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# ═══════════════════════════════ التشغيل ═══════════════════════════════

if __name__ == "__main__":
    # تنظيف بقايا تشغيل سابق عند البدء
    _cleanup_old_files()

    print("════════════════════════════════════════════")
    print("  TeleSession جاهز — افتح: http://127.0.0.1:5000")
    if not (API_ID and API_HASH):
        print("  ⚠️  تنبيه: TELEGRAM_API_ID / TELEGRAM_API_HASH غير مضبوطة")
        print("════════════════════════════════════════════")
    app.run(host=APP_HOST, port=APP_PORT, threaded=True, debug=False, use_reloader=False)
