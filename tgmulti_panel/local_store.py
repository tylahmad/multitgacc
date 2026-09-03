#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
========================================================================
 local_store.py - مخزن بيانات محلي (بديل Supabase) لنسخة سطح المكتب
========================================================================
الهدف:
  إبقاء منطق التنفيذ في worker.py كما هو 100% مع إزالة الاعتماد على Supabase.
  يوفر هذا الملف واجهة استعلام صغيرة *مطابقة في الشكل* لواجهة supabase-py:

      db.table('tasks_queue').select('*').eq('status', 'pending') \
        .order('created_at').limit(3).execute().data

  بحيث تبقى جميع مواضع الاستدعاء في worker.py دون تغيير (باستثناء اسم الكائن).

الخصائص:
  - جميع الجداول في الذاكرة (لكل تشغيل).
  - الجداول المذكورة في persistent_tables (افتراضياً: bot_templates) تُحفظ
    محلياً كـ JSON داخل مجلد data/ ليستمر "التعلم" بين التشغيلات.
  - لا يحتاج إنترنت ولا مفاتيح ولا متغيرات بيئة.
  - آمن للاستخدام من عدة خيوط (RLock).

العمليات المدعومة:
  select / insert / update / upsert / delete
  eq / neq / is_ / lt / lte / gt / gte / in_
  order / limit / execute
========================================================================
"""

from __future__ import annotations

import copy
import json
import os
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# القيم الافتراضية لكل جدول (تحاكي DEFAULT في schema.sql القديم)
TABLE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    'tasks_queue': {
        'target_bot_link': '',
        'task_type': 'composite',
        'session_id': None,
        'status': 'pending',
        'ref_id': None,
        'target_message_link': None,
        'solve_pattern': None,
        'result_data': None,
        'error_message': None,
        'retry_count': 0,
        'max_retries': 3,
        'speed': 'medium',
        'composite_steps': '[]',
        'emoji_target': '👍',
        'vote_option': '0',
        'required_accounts': 1,
        'parent_task_id': None,
        'multi_account': False,
        'channel_list': '[]',
        'started_at': None,
        'completed_at': None,
    },
    'client_sessions': {
        'phone': '',
        'session_string': None,
        'session_file': None,
        'is_active': True,
        'is_banned': False,
        'last_used_at': None,
        'error_message': None,
        'proxy_id': None,
    },
    'bot_templates': {
        'template_name': None,
        'steps': '[]',
        'total_steps': 0,
        'success_count': 0,
        'fail_count': 0,
        'updated_at': None,
        'last_used_at': None,
    },
    'proxy_list': {
        'proxy_type': 'socks5',
        'username': None,
        'password': None,
        'max_accounts': 5,
        'used_count': 0,
        'is_active': True,
        'last_used_at': None,
    },
    'completed_tasks_history': {
        'task_type': None,
        'parent_task_id': None,
    },
    'task_logs': {
        'status': None,
        'message': '',
        'parent_task_id': None,
    },
    'fallback_requests': {
        'status': 'pending',
        'admin_response': None,
    },
    'settings': {
        'value': None,
        'is_enabled': False,
    },
}

# عمود المفتاح الأساسي لكل جدول (الافتراضي: id)
PRIMARY_KEYS: Dict[str, str] = {
    'settings': 'key',
}

# قيود التفرد (تحاكي الفهارس الفريدة في schema.sql القديم) - يعتمد عليها
# worker.record_completion: insert يفشل عند التكرار -> يتحول إلى update
UNIQUE_CONSTRAINTS: Dict[str, Tuple[str, ...]] = {
    'completed_tasks_history': ('session_id', 'bot_username', 'parent_task_id'),
    'bot_templates': ('bot_username',),
}


class LocalStoreError(Exception):
    """خطأ في المخزن المحلي (مثل تعارض قيد فريد) - يحاكي APIError في supabase-py."""

# أعمدة وقت الإنشاء (تُملأ تلقائياً عند الإدراج)
CREATED_AT_COLUMNS: Dict[str, str] = {
    'tasks_queue': 'created_at',
    'client_sessions': 'added_at',
    'bot_templates': 'created_at',
    'proxy_list': 'added_at',
    'completed_tasks_history': 'completed_at',
    'task_logs': 'created_at',
    'fallback_requests': 'created_at',
    'settings': 'updated_at',
}


class LocalResponse:
    """يحاكي كائن الاستجابة في supabase-py (يوفر .data و .count)."""

    __slots__ = ('data', 'count')

    def __init__(self, data: List[Dict[str, Any]]):
        self.data = data
        self.count = len(data)

    def __repr__(self) -> str:  # pragma: no cover
        return f"LocalResponse(count={self.count})"


class LocalQuery:
    """باني استعلام سلس (fluent) - يُنفَّذ عند استدعاء execute()."""

    def __init__(self, store: 'LocalStore', table: str):
        self._store = store
        self.table = table
        self._op: str = 'select'
        self._columns: Optional[List[str]] = None
        self._payload: Any = None
        self._on_conflict: Optional[str] = None
        self._filters: List[Tuple[str, str, Any]] = []
        self._order: List[Tuple[str, bool, Optional[bool]]] = []
        self._limit: Optional[int] = None

    # ---------------- العمليات ----------------
    def select(self, columns: str = '*', *args, **kwargs) -> 'LocalQuery':
        self._op = 'select'
        cols = (columns or '*').replace(' ', '')
        self._columns = None if cols == '*' else [c for c in cols.split(',') if c]
        return self

    def insert(self, data: Any, *args, **kwargs) -> 'LocalQuery':
        self._op = 'insert'
        self._payload = data
        return self

    def update(self, data: Dict[str, Any], *args, **kwargs) -> 'LocalQuery':
        self._op = 'update'
        self._payload = data
        return self

    def upsert(self, data: Any, on_conflict: Optional[str] = None, *args, **kwargs) -> 'LocalQuery':
        self._op = 'upsert'
        self._payload = data
        self._on_conflict = on_conflict
        return self

    def delete(self, *args, **kwargs) -> 'LocalQuery':
        self._op = 'delete'
        return self

    # ---------------- المرشحات ----------------
    def eq(self, column: str, value: Any) -> 'LocalQuery':
        self._filters.append(('eq', column, value))
        return self

    def neq(self, column: str, value: Any) -> 'LocalQuery':
        self._filters.append(('neq', column, value))
        return self

    def is_(self, column: str, value: Any) -> 'LocalQuery':
        self._filters.append(('is', column, value))
        return self

    def lt(self, column: str, value: Any) -> 'LocalQuery':
        self._filters.append(('lt', column, value))
        return self

    def lte(self, column: str, value: Any) -> 'LocalQuery':
        self._filters.append(('lte', column, value))
        return self

    def gt(self, column: str, value: Any) -> 'LocalQuery':
        self._filters.append(('gt', column, value))
        return self

    def gte(self, column: str, value: Any) -> 'LocalQuery':
        self._filters.append(('gte', column, value))
        return self

    def in_(self, column: str, values: Iterable[Any]) -> 'LocalQuery':
        self._filters.append(('in', column, list(values)))
        return self

    # ---------------- الترتيب والحد ----------------
    def order(self, column: str, desc: bool = False, nullsfirst: Optional[bool] = None, **kwargs) -> 'LocalQuery':
        self._order.append((column, bool(desc), nullsfirst))
        return self

    def limit(self, n: int, *args, **kwargs) -> 'LocalQuery':
        self._limit = int(n)
        return self

    # ---------------- التنفيذ ----------------
    def execute(self) -> LocalResponse:
        return self._store._execute(self)


class LocalStore:
    """قاعدة بيانات محلية بسيطة في الذاكرة مع حفظ اختياري لبعض الجداول."""

    def __init__(self, data_dir: Optional[os.PathLike] = None,
                 persistent_tables: Iterable[str] = ('bot_templates',)):
        self._lock = threading.RLock()
        self._tables: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.data_dir: Optional[Path] = Path(data_dir) if data_dir else None
        self._persistent = set(persistent_tables) if self.data_dir else set()
        if self.data_dir:
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                self._persistent = set()
            self._load_persistent()

    # ---------------- الواجهة العامة ----------------
    def table(self, name: str) -> LocalQuery:
        return LocalQuery(self, name)

    def rows(self, table: str) -> List[Dict[str, Any]]:
        """نسخة من كل صفوف الجدول (للاستخدام في الواجهة/التقارير)."""
        with self._lock:
            return copy.deepcopy(self._tables.get(table, []))

    def clear(self, table: Optional[str] = None, keep_persistent: bool = True):
        """مسح الجداول (افتراضياً: كل الجداول غير المحفوظة)."""
        with self._lock:
            names = [table] if table else list(self._tables.keys())
            for name in names:
                if keep_persistent and name in self._persistent and table is None:
                    continue
                self._tables[name] = []
                if name in self._persistent:
                    self._save(name)

    def count(self, table: str) -> int:
        with self._lock:
            return len(self._tables.get(table, []))

    # ---------------- الحفظ المحلي ----------------
    def _file_for(self, table: str) -> Path:
        return self.data_dir / f"{table}.json"  # type: ignore[operator]

    def _load_persistent(self):
        for name in list(self._persistent):
            path = self._file_for(name)
            if not path.exists():
                continue
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    self._tables[name] = [r for r in data if isinstance(r, dict)]
            except Exception:
                # ملف تالف: نتجاهله ولا نوقف البرنامج
                self._tables[name] = []

    def _save(self, table: str):
        if table not in self._persistent:
            return
        path = self._file_for(table)
        tmp = path.with_suffix('.json.tmp')
        try:
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(self._tables.get(table, []), fh, ensure_ascii=False, indent=2, default=str)
            os.replace(tmp, path)
        except Exception:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass

    # ---------------- المنطق الداخلي ----------------
    @staticmethod
    def _match(row: Dict[str, Any], filters: List[Tuple[str, str, Any]]) -> bool:
        for op, col, val in filters:
            cur = row.get(col)
            if op == 'eq':
                if cur != val:
                    return False
            elif op == 'neq':
                if cur == val:
                    return False
            elif op == 'is':
                want_null = (val is None) or (isinstance(val, str) and val.lower() == 'null')
                if want_null:
                    if cur is not None:
                        return False
                elif isinstance(val, str) and val.lower() == 'not null':
                    if cur is None:
                        return False
                else:
                    if cur != val:
                        return False
            elif op in ('lt', 'lte', 'gt', 'gte'):
                if cur is None:
                    return False
                try:
                    if op == 'lt' and not (cur < val):
                        return False
                    if op == 'lte' and not (cur <= val):
                        return False
                    if op == 'gt' and not (cur > val):
                        return False
                    if op == 'gte' and not (cur >= val):
                        return False
                except TypeError:
                    return False
            elif op == 'in':
                if cur not in val:
                    return False
        return True

    @staticmethod
    def _sort(rows: List[Dict[str, Any]], order: List[Tuple[str, bool, Optional[bool]]]) -> List[Dict[str, Any]]:
        # نطبق الترتيب من الأخير إلى الأول للحصول على ترتيب مستقر متعدد الأعمدة
        result = list(rows)
        for col, desc, nullsfirst in reversed(order):
            non_null = [r for r in result if r.get(col) is not None]
            nulls = [r for r in result if r.get(col) is None]
            try:
                non_null.sort(key=lambda r: r.get(col), reverse=desc)
            except TypeError:
                non_null.sort(key=lambda r: str(r.get(col)), reverse=desc)
            if nullsfirst is None:
                nullsfirst = desc  # سلوك PostgreSQL الافتراضي
            result = (nulls + non_null) if nullsfirst else (non_null + nulls)
        return result

    def _project(self, rows: List[Dict[str, Any]], columns: Optional[List[str]]) -> List[Dict[str, Any]]:
        if not columns:
            return [copy.deepcopy(r) for r in rows]
        return [{c: copy.deepcopy(r.get(c)) for c in columns} for r in rows]

    def _new_row(self, table: str, data: Dict[str, Any]) -> Dict[str, Any]:
        row = copy.deepcopy(TABLE_DEFAULTS.get(table, {}))
        row.update(copy.deepcopy(data))
        pk = PRIMARY_KEYS.get(table, 'id')
        if pk == 'id' and not row.get('id'):
            row['id'] = str(uuid.uuid4())
        created_col = CREATED_AT_COLUMNS.get(table)
        if created_col and not row.get(created_col):
            row[created_col] = _now_iso()
        return row

    def _execute(self, q: LocalQuery) -> LocalResponse:
        with self._lock:
            rows = self._tables[q.table]

            if q._op == 'insert':
                payload = q._payload if isinstance(q._payload, list) else [q._payload]
                inserted = []
                unique_cols = UNIQUE_CONSTRAINTS.get(q.table)
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    row = self._new_row(q.table, item)
                    if unique_cols:
                        for r in rows:
                            if all(r.get(c) == row.get(c) for c in unique_cols):
                                raise LocalStoreError(
                                    f"duplicate key value violates unique constraint on "
                                    f"{q.table}({', '.join(unique_cols)})"
                                )
                    rows.append(row)
                    inserted.append(copy.deepcopy(row))
                self._save(q.table)
                return LocalResponse(inserted)

            if q._op == 'upsert':
                payload = q._payload if isinstance(q._payload, list) else [q._payload]
                key = q._on_conflict or PRIMARY_KEYS.get(q.table, 'id')
                out = []
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    existing = None
                    if item.get(key) is not None:
                        for r in rows:
                            if r.get(key) == item.get(key):
                                existing = r
                                break
                    if existing is not None:
                        existing.update(copy.deepcopy(item))
                        out.append(copy.deepcopy(existing))
                    else:
                        row = self._new_row(q.table, item)
                        rows.append(row)
                        out.append(copy.deepcopy(row))
                self._save(q.table)
                return LocalResponse(out)

            if q._op == 'update':
                updated = []
                for r in rows:
                    if self._match(r, q._filters):
                        r.update(copy.deepcopy(q._payload or {}))
                        updated.append(copy.deepcopy(r))
                if updated:
                    self._save(q.table)
                return LocalResponse(updated)

            if q._op == 'delete':
                keep, deleted = [], []
                for r in rows:
                    (deleted if self._match(r, q._filters) else keep).append(r)
                self._tables[q.table] = keep
                if deleted:
                    self._save(q.table)
                return LocalResponse([copy.deepcopy(r) for r in deleted])

            # select
            matched = [r for r in rows if self._match(r, q._filters)]
            if q._order:
                matched = self._sort(matched, q._order)
            if q._limit is not None:
                matched = matched[:q._limit]
            return LocalResponse(self._project(matched, q._columns))


__all__ = ['LocalStore', 'LocalQuery', 'LocalResponse', 'LocalStoreError', 'TABLE_DEFAULTS']
