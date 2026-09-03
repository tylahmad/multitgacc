#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================
 ahmadtgmulti.py - tgmultipanel | مدير جلسات Telethon
 الواجهة الرسومية لسطح المكتب (PyQt5) - بديل لوحة تحكم البوت (main.py)
========================================================================
 - تحميل الجلسات من مجلد sessions/ (مع المجلدات الفرعية)
 - إدخال API_ID / API_HASH من الواجهة (بدون .env)
 - تحليل المهمة بالذكاء الاصطناعي (task_planner + ai_agent) وعرض خطوات التفكير
 - نافذة مساعدة عربية عند احتياج الذكاء الاصطناعي لقرار (قبل/أثناء التنفيذ)
 - تنفيذ المهام عبر worker.py بنفس المنطق الأصلي (WorkerEngine.run_once)
 - سجل ملوّن (✅ أخضر / ❌ أحمر / ⚠️ أصفر) + شريط حالة + وضع داكن/فاتح
========================================================================
"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# مجلد البرنامج هو مجلد العمل دائماً (حتى لو شُغّل من مسار آخر)
BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# ------------------------------------------------------------------
# PyQt5
# ------------------------------------------------------------------
try:
    from PyQt5.QtCore import Qt, QObject, QSettings, QThread, QTimer, pyqtSignal, pyqtSlot, QSize
    from PyQt5.QtGui import QColor, QFont, QIcon, QTextCharFormat, QTextCursor, QPixmap, QPainter, QBrush
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
        QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox, QTextEdit, QPlainTextEdit,
        QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QGroupBox, QSplitter,
        QDialog, QDialogButtonBox, QMessageBox, QStatusBar, QAction, QMenu, QToolBar,
        QAbstractItemView, QSizePolicy, QFrame, QButtonGroup, QRadioButton, QScrollArea,
        QProgressBar, QStyle, QFileDialog
    )
except ImportError:  # pragma: no cover
    print("PyQt5 غير مثبت. نفّذ: pip install PyQt5")
    sys.exit(1)

# ------------------------------------------------------------------
# وحدات المشروع
# ------------------------------------------------------------------
IMPORT_ERROR: Optional[str] = None
try:
    import worker
    from task_planner import TaskPlanner, Plan, Question, SPEED_LABELS_AR
except Exception as _e:  # pragma: no cover
    worker = None  # type: ignore
    TaskPlanner = None  # type: ignore
    IMPORT_ERROR = f"{type(_e).__name__}: {_e}\n{traceback.format_exc()}"

APP_TITLE = "ahmadtgmulti.py - tgmultipanel | مدير جلسات Telethon"
APP_VERSION = "1.0.0"
ORG_NAME = "tgmultipanel"
APP_NAME = "ahmadtgmulti"


# ======================================================================
# الأنماط (داكن / فاتح)
# ======================================================================
DARK_QSS = """
QWidget { background-color: #1e1f26; color: #e6e6e6; font-size: 10.5pt; }
QMainWindow, QDialog { background-color: #1e1f26; }
QGroupBox { border: 1px solid #3a3b45; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; font-weight: bold; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; color: #8ab4f8; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background-color: #2a2b35; border: 1px solid #3f404c; border-radius: 6px; padding: 5px 8px; selection-background-color: #3d5afe; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #8ab4f8; }
QComboBox QAbstractItemView { background-color: #2a2b35; selection-background-color: #3d5afe; border: 1px solid #3f404c; }
QPushButton { background-color: #2f3140; border: 1px solid #454657; border-radius: 6px; padding: 7px 14px; font-weight: bold; }
QPushButton:hover { background-color: #3a3c4f; border-color: #8ab4f8; }
QPushButton:pressed { background-color: #24252f; }
QPushButton:disabled { color: #777; background-color: #262733; border-color: #33343f; }
QPushButton#runBtn { background-color: #1f7a3f; border-color: #2ea55a; color: white; }
QPushButton#runBtn:hover { background-color: #23924b; }
QPushButton#stopBtn { background-color: #8a2b2b; border-color: #c0392b; color: white; }
QPushButton#stopBtn:hover { background-color: #a33333; }
QPushButton#clearBtn { background-color: #5a4d1f; border-color: #b8952a; color: white; }
QPushButton#clearBtn:hover { background-color: #6d5d25; }
QTableWidget { background-color: #24252f; gridline-color: #34353f; border: 1px solid #3a3b45; border-radius: 6px; alternate-background-color: #282933; }
QTableWidget::item:selected { background-color: #3d5afe; color: white; }
QHeaderView::section { background-color: #2f3140; color: #cfd8dc; padding: 6px; border: none; border-bottom: 1px solid #3a3b45; font-weight: bold; }
QStatusBar { background-color: #16171d; color: #b0bec5; border-top: 1px solid #2f3140; }
QToolBar { background-color: #16171d; border-bottom: 1px solid #2f3140; spacing: 6px; padding: 4px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; }
QSplitter::handle { background-color: #2f3140; }
QScrollBar:vertical { background: #1e1f26; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: #3f404c; border-radius: 6px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #55576a; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QProgressBar { border: 1px solid #3a3b45; border-radius: 6px; text-align: center; background: #24252f; }
QProgressBar::chunk { background-color: #2ea55a; border-radius: 6px; }
QLabel#hint { color: #9aa0a6; font-size: 9.5pt; }
QLabel#planTitle { color: #8ab4f8; font-weight: bold; font-size: 11.5pt; }
QFrame#botMsg { background-color: #2a2b35; border: 1px solid #3f404c; border-radius: 8px; padding: 8px; }
QMenu { background-color: #2a2b35; border: 1px solid #3f404c; }
QMenu::item:selected { background-color: #3d5afe; }
QToolTip { background-color: #2a2b35; color: #e6e6e6; border: 1px solid #8ab4f8; }
"""

LIGHT_QSS = """
QWidget { background-color: #f5f6fa; color: #1f2328; font-size: 10.5pt; }
QMainWindow, QDialog { background-color: #f5f6fa; }
QGroupBox { border: 1px solid #d0d7de; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; font-weight: bold; background: #ffffff; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; color: #0b57d0; }
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    background-color: #ffffff; border: 1px solid #c9d1d9; border-radius: 6px; padding: 5px 8px; selection-background-color: #0b57d0; selection-color: white; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid #0b57d0; }
QComboBox QAbstractItemView { background-color: #ffffff; selection-background-color: #0b57d0; selection-color: white; border: 1px solid #c9d1d9; }
QPushButton { background-color: #eaeef2; border: 1px solid #c9d1d9; border-radius: 6px; padding: 7px 14px; font-weight: bold; }
QPushButton:hover { background-color: #dde3ea; border-color: #0b57d0; }
QPushButton:pressed { background-color: #cfd6de; }
QPushButton:disabled { color: #9aa0a6; background-color: #eef0f3; border-color: #dfe3e8; }
QPushButton#runBtn { background-color: #1e8e3e; border-color: #188038; color: white; }
QPushButton#runBtn:hover { background-color: #23a047; }
QPushButton#stopBtn { background-color: #d93025; border-color: #c5221f; color: white; }
QPushButton#stopBtn:hover { background-color: #e5473b; }
QPushButton#clearBtn { background-color: #f9ab00; border-color: #e37400; color: #1f2328; }
QPushButton#clearBtn:hover { background-color: #ffbb1f; }
QTableWidget { background-color: #ffffff; gridline-color: #e6e9ee; border: 1px solid #d0d7de; border-radius: 6px; alternate-background-color: #f6f8fa; }
QTableWidget::item:selected { background-color: #0b57d0; color: white; }
QHeaderView::section { background-color: #eaeef2; color: #1f2328; padding: 6px; border: none; border-bottom: 1px solid #d0d7de; font-weight: bold; }
QStatusBar { background-color: #eaeef2; color: #444; border-top: 1px solid #d0d7de; }
QToolBar { background-color: #eaeef2; border-bottom: 1px solid #d0d7de; spacing: 6px; padding: 4px; }
QSplitter::handle { background-color: #d0d7de; }
QScrollBar:vertical { background: #f5f6fa; width: 12px; margin: 0; }
QScrollBar::handle:vertical { background: #c9d1d9; border-radius: 6px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QProgressBar { border: 1px solid #d0d7de; border-radius: 6px; text-align: center; background: #ffffff; }
QProgressBar::chunk { background-color: #1e8e3e; border-radius: 6px; }
QLabel#hint { color: #57606a; font-size: 9.5pt; }
QLabel#planTitle { color: #0b57d0; font-weight: bold; font-size: 11.5pt; }
QFrame#botMsg { background-color: #ffffff; border: 1px solid #c9d1d9; border-radius: 8px; padding: 8px; }
QMenu { background-color: #ffffff; border: 1px solid #c9d1d9; }
QMenu::item:selected { background-color: #0b57d0; color: white; }
QToolTip { background-color: #ffffff; color: #1f2328; border: 1px solid #0b57d0; }
"""

LOG_COLORS = {
    'dark': {'success': '#4cd964', 'error': '#ff5c5c', 'warning': '#ffd166', 'info': '#e6e6e6',
             'ai': '#8ab4f8', 'debug': '#9aa0a6', 'time': '#7f8c8d'},
    'light': {'success': '#1e8e3e', 'error': '#d93025', 'warning': '#b26a00', 'info': '#1f2328',
              'ai': '#0b57d0', 'debug': '#6a737d', 'time': '#8a949e'},
}


def make_app_icon() -> QIcon:
    """أيقونة بسيطة مرسومة برمجياً (بدون ملفات خارجية)."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QBrush(QColor('#2AABEE')))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(2, 2, 60, 60)
    painter.setBrush(QBrush(QColor('white')))
    pts = [(16, 32), (48, 18), (40, 48), (30, 38), (24, 46), (26, 36)]
    from PyQt5.QtGui import QPolygon
    from PyQt5.QtCore import QPoint
    painter.drawPolygon(QPolygon([QPoint(x, y) for x, y in pts]))
    painter.end()
    return QIcon(pix)


# ======================================================================
# جسر السجل: logging -> إشارة Qt
# ======================================================================
class QtLogBridge(QObject, logging.Handler):
    """يحوّل سجلات worker/ai_agent إلى إشارات Qt (آمن بين الخيوط)."""
    record = pyqtSignal(str, str)  # (level_kind, message)

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self)
        self.setLevel(logging.INFO)

    def emit(self, rec: logging.LogRecord):  # type: ignore[override]
        try:
            msg = self.format(rec) if self.formatter else rec.getMessage()
            kind = 'info'
            if rec.levelno >= logging.ERROR:
                kind = 'error'
            elif rec.levelno >= logging.WARNING:
                kind = 'warning'
            low = msg.lower()
            if any(k in low for k in ('completed successfully', 'success detected', 'batch finished',
                                      'joined channel', 'template saved', 'session initialized',
                                      'marked task complete', 'parent ', 'all tasks processed')):
                if 'failed' not in low and 'error' not in low:
                    kind = 'success'
            if rec.name.startswith('AIAgent') or 'ai decision' in low or 'smart loop' in low or 'diag:' in low:
                if kind == 'info':
                    kind = 'ai'
            self.record.emit(kind, msg)
        except Exception:
            pass


# ======================================================================
# طلب مساعدة (من خيط المحرك إلى الواجهة) - جسر متزامن
# ======================================================================
class HelpBridge(QObject):
    """المحرك يستدعي ask() من حلقة asyncio (خيط آخر)؛ الواجهة تعرض نافذة وتعيد الجواب."""
    request = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self._answer: Optional[str] = None
        self._event = threading.Event()
        self._lock = threading.Lock()

    async def ask(self, req: Dict[str, Any]) -> Optional[str]:
        """تُستدعى من worker (asyncio في خيط العمل) - تنتظر إجابة الواجهة بمهلة."""
        timeout = int(req.get('timeout') or 120)
        with self._lock:
            self._answer = None
            self._event.clear()
            self.request.emit(req)
            loop = asyncio.get_running_loop()
            try:
                got = await loop.run_in_executor(None, self._event.wait, timeout)
            except Exception:
                got = False
            return self._answer if got else None

    @pyqtSlot(object)
    def deliver(self, answer: Optional[str]):
        self._answer = answer
        self._event.set()


# ======================================================================
# خيط المحرك
# ======================================================================
class EngineThread(QThread):
    """يشغّل WorkerEngine.run_once داخل حلقة asyncio خاصة به."""
    progress = pyqtSignal(dict)
    finished_run = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, sessions: List[Dict[str, Any]], task: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.sessions = sessions
        self.task = task
        self.engine = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_requested = False

    def run(self):
        try:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            result = self.loop.run_until_complete(self._main())
            self.finished_run.emit(result or {})
        except Exception as e:
            self.failed.emit(f"{type(e).__name__}: {e}")
        finally:
            try:
                if self.loop:
                    pending = asyncio.all_tasks(self.loop)
                    for t in pending:
                        t.cancel()
                    if pending:
                        self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    self.loop.close()
            except Exception:
                pass

    async def _main(self):
        worker.reset_runtime_tables()
        worker.supabase.table('tasks_queue').insert(dict(self.task)).execute()
        self.engine = worker.WorkerEngine()
        if self._stop_requested:
            return {'completed': 0, 'failed': 0, 'cycles': 0, 'sessions_used': 0}
        return await self.engine.run_once(self.sessions, progress_cb=self.progress.emit)

    def request_stop(self):
        self._stop_requested = True
        if self.engine and self.loop and self.loop.is_running():
            def _do_stop():
                try:
                    self.engine.is_running = False
                    # إلغاء كل المهام الجارية داخل الحلقة (إيقاف فوري وآمن)
                    for t in asyncio.all_tasks(self.loop):
                        if t is not asyncio.current_task(self.loop):
                            t.cancel()
                except Exception:
                    pass
            self.loop.call_soon_threadsafe(_do_stop)


# ======================================================================
# نافذة المساعدة (سؤال الذكاء الاصطناعي)
# ======================================================================
class HelpDialog(QDialog):
    """نافذة عربية: سؤال + خيارات مرقّمة + حقل إجابة + زر إرسال."""

    def __init__(self, title: str, question: str, options: List[str], context_lines: List[str] = None,
                 bot_message: str = '', default: Optional[str] = None, timeout: int = 0,
                 allow_custom: bool = True, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(560)
        self.answer: Optional[str] = None
        self._timeout = timeout
        self._remaining = timeout

        root = QVBoxLayout(self)
        root.setSpacing(10)

        head = QLabel(question)
        head.setWordWrap(True)
        head.setObjectName('planTitle')
        root.addWidget(head)

        if bot_message:
            frame = QFrame()
            frame.setObjectName('botMsg')
            fl = QVBoxLayout(frame)
            lbl = QLabel("📨 رسالة البوت:")
            lbl.setStyleSheet("font-weight: bold;")
            fl.addWidget(lbl)
            msg = QPlainTextEdit(bot_message)
            msg.setReadOnly(True)
            msg.setMaximumHeight(140)
            fl.addWidget(msg)
            root.addWidget(frame)

        if context_lines:
            ctx = QLabel("\n".join(context_lines))
            ctx.setWordWrap(True)
            ctx.setObjectName('hint')
            root.addWidget(ctx)

        self.group = QButtonGroup(self)
        if options:
            box = QGroupBox("الخيارات المقترحة")
            bl = QVBoxLayout(box)
            for i, opt in enumerate(options, 1):
                rb = QRadioButton(f"{i}. {opt}")
                self.group.addButton(rb, i)
                bl.addWidget(rb)
                if default and str(default) == str(i):
                    rb.setChecked(True)
            root.addWidget(box)

        form = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("اكتب رقم الخيار أو نصاً مخصصاً (مثال: 1 أو اضغط تحقق أو تم)")
        self.input.setEnabled(allow_custom or bool(options))
        self.input.returnPressed.connect(self._send)
        form.addWidget(QLabel("إجابتك:"))
        form.addWidget(self.input, 1)
        root.addLayout(form)

        hint = QLabel("💡 كلمات خاصة: «تم» = اعتبر المهمة مكتملة | «تخطي» = دع الذكاء الاصطناعي يقرر | «إيقاف» = أوقف هذه المهمة")
        hint.setObjectName('hint')
        hint.setWordWrap(True)
        root.addWidget(hint)

        btns = QHBoxLayout()
        self.send_btn = QPushButton("📤 إرسال")
        self.send_btn.setObjectName('runBtn')
        self.send_btn.clicked.connect(self._send)
        self.skip_btn = QPushButton("⏭ تخطي (تلقائي)")
        self.skip_btn.clicked.connect(self._skip)
        self.timer_lbl = QLabel("")
        self.timer_lbl.setObjectName('hint')
        btns.addWidget(self.send_btn)
        btns.addWidget(self.skip_btn)
        btns.addStretch(1)
        btns.addWidget(self.timer_lbl)
        root.addLayout(btns)

        if timeout > 0:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(1000)
            self._tick()

        self.input.setFocus()

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self.timer_lbl.setText("⏰ انتهت المهلة - متابعة تلقائية")
            self._skip()
            return
        self.timer_lbl.setText(f"⏳ المتابعة التلقائية بعد {self._remaining} ث")

    def _send(self):
        text = self.input.text().strip()
        if not text and self.group.checkedId() > 0:
            text = str(self.group.checkedId())
        if not text:
            QMessageBox.warning(self, "تنبيه", "اختر خياراً أو اكتب إجابة أولاً.")
            return
        self.answer = text
        self.accept()

    def _skip(self):
        self.answer = None
        self.reject()


# ======================================================================
# النافذة الرئيسية
# ======================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(make_app_icon())
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1280, 820)

        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.theme = self.settings.value('theme', 'dark')
        self.sessions_root = Path(self.settings.value('sessions_root', str(BASE_DIR / 'sessions')))
        self.loaded_sessions: List[Dict[str, Any]] = []
        self.engine_thread: Optional[EngineThread] = None
        self.planner = TaskPlanner() if TaskPlanner else None
        self.current_plan: Optional[Plan] = None
        self.run_started_at: Optional[datetime] = None
        self._stats = {'done': 0, 'failed': 0}

        self._build_ui()
        self._build_toolbar()
        self._build_statusbar()
        self._apply_theme(self.theme)
        self._install_logging()
        self._restore_settings()
        self.refresh_folders()

        if IMPORT_ERROR:
            self.log('error', "❌ تعذر تحميل وحدات المشروع (worker/ai_agent):")
            for line in IMPORT_ERROR.strip().splitlines():
                self.log('error', "   " + line)
            self.log('warning', "⚠️ تأكد من تثبيت المتطلبات: pip install -r requirements.txt")
        else:
            self.log('success', f"✅ تم تشغيل tgmultipanel v{APP_VERSION} - مدير جلسات Telethon")
            self.log('info', "ℹ️ اختر مجلد الجلسات، أدخل API_ID/API_HASH، اكتب المهمة ثم اضغط «تشغيل».")

    # ------------------------------------------------------------------
    # بناء الواجهة
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main = QVBoxLayout(central)
        main.setContentsMargins(10, 8, 10, 6)
        main.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        main.addWidget(splitter, 1)

        # ===== اليمين (في RTL يظهر أولاً): الإعدادات + الجلسات =====
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)

        api_box = QGroupBox("🔑 بيانات Telegram API")
        api_form = QGridLayout(api_box)
        api_form.setHorizontalSpacing(8)
        self.api_id_edit = QLineEdit()
        self.api_id_edit.setPlaceholderText("مثال: 1234567")
        self.api_hash_edit = QLineEdit()
        self.api_hash_edit.setPlaceholderText("مثال: 0123456789abcdef0123456789abcdef")
        self.api_hash_edit.setEchoMode(QLineEdit.Password)
        self.show_hash_chk = QCheckBox("إظهار")
        self.show_hash_chk.toggled.connect(
            lambda on: self.api_hash_edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        api_form.addWidget(QLabel("API_ID:"), 0, 0)
        api_form.addWidget(self.api_id_edit, 0, 1, 1, 2)
        api_form.addWidget(QLabel("API_HASH:"), 1, 0)
        api_form.addWidget(self.api_hash_edit, 1, 1)
        api_form.addWidget(self.show_hash_chk, 1, 2)
        hint = QLabel("تحصل عليهما من my.telegram.org ← API development tools. تُحفظ محلياً على هذا الجهاز.")
        hint.setObjectName('hint')
        hint.setWordWrap(True)
        api_form.addWidget(hint, 2, 0, 1, 3)
        rl.addWidget(api_box)

        sess_box = QGroupBox("📁 الجلسات (sessions/)")
        sl = QVBoxLayout(sess_box)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("المجلد:"))
        self.folder_combo = QComboBox()
        self.folder_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.folder_combo.currentIndexChanged.connect(self.load_selected_folder)
        folder_row.addWidget(self.folder_combo, 1)
        self.refresh_btn = QPushButton("🔄 تحديث")
        self.refresh_btn.setToolTip("إعادة قراءة المجلدات وملفات الجلسات")
        self.refresh_btn.clicked.connect(self.refresh_folders)
        folder_row.addWidget(self.refresh_btn)
        self.browse_btn = QPushButton("📂 مجلد آخر…")
        self.browse_btn.setToolTip("اختيار مجلد جلسات من مكان آخر")
        self.browse_btn.clicked.connect(self.browse_sessions_root)
        folder_row.addWidget(self.browse_btn)
        sl.addLayout(folder_row)

        self.sessions_table = QTableWidget(0, 5)
        self.sessions_table.setHorizontalHeaderLabels(["✔", "الرقم / الملف", "الحالة", "DC", "API"])
        self.sessions_table.setLayoutDirection(Qt.RightToLeft)
        self.sessions_table.verticalHeader().setVisible(False)
        self.sessions_table.setAlternatingRowColors(True)
        self.sessions_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.sessions_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.sessions_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.sessions_table.itemChanged.connect(self._on_session_item_changed)
        self.sessions_table.setMinimumHeight(220)
        sl.addWidget(self.sessions_table, 1)

        sel_row = QHBoxLayout()
        self.select_all_chk = QCheckBox("تحديد الكل")
        self.select_all_chk.stateChanged.connect(self._toggle_select_all)
        sel_row.addWidget(self.select_all_chk)
        self.select_valid_btn = QPushButton("✅ الصالحة فقط")
        self.select_valid_btn.setToolTip("تحديد الجلسات التي تحتوي مفتاح تسجيل دخول صالحاً")
        self.select_valid_btn.clicked.connect(self._select_valid_only)
        sel_row.addWidget(self.select_valid_btn)
        sel_row.addStretch(1)
        self.sessions_count_lbl = QLabel("0 جلسة")
        self.sessions_count_lbl.setObjectName('hint')
        sel_row.addWidget(self.sessions_count_lbl)
        sl.addLayout(sel_row)
        rl.addWidget(sess_box, 1)

        splitter.addWidget(right)

        # ===== اليسار: المهمة + السجل =====
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)

        task_box = QGroupBox("📝 المهمة")
        tl = QVBoxLayout(task_box)
        self.task_edit = QPlainTextEdit()
        self.task_edit.setPlaceholderText(
            "اكتب المهمة هنا (سطر أو عدة أسطر). أمثلة:\n"
            "https://t.me/SomeBot?start=REF123           ← رابط إحالة (مهمة ذكية)\n"
            "اشترك @channel_name                          ← اشتراك في قناة\n"
            "https://t.me/SomeBot?start=REF\nsubscribe\ncheck\nmath   ← خطوات يدوية\n"
            "https://t.me/channel/123 تفاعل 🔥            ← تفاعل على منشور"
        )
        self.task_edit.setMinimumHeight(110)
        self.task_edit.setMaximumHeight(170)
        tl.addWidget(self.task_edit)

        opts = QHBoxLayout()
        opts.addWidget(QLabel("عدد الحسابات:"))
        self.accounts_spin = QSpinBox()
        self.accounts_spin.setRange(1, 1000)
        self.accounts_spin.setValue(1)
        self.accounts_spin.setToolTip("عدد الحسابات التي ستنفذ المهمة (من الجلسات المحددة)")
        opts.addWidget(self.accounts_spin)
        opts.addSpacing(12)
        opts.addWidget(QLabel("السرعة:"))
        self.speed_combo = QComboBox()
        for key, label in (('slow', 'بطيئة (أكثر أماناً)'), ('medium', 'متوسطة'), ('fast', 'سريعة')):
            self.speed_combo.addItem(label, key)
        self.speed_combo.setCurrentIndex(1)
        opts.addWidget(self.speed_combo)
        opts.addSpacing(12)
        opts.addWidget(QLabel("التأخير بين الحسابات (ث):"))
        self.delay_min_spin = QSpinBox()
        self.delay_min_spin.setRange(0, 3600)
        self.delay_min_spin.setValue(30)
        self.delay_max_spin = QSpinBox()
        self.delay_max_spin.setRange(0, 7200)
        self.delay_max_spin.setValue(300)
        opts.addWidget(self.delay_min_spin)
        opts.addWidget(QLabel("إلى"))
        opts.addWidget(self.delay_max_spin)
        opts.addStretch(1)
        tl.addLayout(opts)

        modes = QHBoxLayout()
        self.ai_mode_rb = QRadioButton("🧠 تحليل بالذكاء الاصطناعي (موصى به)")
        self.ai_mode_rb.setChecked(True)
        self.direct_mode_rb = QRadioButton("⚡ تنفيذ مباشر (إرسال للمحرك بدون تحليل)")
        modes.addWidget(self.ai_mode_rb)
        modes.addWidget(self.direct_mode_rb)
        modes.addStretch(1)
        self.help_chk = QCheckBox("🙋 اسألني عند الحاجة أثناء التنفيذ")
        self.help_chk.setChecked(True)
        self.help_chk.setToolTip("عند انخفاض ثقة الذكاء الاصطناعي أو التعثر تظهر نافذة تسألك ماذا تفعل. "
                                 "إن لم تجب خلال المهلة يكمل تلقائياً.")
        modes.addWidget(self.help_chk)
        modes.addWidget(QLabel("المهلة:"))
        self.help_timeout_spin = QSpinBox()
        self.help_timeout_spin.setRange(10, 900)
        self.help_timeout_spin.setValue(120)
        self.help_timeout_spin.setSuffix(" ث")
        modes.addWidget(self.help_timeout_spin)
        tl.addLayout(modes)

        btns = QHBoxLayout()
        self.run_btn = QPushButton("▶ تشغيل")
        self.run_btn.setObjectName('runBtn')
        self.run_btn.setMinimumHeight(38)
        self.run_btn.clicked.connect(self.on_run)
        self.stop_btn = QPushButton("⏹ إيقاف")
        self.stop_btn.setObjectName('stopBtn')
        self.stop_btn.setMinimumHeight(38)
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.on_stop)
        self.clear_btn = QPushButton("🧹 مسح السجل")
        self.clear_btn.setObjectName('clearBtn')
        self.clear_btn.setMinimumHeight(38)
        self.clear_btn.clicked.connect(self.clear_log)
        self.analyze_btn = QPushButton("🔍 تحليل فقط")
        self.analyze_btn.setMinimumHeight(38)
        self.analyze_btn.setToolTip("عرض ما فهمه الذكاء الاصطناعي وخطته دون تنفيذ")
        self.analyze_btn.clicked.connect(self.on_analyze_only)
        btns.addWidget(self.run_btn, 2)
        btns.addWidget(self.stop_btn, 1)
        btns.addWidget(self.analyze_btn, 1)
        btns.addWidget(self.clear_btn, 1)
        tl.addLayout(btns)
        ll.addWidget(task_box)

        log_box = QGroupBox("📜 السجل")
        lgl = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setLayoutDirection(Qt.LeftToRight)
        self.log_view.setLineWrapMode(QTextEdit.WidgetWidth)
        mono = QFont("Consolas" if sys.platform.startswith('win') else "DejaVu Sans Mono")
        mono.setPointSize(10)
        self.log_view.setFont(mono)
        lgl.addWidget(self.log_view, 1)
        log_opts = QHBoxLayout()
        self.autoscroll_chk = QCheckBox("تمرير تلقائي")
        self.autoscroll_chk.setChecked(True)
        self.verbose_chk = QCheckBox("عرض تفاصيل الشبكة (telethon)")
        self.verbose_chk.setChecked(False)
        self.verbose_chk.toggled.connect(self._toggle_verbose)
        log_opts.addWidget(self.autoscroll_chk)
        log_opts.addWidget(self.verbose_chk)
        log_opts.addStretch(1)
        self.save_log_btn = QPushButton("💾 حفظ السجل")
        self.save_log_btn.clicked.connect(self.save_log)
        log_opts.addWidget(self.save_log_btn)
        lgl.addLayout(log_opts)
        ll.addWidget(log_box, 1)

        splitter.addWidget(left)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([480, 800])

    def _build_toolbar(self):
        tb = QToolBar("الأدوات")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(tb)

        self.theme_action = QAction("🌙 الوضع الداكن" if self.theme == 'light' else "☀️ الوضع الفاتح", self)
        self.theme_action.triggered.connect(self.toggle_theme)
        tb.addAction(self.theme_action)
        tb.addSeparator()

        open_sessions = QAction("📂 فتح مجلد الجلسات", self)
        open_sessions.triggered.connect(lambda: self._open_path(self.sessions_root))
        tb.addAction(open_sessions)

        open_logs = QAction("🗒 فتح مجلد السجلات", self)
        open_logs.triggered.connect(lambda: self._open_path(BASE_DIR / 'logs'))
        tb.addAction(open_logs)
        tb.addSeparator()

        clear_templates = QAction("🧠 مسح القوالب المتعلَّمة", self)
        clear_templates.setToolTip("حذف الأنماط التي تعلمها الذكاء الاصطناعي عن البوتات (data/bot_templates.json)")
        clear_templates.triggered.connect(self.clear_templates)
        tb.addAction(clear_templates)
        tb.addSeparator()

        help_action = QAction("❓ مساعدة", self)
        help_action.triggered.connect(self.show_help)
        tb.addAction(help_action)
        about_action = QAction("ℹ️ حول", self)
        about_action.triggered.connect(self.show_about)
        tb.addAction(about_action)

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_lbl = QLabel("جاهز")
        self.stats_lbl = QLabel("✅ 0 | ❌ 0")
        self.sessions_lbl = QLabel("الجلسات المحددة: 0")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(220)
        self.progress.setVisible(False)
        self.progress.setRange(0, 0)
        sb.addWidget(self.status_lbl, 1)
        sb.addPermanentWidget(self.progress)
        sb.addPermanentWidget(self.sessions_lbl)
        sb.addPermanentWidget(self.stats_lbl)
        self.elapsed_lbl = QLabel("")
        sb.addPermanentWidget(self.elapsed_lbl)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

    # ------------------------------------------------------------------
    # السمة
    # ------------------------------------------------------------------
    def _apply_theme(self, theme: str):
        self.theme = theme if theme in ('dark', 'light') else 'dark'
        QApplication.instance().setStyleSheet(DARK_QSS if self.theme == 'dark' else LIGHT_QSS)
        if hasattr(self, 'theme_action'):
            self.theme_action.setText("☀️ الوضع الفاتح" if self.theme == 'dark' else "🌙 الوضع الداكن")
        self.settings.setValue('theme', self.theme)

    def toggle_theme(self):
        self._apply_theme('light' if self.theme == 'dark' else 'dark')
        self.log('info', f"🎨 تم التبديل إلى {'الوضع الفاتح' if self.theme == 'light' else 'الوضع الداكن'}")

    # ------------------------------------------------------------------
    # السجل
    # ------------------------------------------------------------------
    def _install_logging(self):
        self.log_bridge = QtLogBridge()
        self.log_bridge.setFormatter(logging.Formatter('%(name)s - %(message)s'))
        self.log_bridge.record.connect(self._on_worker_log)
        root = logging.getLogger()
        root.addHandler(self.log_bridge)
        if root.level > logging.INFO or root.level == logging.NOTSET:
            root.setLevel(logging.INFO)
        self._toggle_verbose(False)

    def _toggle_verbose(self, on: bool):
        level = logging.INFO if on else logging.WARNING
        for name in ('telethon', 'telethon.network', 'telethon.network.mtprotosender',
                     'telethon.network.mtprotostate', 'telethon.client', 'asyncio'):
            logging.getLogger(name).setLevel(level)

    @pyqtSlot(str, str)
    def _on_worker_log(self, kind: str, msg: str):
        # إخفاء ضجيج telethon إلا إذا طُلب
        if not self.verbose_chk.isChecked() and msg.startswith('telethon'):
            return
        # اختصار أسماء اللوجر
        for prefix, label in (('WorkerEngine - ', ''), ('AIAgent - ', '🧠 '), ('root - ', '')):
            if msg.startswith(prefix):
                msg = label + msg[len(prefix):]
                break
        self.log(kind, msg)

    def log(self, kind: str, text: str):
        colors = LOG_COLORS['dark' if self.theme == 'dark' else 'light']
        icon = {'success': '✅ ', 'error': '❌ ', 'warning': '⚠️ '}.get(kind, '')
        # لا نكرر الأيقونة إن كانت موجودة بالنص
        if text.lstrip()[:1] in ('✅', '❌', '⚠', '🧠', '📌', '🎯', '📝', '🤖', '📢', '🔗', '🔒', '📋', '➕',
                                  '✍', '🖱', '⏭', '😊', '🎲', '🗳', '━', '1', '2', '3', '4', '5', '6', '7', '8', '9',
                                  '👥', 'ℹ', '⏱', '🔑', '📁', '🎨', '💾', '🧹', '▶', '⏹', '🙋', '🔍', '❓', '📨',
                                  '🗒', '📂', '⏰', '💡', '🌐', '🔢', '📱'):
            icon = ''
        ts = datetime.now().strftime('%H:%M:%S')
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.End)

        fmt_time = QTextCharFormat()
        fmt_time.setForeground(QColor(colors['time']))
        cursor.insertText(f"[{ts}] ", fmt_time)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(colors.get(kind, colors['info'])))
        if kind in ('success', 'error'):
            fmt.setFontWeight(QFont.Bold)
        cursor.insertText(f"{icon}{text}\n", fmt)

        if self.autoscroll_chk.isChecked():
            self.log_view.setTextCursor(cursor)
            self.log_view.ensureCursorVisible()

        # حد أقصى للأسطر حتى لا تثقل الواجهة
        doc = self.log_view.document()
        if doc.blockCount() > 5000:
            c = QTextCursor(doc)
            c.movePosition(QTextCursor.Start)
            c.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, 1000)
            c.removeSelectedText()

    def clear_log(self):
        self.log_view.clear()
        self.log('info', "🧹 تم مسح السجل.")

    def save_log(self):
        logs_dir = BASE_DIR / 'logs'
        logs_dir.mkdir(exist_ok=True)
        default = logs_dir / f"gui_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "حفظ السجل", str(default), "ملف نصي (*.txt)")
        if not path:
            return
        try:
            Path(path).write_text(self.log_view.toPlainText(), encoding='utf-8')
            self.log('success', f"✅ تم حفظ السجل في: {path}")
        except Exception as e:
            self._error("تعذر حفظ السجل", str(e))

    # ------------------------------------------------------------------
    # الإعدادات
    # ------------------------------------------------------------------
    def _restore_settings(self):
        self.api_id_edit.setText(str(self.settings.value('api_id', '')))
        self.api_hash_edit.setText(str(self.settings.value('api_hash', '')))
        self.accounts_spin.setValue(int(self.settings.value('accounts', 1)))
        speed = str(self.settings.value('speed', 'medium'))
        idx = self.speed_combo.findData(speed)
        if idx >= 0:
            self.speed_combo.setCurrentIndex(idx)
        self.delay_min_spin.setValue(int(self.settings.value('delay_min', 30)))
        self.delay_max_spin.setValue(int(self.settings.value('delay_max', 300)))
        self.help_chk.setChecked(self.settings.value('help_enabled', 'true') in ('true', True, 'True', 1))
        self.help_timeout_spin.setValue(int(self.settings.value('help_timeout', 120)))
        self.task_edit.setPlainText(str(self.settings.value('last_task', '')))
        if self.settings.value('direct_mode', 'false') in ('true', True, 'True', 1):
            self.direct_mode_rb.setChecked(True)
        geo = self.settings.value('geometry')
        if geo:
            self.restoreGeometry(geo)

    def _save_settings(self):
        self.settings.setValue('api_id', self.api_id_edit.text().strip())
        self.settings.setValue('api_hash', self.api_hash_edit.text().strip())
        self.settings.setValue('accounts', self.accounts_spin.value())
        self.settings.setValue('speed', self.speed_combo.currentData())
        self.settings.setValue('delay_min', self.delay_min_spin.value())
        self.settings.setValue('delay_max', self.delay_max_spin.value())
        self.settings.setValue('help_enabled', 'true' if self.help_chk.isChecked() else 'false')
        self.settings.setValue('help_timeout', self.help_timeout_spin.value())
        self.settings.setValue('last_task', self.task_edit.toPlainText())
        self.settings.setValue('direct_mode', 'true' if self.direct_mode_rb.isChecked() else 'false')
        self.settings.setValue('sessions_root', str(self.sessions_root))
        self.settings.setValue('last_folder', self.folder_combo.currentData() or '')
        self.settings.setValue('geometry', self.saveGeometry())

    def closeEvent(self, event):
        if self.engine_thread and self.engine_thread.isRunning():
            r = QMessageBox.question(self, "تأكيد الخروج",
                                     "المحرك ما زال يعمل. هل تريد إيقافه والخروج؟",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                event.ignore()
                return
            self.engine_thread.request_stop()
            self.engine_thread.wait(8000)
        self._save_settings()
        event.accept()

    # ------------------------------------------------------------------
    # الجلسات
    # ------------------------------------------------------------------
    def browse_sessions_root(self):
        path = QFileDialog.getExistingDirectory(self, "اختر مجلد الجلسات", str(self.sessions_root))
        if path:
            self.sessions_root = Path(path)
            self.settings.setValue('sessions_root', path)
            self.refresh_folders()

    def refresh_folders(self):
        if worker is None:
            return
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        folders = worker.list_session_folders(self.sessions_root)
        current = self.folder_combo.currentData() or self.settings.value('last_folder', '')
        self.folder_combo.blockSignals(True)
        self.folder_combo.clear()
        if not folders:
            # أعرض المجلدات الفرعية حتى لو كانت فارغة ليعرف المستخدم أين يضع الملفات
            subdirs = [p for p in sorted(self.sessions_root.iterdir()) if p.is_dir()] if self.sessions_root.exists() else []
            for p in subdirs:
                self.folder_combo.addItem(f"{p.name}  (فارغ)", str(p))
            if not subdirs:
                self.folder_combo.addItem("(لا توجد مجلدات - ضع ملفات .session داخل sessions/)", str(self.sessions_root))
        else:
            for f in folders:
                try:
                    rel = f.relative_to(self.sessions_root)
                    label = str(rel) if str(rel) != '.' else "(المجلد الرئيسي sessions/)"
                except ValueError:
                    label = str(f)
                count = sum(1 for p in f.glob('*.session'))
                self.folder_combo.addItem(f"{label}  —  {count} جلسة", str(f))
        # استعادة الاختيار السابق
        idx = self.folder_combo.findData(current) if current else -1
        self.folder_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.folder_combo.blockSignals(False)
        self.load_selected_folder()
        self.log('info', f"📁 مجلد الجلسات: {self.sessions_root}  ({len(folders)} مجلد يحتوي جلسات)")

    def load_selected_folder(self):
        if worker is None:
            return
        folder = self.folder_combo.currentData()
        self.sessions_table.blockSignals(True)
        self.sessions_table.setRowCount(0)
        self.loaded_sessions = []
        if folder:
            try:
                api_id = int(self.api_id_edit.text().strip()) if self.api_id_edit.text().strip().isdigit() else None
                api_hash = self.api_hash_edit.text().strip() or None
                self.loaded_sessions = worker.load_sessions_from_folder(Path(folder), api_id, api_hash)
            except Exception as e:
                self._error("تعذر قراءة المجلد", str(e))
        for row, s in enumerate(self.loaded_sessions):
            self.sessions_table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if s.get('valid') else Qt.Unchecked)
            self.sessions_table.setItem(row, 0, chk)
            name = s.get('phone') or s.get('file_name')
            if s.get('name'):
                name = f"{name}  ({s['name']})"
            item = QTableWidgetItem(name)
            item.setToolTip(s.get('session_file', ''))
            self.sessions_table.setItem(row, 1, item)
            if s.get('valid'):
                st = QTableWidgetItem("✅ صالحة")
                st.setForeground(QColor('#2ea55a'))
            else:
                st = QTableWidgetItem("❌ " + self._translate_check_error(s.get('check_error')))
                st.setForeground(QColor('#e05252'))
            self.sessions_table.setItem(row, 2, st)
            self.sessions_table.setItem(row, 3, QTableWidgetItem(str(s.get('dc_id') or '-')))
            api_src = "خاص (json)" if (Path(s['session_file']).with_suffix('.json').exists() and s.get('api_id')) else "عام"
            self.sessions_table.setItem(row, 4, QTableWidgetItem(api_src))
        self.sessions_table.blockSignals(False)
        valid = sum(1 for s in self.loaded_sessions if s.get('valid'))
        self.sessions_count_lbl.setText(f"{len(self.loaded_sessions)} جلسة ({valid} صالحة)")
        self.select_all_chk.blockSignals(True)
        self.select_all_chk.setChecked(bool(self.loaded_sessions) and valid == len(self.loaded_sessions))
        self.select_all_chk.blockSignals(False)
        self._update_selected_count()
        if folder and self.loaded_sessions:
            self.log('info', f"📁 تم تحميل {len(self.loaded_sessions)} جلسة من «{Path(folder).name}» ({valid} صالحة)")

    @staticmethod
    def _translate_check_error(err: Optional[str]) -> str:
        if not err:
            return "غير صالحة"
        low = err.lower()
        if 'no auth key' in low:
            return "غير مسجَّلة دخول"
        if 'not a telethon' in low:
            return "ليست جلسة Telethon"
        if 'locked' in low:
            return "الملف مقفول (مستخدم ببرنامج آخر)"
        if 'empty' in low:
            return "جلسة فارغة"
        return err[:40]

    def _on_session_item_changed(self, item: QTableWidgetItem):
        if item.column() == 0:
            self._update_selected_count()

    def _toggle_select_all(self, state):
        self.sessions_table.blockSignals(True)
        for r in range(self.sessions_table.rowCount()):
            self.sessions_table.item(r, 0).setCheckState(Qt.Checked if state == Qt.Checked else Qt.Unchecked)
        self.sessions_table.blockSignals(False)
        self._update_selected_count()

    def _select_valid_only(self):
        self.sessions_table.blockSignals(True)
        for r, s in enumerate(self.loaded_sessions):
            self.sessions_table.item(r, 0).setCheckState(Qt.Checked if s.get('valid') else Qt.Unchecked)
        self.sessions_table.blockSignals(False)
        self._update_selected_count()

    def selected_sessions(self) -> List[Dict[str, Any]]:
        out = []
        for r, s in enumerate(self.loaded_sessions):
            item = self.sessions_table.item(r, 0)
            if item and item.checkState() == Qt.Checked:
                out.append(s)
        return out

    def _update_selected_count(self):
        n = len(self.selected_sessions())
        self.sessions_lbl.setText(f"الجلسات المحددة: {n}")
        if n and self.accounts_spin.value() > n:
            self.accounts_spin.setValue(n)

    # ------------------------------------------------------------------
    # التحقق من المدخلات
    # ------------------------------------------------------------------
    def _validate_inputs(self) -> bool:
        if worker is None:
            self._error("خطأ في التحميل", "وحدات المشروع غير محمّلة. راجع السجل وثبّت المتطلبات.")
            return False
        api_id = self.api_id_edit.text().strip()
        api_hash = self.api_hash_edit.text().strip()
        if not api_id.isdigit():
            self._error("بيانات API ناقصة", "أدخل API_ID كرقم صحيح (من my.telegram.org).")
            self.api_id_edit.setFocus()
            return False
        if len(api_hash) < 16:
            self._error("بيانات API ناقصة", "أدخل API_HASH صحيحاً (32 حرفاً عادةً).")
            self.api_hash_edit.setFocus()
            return False
        if not self.task_edit.toPlainText().strip():
            self._error("المهمة فارغة", "اكتب المهمة أولاً (رابط بوت، @قناة، أو خطوات).")
            self.task_edit.setFocus()
            return False
        sel = self.selected_sessions()
        if not sel:
            self._error("لا توجد جلسات محددة", "حدّد جلسة واحدة على الأقل من الجدول (أو «تحديد الكل»).")
            return False
        invalid = [s for s in sel if not s.get('valid')]
        if invalid:
            r = QMessageBox.question(
                self, "جلسات غير صالحة",
                f"{len(invalid)} من الجلسات المحددة تبدو غير مسجَّلة دخول.\nهل تريد المتابعة بالجلسات الصالحة فقط؟",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if r != QMessageBox.Yes:
                return False
            if not any(s.get('valid') for s in sel):
                self._error("لا توجد جلسات صالحة", "كل الجلسات المحددة غير صالحة.")
                return False
        if self.delay_max_spin.value() < self.delay_min_spin.value():
            self.delay_max_spin.setValue(self.delay_min_spin.value())
        return True

    # ------------------------------------------------------------------
    # التحليل والتخطيط
    # ------------------------------------------------------------------
    def _plan_with_questions(self, text: str, accounts: int, speed: str) -> Optional[Plan]:
        """تحليل المهمة؛ عند وجود أسئلة تُعرض نوافذ منبثقة حتى تكتمل الخطة."""
        if not self.planner:
            return None
        answers: Dict[str, str] = {}
        plan = self.planner.plan(text, answers=answers, accounts=accounts, speed=speed)
        rounds = 0
        while plan.questions and rounds < 8:
            rounds += 1
            q = plan.questions[0]
            self.log('ai', f"🙋 الذكاء الاصطناعي يحتاج توضيحاً: {q.text.splitlines()[0]}")
            dlg = HelpDialog("🤖 الذكاء الاصطناعي يحتاج مساعدتك", q.text, q.options,
                             context_lines=["اختر رقم الخيار أو اكتب إجابتك ثم اضغط إرسال."],
                             default=q.default, allow_custom=q.allow_custom, parent=self)
            if dlg.exec_() == QDialog.Accepted and dlg.answer:
                answers[q.id] = dlg.answer
                self.log('info', f"   ↳ إجابتك: {dlg.answer}")
            else:
                if q.id in ('no_target', 'empty', 'forward_target'):
                    self.log('warning', "⚠️ تم إلغاء التخطيط - لا يمكن المتابعة بدون هدف.")
                    return None
                answers[q.id] = q.default or '1'
                self.log('info', f"   ↳ تم اعتماد الخيار الافتراضي ({answers[q.id]})")
            plan = self.planner.plan(text, answers=answers, accounts=accounts, speed=speed)
        return plan

    def _print_plan(self, plan: Plan):
        self.log('ai', "🧠 ━━━━━━━━━ تحليل الذكاء الاصطناعي للمهمة ━━━━━━━━━")
        for line in plan.reasoning:
            self.log('ai', line)
        for w in plan.warnings:
            self.log('warning', w)
        if plan.mode == 'smart' and self.planner:
            for line in self.planner.explain_ai_behaviour():
                self.log('ai', line)

    def on_analyze_only(self):
        if worker is None or not self.planner:
            self._error("غير متاح", "وحدة التحليل غير محمّلة.")
            return
        text = self.task_edit.toPlainText().strip()
        if not text:
            self._error("المهمة فارغة", "اكتب المهمة أولاً.")
            return
        plan = self._plan_with_questions(text, self.accounts_spin.value(), self.speed_combo.currentData())
        if plan:
            self._print_plan(plan)
            self.current_plan = plan
            self.status_lbl.setText("تم التحليل - اضغط «تشغيل» للتنفيذ")

    # ------------------------------------------------------------------
    # التشغيل / الإيقاف
    # ------------------------------------------------------------------
    def on_run(self):
        if self.engine_thread and self.engine_thread.isRunning():
            self._error("قيد التشغيل", "المحرك يعمل حالياً. أوقفه أولاً.")
            return
        if not self._validate_inputs():
            return
        self._save_settings()

        text = self.task_edit.toPlainText().strip()
        speed = self.speed_combo.currentData()
        sel = [s for s in self.selected_sessions() if s.get('valid')]
        accounts = min(self.accounts_spin.value(), len(sel))
        sessions = sel[:accounts]

        # ضبط المحرك
        try:
            worker.configure(int(self.api_id_edit.text().strip()), self.api_hash_edit.text().strip(),
                             delay_between_accounts=(self.delay_min_spin.value(), self.delay_max_spin.value()))
        except Exception as e:
            self._error("إعدادات غير صالحة", str(e))
            return
        # تحديث api للجلسات التي لا تملك ملف json خاص
        for s in sessions:
            if not Path(s['session_file']).with_suffix('.json').exists():
                s['api_id'] = worker.API_ID
                s['api_hash'] = worker.API_HASH

        # بناء المهمة
        if self.direct_mode_rb.isChecked():
            task = self._direct_task(text, accounts, speed)
            self.log('warning', "⚡ وضع التنفيذ المباشر: سيتم إرسال المهمة للمحرك دون تحليل مسبق.")
            self.log('info', f"📌 الهدف: {task['target_bot_link']} | النوع: {task['task_type']} | الحسابات: {accounts}")
        else:
            plan = self._plan_with_questions(text, accounts, speed)
            if plan is None:
                self.status_lbl.setText("تم إلغاء التشغيل")
                return
            self._print_plan(plan)
            self.current_plan = plan
            task = dict(plan.task)
            task['required_accounts'] = accounts
            task['multi_account'] = accounts > 1

        # طلب المساعدة أثناء التنفيذ
        if self.help_chk.isChecked():
            self.help_bridge = HelpBridge()
            self.help_bridge.request.connect(self._on_help_request)
            worker.set_help_handler(self.help_bridge.ask, timeout=self.help_timeout_spin.value())
            self.log('info', f"🙋 المساعدة أثناء التنفيذ مفعّلة (مهلة {self.help_timeout_spin.value()} ث).")
        else:
            worker.set_help_handler(None)

        # تشغيل الخيط
        self.engine_thread = EngineThread(sessions, task, parent=self)
        self.engine_thread.progress.connect(self._on_progress)
        self.engine_thread.finished_run.connect(self._on_finished)
        self.engine_thread.failed.connect(self._on_failed)
        self._stats = {'done': 0, 'failed': 0}
        self.stats_lbl.setText("✅ 0 | ❌ 0")
        self.run_started_at = datetime.now()
        self._elapsed_timer.start(1000)
        self._set_running(True)
        self.log('success', f"▶ بدء التنفيذ على {accounts} حساب من «{self.folder_combo.currentText().split('  —')[0].strip()}»")
        self.engine_thread.start()

    def _direct_task(self, text: str, accounts: int, speed: str) -> Dict[str, Any]:
        """وضع التنفيذ المباشر: أول رابط/معرّف = الهدف، بقية الأسطر = خطوات يدوية (إن وُجدت)."""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        target = lines[0] if lines else 'unknown'
        steps_lines = lines[1:]
        steps: List[Dict[str, Any]] = []
        if self.planner:
            steps, _unknown = self.planner._parse_manual_steps(steps_lines)
        low = target.lower()
        if '/' in low.split('t.me/')[-1] and low.split('t.me/')[-1].split('/')[-1].isdigit():
            task_type = 'react_post'
        elif steps:
            task_type = 'manual'
        elif 't.me/' in low or low.endswith('bot') or '?start=' in low:
            task_type = 'composite'
        else:
            task_type = 'follow_channel'
        if task_type == 'follow_channel':
            target = target.replace('https://t.me/', '').lstrip('@')
        return {
            'target_bot_link': target,
            'target_message_link': target if task_type == 'react_post' else None,
            'task_type': task_type,
            'status': 'pending',
            'speed': speed,
            'composite_steps': json.dumps(steps, ensure_ascii=False) if steps else '[]',
            'emoji_target': '👍',
            'vote_option': '0',
            'channel_list': json.dumps([target] if task_type == 'follow_channel' else [], ensure_ascii=False),
            'required_accounts': accounts,
            'multi_account': accounts > 1,
            'parent_task_id': None,
        }

    def on_stop(self):
        if not (self.engine_thread and self.engine_thread.isRunning()):
            return
        self.log('warning', "⏹ جارٍ الإيقاف... (قد يستغرق ثوانٍ لإغلاق الاتصالات بأمان)")
        self.status_lbl.setText("جارٍ الإيقاف...")
        self.stop_btn.setEnabled(False)
        self.engine_thread.request_stop()

    def _set_running(self, running: bool):
        self.run_btn.setEnabled(not running)
        self.analyze_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.progress.setVisible(running)
        for w in (self.api_id_edit, self.api_hash_edit, self.folder_combo, self.refresh_btn,
                  self.browse_btn, self.task_edit, self.accounts_spin, self.speed_combo,
                  self.direct_mode_rb, self.ai_mode_rb):
            w.setEnabled(not running)
        self.status_lbl.setText("قيد التنفيذ..." if running else "جاهز")
        if not running:
            self._elapsed_timer.stop()

    def _update_elapsed(self):
        if self.run_started_at:
            delta = datetime.now() - self.run_started_at
            m, s = divmod(int(delta.total_seconds()), 60)
            self.elapsed_lbl.setText(f"⏱ {m:02d}:{s:02d}")

    # ------------------------------------------------------------------
    # إشارات المحرك
    # ------------------------------------------------------------------
    @pyqtSlot(dict)
    def _on_progress(self, info: Dict[str, Any]):
        ev = info.get('event')
        stats = info.get('stats') or {}
        self._stats['done'] = stats.get('tasks_completed', self._stats['done'])
        self._stats['failed'] = stats.get('tasks_failed', self._stats['failed'])
        self.stats_lbl.setText(f"✅ {self._stats['done']} | ❌ {self._stats['failed']}")
        if ev == 'session_start':
            self.status_lbl.setText(f"جارٍ العمل على الحساب {info.get('phone')}...")
        elif ev == 'session_done':
            d, f = info.get('done', 0), info.get('failed', 0)
            if d and not f:
                self.log('success', f"✅ الحساب {info.get('phone')}: اكتملت المهمة")
            elif f:
                self.log('warning', f"⚠️ الحساب {info.get('phone')}: {d} نجاح / {f} فشل")
        elif ev == 'cycle':
            self.status_lbl.setText(f"الدورة {info.get('cycle')}: {info.get('pending')} مهمة معلقة على {info.get('sessions')} جلسة")
        elif ev == 'session_skipped':
            self.log('error', f"❌ الحساب {info.get('phone')}: تعذّر الاتصال/تسجيل الدخول مرتين - تم استبعاده من هذه الدفعة.")
        elif ev == 'no_sessions':
            self.log('error', "❌ لم تبقَ جلسات نشطة (تم تعطيلها بسبب أخطاء/حظر).")

    @pyqtSlot(dict)
    def _on_finished(self, result: Dict[str, Any]):
        self._set_running(False)
        done = result.get('completed', 0)
        failed = result.get('failed', 0)
        self.stats_lbl.setText(f"✅ {done} | ❌ {failed}")
        if failed == 0 and done > 0:
            self.log('success', f"✅ انتهى التنفيذ بنجاح: {done} مهمة مكتملة.")
        elif done == 0 and failed == 0:
            self.log('warning', "⚠️ انتهى التنفيذ دون تنفيذ أي مهمة (تم الإيقاف أو لا توجد جلسات صالحة).")
        else:
            self.log('warning', f"⚠️ انتهى التنفيذ: {done} نجاح، {failed} فشل.")
        self.status_lbl.setText("اكتمل التنفيذ")
        worker.set_help_handler(None)
        self._summarize_results()

    @pyqtSlot(str)
    def _on_failed(self, err: str):
        self._set_running(False)
        self.log('error', f"❌ توقف المحرك بخطأ: {err}")
        self.status_lbl.setText("توقف بخطأ")
        worker.set_help_handler(None)
        self._error("خطأ أثناء التنفيذ", self._friendly_error(err))

    def _summarize_results(self):
        """ملخص عربي لكل حساب من جدول المهام المحلي."""
        try:
            rows = worker.supabase.rows('tasks_queue')
            sessions = {s['id']: s for s in worker.supabase.rows('client_sessions')}
            children = [r for r in rows if r.get('parent_task_id')]
            if not children:
                return
            self.log('info', "📋 ━━━━━━━━━ ملخص الحسابات ━━━━━━━━━")
            for c in children:
                phone = sessions.get(c.get('session_id'), {}).get('phone', '?')
                st = c.get('status')
                if st == 'completed':
                    self.log('success', f"✅ {phone}: مكتملة")
                elif st == 'failed':
                    self.log('error', f"❌ {phone}: فشلت ({self._friendly_error(c.get('error_message') or '')})")
                else:
                    self.log('warning', f"⚠️ {phone}: {st} (لم تكتمل)")
            deactivated = [s for s in sessions.values() if not s.get('is_active')]
            for s in deactivated:
                self.log('error', f"❌ الجلسة {s.get('phone')}: تم تعطيلها - {self._friendly_error(s.get('error_message') or '')}")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # نافذة المساعدة أثناء التنفيذ
    # ------------------------------------------------------------------
    @pyqtSlot(dict)
    def _on_help_request(self, req: Dict[str, Any]):
        buttons = req.get('buttons') or []
        options = []
        for b in buttons:
            t = b.get('text', '')
            typ = {'subscribe': 'اشتراك', 'verify': 'تحقق', 'share_phone': 'مشاركة رقم', 'url': 'رابط',
                   'language': 'لغة', 'math_answer': 'إجابة', 'unknown': ''}.get(b.get('type', ''), b.get('type', ''))
            options.append(f"{t}" + (f"  [{typ}]" if typ else ""))
        ctx = []
        if self.planner:
            ctx.extend(self.planner.explain_bot_message(req.get('message_text', ''), buttons))
        reason = req.get('reason') or ''
        if req.get('stalled'):
            ctx.append("🔁 السبب: البوت يكرر نفس الرسالة رغم تنفيذ الإجراء - قد يحتاج خطوة مختلفة.")
        elif reason:
            ctx.append(f"🤔 السبب: {reason}")
        self.log('warning', f"🙋 الذكاء الاصطناعي يطلب مساعدتك مع @{req.get('bot_username')} (الحساب {req.get('phone')})")
        dlg = HelpDialog(
            f"🤖 مساعدة مطلوبة - @{req.get('bot_username')}",
            "ماذا أفعل الآن؟ اختر زراً بالرقم أو اكتب نصاً لإرساله للبوت.",
            options,
            context_lines=ctx,
            bot_message=req.get('message_text', ''),
            timeout=int(req.get('timeout') or 120),
            parent=self,
        )
        QApplication.beep()
        self.activateWindow()
        res = dlg.exec_()
        answer = dlg.answer if res == QDialog.Accepted else None
        if answer:
            self.log('info', f"   ↳ إجابتك: {answer}")
        else:
            self.log('info', "   ↳ لا إجابة - يكمل الذكاء الاصطناعي تلقائياً")
        self.help_bridge.deliver(answer)

    # ------------------------------------------------------------------
    # أدوات
    # ------------------------------------------------------------------
    def clear_templates(self):
        r = QMessageBox.question(self, "تأكيد", "هل تريد حذف كل القوالب التي تعلمها الذكاء الاصطناعي؟",
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes and worker is not None:
            worker.supabase.clear('bot_templates')
            self.log('success', "✅ تم مسح القوالب المتعلَّمة.")

    def _open_path(self, path: Path):
        try:
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith('win'):
                os.startfile(str(path))  # type: ignore[attr-defined]
            elif sys.platform == 'darwin':
                os.system(f'open "{path}"')
            else:
                os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')
        except Exception as e:
            self._error("تعذر فتح المجلد", str(e))

    def show_help(self):
        QMessageBox.information(self, "مساعدة", (
            "<b>خطوات الاستخدام:</b><br>"
            "1) ضع ملفات <code>.session</code> داخل <code>sessions/&lt;اسم المجموعة&gt;/</code><br>"
            "2) أدخل API_ID و API_HASH من my.telegram.org<br>"
            "3) اختر المجلد وحدّد الجلسات<br>"
            "4) اكتب المهمة (رابط بوت إحالة، @قناة، أو خطوات يدوية سطراً سطراً)<br>"
            "5) اضغط «تشغيل» - سيعرض الذكاء الاصطناعي ما فهمه ويسألك عند الغموض<br><br>"
            "<b>الخطوات اليدوية المدعومة:</b> start, language, subscribe, check, math, emoji, "
            "text:نص, phone, visit, forward:رابط, react_post:رابط, vote_poll:رابط, click:اسم الزر<br><br>"
            "<b>ملف json جانبي (اختياري):</b> بجانب كل جلسة يمكن وضع ملف بنفس الاسم يحوي "
            "<code>api_id</code>, <code>api_hash</code>, <code>phone</code>."
        ))

    def show_about(self):
        QMessageBox.about(self, "حول البرنامج", (
            f"<b>tgmultipanel</b> v{APP_VERSION}<br>مدير جلسات Telethon - واجهة سطح المكتب<br><br>"
            "المحرك: worker.py (Worker Engine v2.4.0 Desktop)<br>"
            "الذكاء الاصطناعي: ai_agent.py v3.0.2<br>"
            "الواجهة: PyQt5"
        ))

    def _error(self, title: str, message: str):
        self.log('error', f"❌ {title}: {message}")
        QMessageBox.critical(self, title, message)

    @staticmethod
    def _friendly_error(err: str) -> str:
        """تحويل أخطاء تيليجرام/الشبكة الشائعة إلى رسائل عربية مفهومة."""
        low = (err or '').lower()
        table = [
            ('floodwait', 'تيليجرام يطلب الانتظار (FloodWait) - حاول لاحقاً'),
            ('flood', 'تيليجرام يطلب الانتظار - حاول لاحقاً'),
            ('authkey', 'مفتاح الجلسة غير صالح - أعد تسجيل الدخول لهذا الحساب'),
            ('auth key', 'مفتاح الجلسة غير صالح - أعد تسجيل الدخول لهذا الحساب'),
            ('not authorized', 'الجلسة غير مسجَّلة دخول'),
            ('deactivated', 'الحساب معطَّل من تيليجرام'),
            ('banned', 'الحساب محظور'),
            ('database is locked', 'ملف الجلسة مستخدم من برنامج آخر - أغلقه ثم أعد المحاولة'),
            ('api_id', 'بيانات API_ID/API_HASH غير صحيحة'),
            ('api id', 'بيانات API_ID/API_HASH غير صحيحة'),
            ('connection', 'مشكلة في الاتصال بالإنترنت/تيليجرام'),
            ('timed out', 'انتهت مهلة الاتصال - تحقق من الإنترنت'),
            ('timeout', 'انتهت مهلة الاتصال - تحقق من الإنترنت'),
            ('username', 'اسم المستخدم/القناة غير موجود'),
            ('no user has', 'اسم المستخدم/البوت غير موجود'),
            ('cannot find any entity', 'تعذر العثور على البوت/القناة - تحقق من الرابط'),
            ('too many consecutive errors', 'أخطاء متتالية كثيرة - تم تعطيل الجلسة'),
            ('max retries', 'تجاوز عدد المحاولات'),
            ('attempt', 'فشلت المحاولات'),
        ]
        for key, msg in table:
            if key in low:
                return msg
        return err[:120] if err else 'سبب غير معروف'


# ======================================================================
# نقطة الدخول
# ======================================================================
def _install_crash_handler(app: QApplication):
    """أي خطأ غير متوقع: يُسجَّل في logs/gui.log ويُعرض برسالة عربية بدل إغلاق صامت."""
    import traceback
    try:
        fh = logging.handlers.RotatingFileHandler(
            str(BASE_DIR / 'logs' / 'gui.log'), maxBytes=1024 * 1024, backupCount=2, encoding='utf-8')
        fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
        logging.getLogger().addHandler(fh)
    except Exception:
        pass

    def _hook(exc_type, exc, tb):
        text = ''.join(traceback.format_exception(exc_type, exc, tb))
        logging.getLogger('gui').error("Unhandled exception:\n%s", text)
        try:
            win = next((w for w in app.topLevelWidgets() if isinstance(w, MainWindow)), None)
            if win is not None:
                win.log('error', f"❌ خطأ غير متوقع: {exc_type.__name__}: {exc}")
            QMessageBox.critical(win, "خطأ غير متوقع",
                                 f"حدث خطأ غير متوقع في الواجهة:\n{exc_type.__name__}: {exc}\n\n"
                                 f"تم حفظ التفاصيل في logs/gui.log - البرنامج سيستمر بالعمل.")
        except Exception:
            pass
    sys.excepthook = _hook


def main() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setLayoutDirection(Qt.RightToLeft)
    _install_crash_handler(app)
    # خط مناسب للعربية على ويندوز
    if sys.platform.startswith('win'):
        f = QFont("Segoe UI", 10)
    else:
        f = QFont()
        f.setPointSize(10)
    app.setFont(f)
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == '__main__':
    sys.exit(main())
