from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .constants import IGNORABLE_MOD_WARNING_CODES
from .mod_types import (
    DEFAULT_MOD_TYPE_ID,
    DEFAULT_MOD_TYPE_IDS,
    DEFAULT_MOD_TYPE_NAMES,
    default_mod_types,
)


DEFAULT_PLAYSET_ID = "default"
DEFAULT_PLAYSET_NAME = "默认"


class StateRepository:
    """Stores user intent only; installed pack facts are always rescanned."""

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=15)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS system_info (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS app_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS user_mod_data (
                    mod_id TEXT PRIMARY KEY,
                    alias TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    mod_type TEXT NOT NULL DEFAULT 'unknown',
                    mod_types TEXT NOT NULL DEFAULT '[]',
                    published_workshop_id TEXT NOT NULL DEFAULT '',
                    hidden INTEGER NOT NULL DEFAULT 0,
                    ignored_warning_codes TEXT NOT NULL DEFAULT '[]',
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS custom_mod_types (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS presets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS preset_items (
                    preset_id TEXT NOT NULL REFERENCES presets(id) ON DELETE CASCADE,
                    mod_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (preset_id, mod_id)
                );

                CREATE TABLE IF NOT EXISTS playsets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS playset_items (
                    playset_id TEXT NOT NULL REFERENCES playsets(id) ON DELETE CASCADE,
                    mod_id TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY (playset_id, mod_id)
                );

                CREATE TABLE IF NOT EXISTS load_order_backups (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    ordered_mod_ids TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS data_sync_items (
                    pack_name TEXT PRIMARY KEY COLLATE NOCASE,
                    workshop_id TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_size INTEGER NOT NULL,
                    source_mtime_ns INTEGER NOT NULL,
                    target_path TEXT NOT NULL,
                    target_size INTEGER NOT NULL,
                    target_mtime_ns INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )
            user_data_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(user_mod_data)").fetchall()
            }
            if "mod_type" not in user_data_columns:
                connection.execute(
                    "ALTER TABLE user_mod_data ADD COLUMN mod_type TEXT NOT NULL DEFAULT 'unknown'"
                )
            if "hidden" not in user_data_columns:
                connection.execute(
                    "ALTER TABLE user_mod_data ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0"
                )
            if "mod_types" not in user_data_columns:
                connection.execute(
                    "ALTER TABLE user_mod_data ADD COLUMN mod_types TEXT NOT NULL DEFAULT '[]'"
                )
            if "published_workshop_id" not in user_data_columns:
                connection.execute(
                    "ALTER TABLE user_mod_data ADD COLUMN published_workshop_id TEXT NOT NULL DEFAULT ''"
                )
            if "ignored_warning_codes" not in user_data_columns:
                connection.execute(
                    "ALTER TABLE user_mod_data ADD COLUMN ignored_warning_codes TEXT NOT NULL DEFAULT '[]'"
                )
            for row in connection.execute(
                "SELECT mod_id, mod_type, mod_types FROM user_mod_data"
            ).fetchall():
                selected_types = self._decode_mod_types(row["mod_types"], row["mod_type"])
                connection.execute(
                    "UPDATE user_mod_data SET mod_type = ?, mod_types = ? WHERE mod_id = ?",
                    (
                        selected_types[0],
                        json.dumps(selected_types, ensure_ascii=False),
                        row["mod_id"],
                    ),
                )
            self._initialize_playsets(connection)
            connection.execute(
                "INSERT OR REPLACE INTO system_info(key, value) VALUES('schema_version', '7')"
            )

    @classmethod
    def _initialize_playsets(cls, connection: sqlite3.Connection) -> None:
        now = int(time.time() * 1000)
        legacy_order_row = connection.execute(
            "SELECT value FROM app_state WHERE key = 'enabled_order'"
        ).fetchone()
        legacy_order = cls._decode_order(legacy_order_row["value"] if legacy_order_row else "[]")

        default_row = connection.execute(
            "SELECT id FROM playsets WHERE id = ?",
            (DEFAULT_PLAYSET_ID,),
        ).fetchone()
        if not default_row:
            connection.execute(
                "INSERT INTO playsets(id, name, created_at, updated_at) VALUES(?, ?, ?, ?)",
                (DEFAULT_PLAYSET_ID, DEFAULT_PLAYSET_NAME, now, now),
            )
            cls._replace_playset_items(connection, DEFAULT_PLAYSET_ID, legacy_order)

        migration_row = connection.execute(
            "SELECT value FROM system_info WHERE key = 'playsets_migrated'"
        ).fetchone()
        if not migration_row:
            preset_rows = connection.execute(
                "SELECT id, name, created_at, updated_at FROM presets ORDER BY created_at, id"
            ).fetchall()
            for preset in preset_rows:
                playset_id = str(preset["id"] or uuid.uuid4().hex)
                if playset_id == DEFAULT_PLAYSET_ID or connection.execute(
                    "SELECT 1 FROM playsets WHERE id = ?",
                    (playset_id,),
                ).fetchone():
                    playset_id = uuid.uuid4().hex
                base_name = str(preset["name"] or "旧预设").strip() or "旧预设"
                if base_name.casefold() == DEFAULT_PLAYSET_NAME.casefold():
                    base_name = f"{DEFAULT_PLAYSET_NAME}（旧预设）"
                playset_name = cls._available_playset_name(connection, base_name)
                connection.execute(
                    "INSERT INTO playsets(id, name, created_at, updated_at) VALUES(?, ?, ?, ?)",
                    (
                        playset_id,
                        playset_name,
                        int(preset["created_at"] or now),
                        int(preset["updated_at"] or now),
                    ),
                )
                item_rows = connection.execute(
                    "SELECT mod_id FROM preset_items WHERE preset_id = ? ORDER BY position, mod_id",
                    (preset["id"],),
                ).fetchall()
                cls._replace_playset_items(
                    connection,
                    playset_id,
                    [str(row["mod_id"]) for row in item_rows],
                )
            connection.execute(
                "INSERT INTO system_info(key, value) VALUES('playsets_migrated', '1')"
            )

        current_row = connection.execute(
            "SELECT value FROM app_state WHERE key = 'current_playset_id'"
        ).fetchone()
        current_id = str(current_row["value"] if current_row else DEFAULT_PLAYSET_ID)
        if not connection.execute("SELECT 1 FROM playsets WHERE id = ?", (current_id,)).fetchone():
            current_id = DEFAULT_PLAYSET_ID
        cls._write_app_state(connection, "current_playset_id", current_id)

        initialized_row = connection.execute(
            "SELECT value FROM app_state WHERE key = 'playsets_initialized'"
        ).fetchone()
        if not initialized_row:
            cls._write_app_state(
                connection,
                "playsets_initialized",
                "1" if legacy_order_row else "0",
            )

    @staticmethod
    def _decode_order(raw_value: Any) -> list[str]:
        try:
            decoded = json.loads(str(raw_value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(decoded, list):
            return []
        return list(dict.fromkeys(str(item) for item in decoded if str(item).strip()))

    @staticmethod
    def _write_app_state(connection: sqlite3.Connection, key: str, value: str) -> None:
        connection.execute(
            """
            INSERT INTO app_state(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    @staticmethod
    def _replace_playset_items(
        connection: sqlite3.Connection,
        playset_id: str,
        mod_ids: list[str],
    ) -> list[str]:
        normalized = list(dict.fromkeys(str(item) for item in mod_ids if str(item).strip()))
        connection.execute("DELETE FROM playset_items WHERE playset_id = ?", (playset_id,))
        connection.executemany(
            "INSERT INTO playset_items(playset_id, mod_id, position) VALUES(?, ?, ?)",
            [(playset_id, mod_id, index) for index, mod_id in enumerate(normalized)],
        )
        return normalized

    @staticmethod
    def _available_playset_name(connection: sqlite3.Connection, base_name: str) -> str:
        candidate = base_name
        suffix = 2
        while connection.execute(
            "SELECT 1 FROM playsets WHERE name = ? COLLATE NOCASE",
            (candidate,),
        ).fetchone():
            candidate = f"{base_name} ({suffix})"
            suffix += 1
        return candidate

    def get_enabled_order(self) -> list[str]:
        return list(self.get_current_playset()["mod_ids"])

    def set_enabled_order(self, mod_ids: list[str]) -> None:
        self.update_current_playset(mod_ids)

    def get_active_order_filename(self) -> str:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_state WHERE key = 'active_order_filename'"
            ).fetchone()
        value = str(row["value"] if row else "")
        return value if value in {"used_mods.txt", "my_mods.txt"} else ""

    def set_active_order_filename(self, filename: str) -> None:
        if filename not in {"used_mods.txt", "my_mods.txt"}:
            raise ValueError("不支持的加载清单文件名")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO app_state(key, value) VALUES('active_order_filename', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (filename,),
            )

    def list_user_mod_data(self) -> dict[str, dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT mod_id, alias, notes, mod_type, mod_types, published_workshop_id, hidden, "
                "ignored_warning_codes "
                "FROM user_mod_data"
            ).fetchall()
        return {
            row["mod_id"]: {
                "alias": row["alias"] or "",
                "notes": row["notes"] or "",
                "mod_type": self._decode_mod_types(row["mod_types"], row["mod_type"])[0],
                "mod_types": self._decode_mod_types(row["mod_types"], row["mod_type"]),
                "published_workshop_id": row["published_workshop_id"] or "",
                "hidden": bool(row["hidden"]),
                "ignored_warning_codes": self._decode_ignored_warning_codes(
                    row["ignored_warning_codes"]
                ),
            }
            for row in rows
        }

    @staticmethod
    def _decode_ignored_warning_codes(raw_value: Any) -> list[str]:
        try:
            decoded = json.loads(str(raw_value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(decoded, list):
            return []
        selected = {str(item) for item in decoded}
        return [code for code in IGNORABLE_MOD_WARNING_CODES if code in selected]

    def save_user_mod_data(self, mod_id: str, alias: str, notes: str) -> dict[str, str]:
        now = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_mod_data(mod_id, alias, notes, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(mod_id) DO UPDATE SET
                    alias = excluded.alias,
                    notes = excluded.notes,
                    updated_at = excluded.updated_at
                """,
                (mod_id, alias.strip(), notes.strip(), now),
            )
        return {"alias": alias.strip(), "notes": notes.strip()}

    def list_mod_types(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id, name, created_at, updated_at "
                "FROM custom_mod_types ORDER BY name COLLATE NOCASE, created_at"
            ).fetchall()
        return [
            *default_mod_types(),
            *[
                {
                    "id": row["id"],
                    "name": row["name"],
                    "built_in": False,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ],
        ]

    def create_mod_type(self, name: str) -> dict[str, Any]:
        clean_name = self._validate_mod_type_name(name)
        now = int(time.time() * 1000)
        type_id = f"custom:{uuid.uuid4().hex}"
        with self._lock, self._connect() as connection:
            self._ensure_custom_type_name_available(connection, clean_name)
            connection.execute(
                "INSERT INTO custom_mod_types(id, name, created_at, updated_at) VALUES(?, ?, ?, ?)",
                (type_id, clean_name, now, now),
            )
        return {
            "id": type_id,
            "name": clean_name,
            "built_in": False,
            "created_at": now,
            "updated_at": now,
        }

    def update_mod_type(self, type_id: str, name: str) -> dict[str, Any]:
        normalized_id = str(type_id or "").strip()
        if normalized_id in DEFAULT_MOD_TYPE_IDS:
            raise ValueError("默认类型无法修改")
        clean_name = self._validate_mod_type_name(name)
        now = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT created_at FROM custom_mod_types WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            if not existing:
                raise ValueError("自定义类型不存在")
            self._ensure_custom_type_name_available(connection, clean_name, normalized_id)
            connection.execute(
                "UPDATE custom_mod_types SET name = ?, updated_at = ? WHERE id = ?",
                (clean_name, now, normalized_id),
            )
        return {
            "id": normalized_id,
            "name": clean_name,
            "built_in": False,
            "created_at": existing["created_at"],
            "updated_at": now,
        }

    def delete_mod_type(self, type_id: str) -> None:
        normalized_id = str(type_id or "").strip()
        if normalized_id in DEFAULT_MOD_TYPE_IDS:
            raise ValueError("默认类型无法删除")
        now = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM custom_mod_types WHERE id = ?",
                (normalized_id,),
            ).fetchone()
            if not existing:
                raise ValueError("自定义类型不存在")
            rows = connection.execute(
                "SELECT mod_id, mod_type, mod_types FROM user_mod_data"
            ).fetchall()
            for row in rows:
                selected_types = [
                    item
                    for item in self._decode_mod_types(row["mod_types"], row["mod_type"])
                    if item != normalized_id
                ]
                selected_types = self._canonical_mod_types(selected_types)
                connection.execute(
                    "UPDATE user_mod_data SET mod_type = ?, mod_types = ?, updated_at = ? "
                    "WHERE mod_id = ?",
                    (
                        selected_types[0],
                        json.dumps(selected_types, ensure_ascii=False),
                        now,
                        row["mod_id"],
                    ),
                )
            connection.execute("DELETE FROM custom_mod_types WHERE id = ?", (normalized_id,))

    def set_mod_type(self, mod_id: str, type_id: str) -> str:
        return self.set_mod_types(mod_id, [type_id])[0]

    def set_mod_types(self, mod_id: str, type_ids: list[str]) -> list[str]:
        selected_types = self._canonical_mod_types(type_ids)
        with self._lock, self._connect() as connection:
            custom_ids = [item for item in selected_types if item not in DEFAULT_MOD_TYPE_IDS]
            if custom_ids:
                placeholders = ",".join("?" for _ in custom_ids)
                existing_ids = {
                    row["id"]
                    for row in connection.execute(
                        f"SELECT id FROM custom_mod_types WHERE id IN ({placeholders})",
                        custom_ids,
                    ).fetchall()
                }
                if existing_ids != set(custom_ids):
                    raise ValueError("模组类型不存在")
            now = int(time.time() * 1000)
            connection.execute(
                """
                INSERT INTO user_mod_data(mod_id, mod_type, mod_types, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(mod_id) DO UPDATE SET
                    mod_type = excluded.mod_type,
                    mod_types = excluded.mod_types,
                    updated_at = excluded.updated_at
                """,
                (
                    str(mod_id),
                    selected_types[0],
                    json.dumps(selected_types, ensure_ascii=False),
                    now,
                ),
            )
        return selected_types

    def set_published_workshop_id(self, mod_id: str, workshop_id: str) -> str:
        normalized_id = str(workshop_id or "").strip()
        if normalized_id and not normalized_id.isdigit():
            raise ValueError("Workshop ID 无效")
        now = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_mod_data(mod_id, published_workshop_id, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(mod_id) DO UPDATE SET
                    published_workshop_id = excluded.published_workshop_id,
                    updated_at = excluded.updated_at
                """,
                (str(mod_id), normalized_id, now),
            )
        return normalized_id

    def set_mod_hidden(self, mod_id: str, hidden: bool) -> bool:
        normalized = bool(hidden)
        now = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO user_mod_data(mod_id, hidden, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(mod_id) DO UPDATE SET
                    hidden = excluded.hidden,
                    updated_at = excluded.updated_at
                """,
                (str(mod_id), int(normalized), now),
            )
        return normalized

    def set_mod_warning_ignored(
        self,
        mod_id: str,
        warning_code: str,
        ignored: bool,
    ) -> list[str]:
        normalized_code = str(warning_code or "").strip()
        if normalized_code not in IGNORABLE_MOD_WARNING_CODES:
            raise ValueError("该 MOD 问题不支持忽略")
        now = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT ignored_warning_codes FROM user_mod_data WHERE mod_id = ?",
                (str(mod_id),),
            ).fetchone()
            selected = set(
                self._decode_ignored_warning_codes(
                    row["ignored_warning_codes"] if row else "[]"
                )
            )
            if ignored:
                selected.add(normalized_code)
            else:
                selected.discard(normalized_code)
            ordered = [code for code in IGNORABLE_MOD_WARNING_CODES if code in selected]
            connection.execute(
                """
                INSERT INTO user_mod_data(mod_id, ignored_warning_codes, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(mod_id) DO UPDATE SET
                    ignored_warning_codes = excluded.ignored_warning_codes,
                    updated_at = excluded.updated_at
                """,
                (str(mod_id), json.dumps(ordered, ensure_ascii=False), now),
            )
        return ordered

    def get_data_sync_item(self, pack_name: str) -> dict[str, Any] | None:
        normalized = Path(str(pack_name)).name
        if not normalized:
            return None
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM data_sync_items WHERE pack_name = ? COLLATE NOCASE",
                (normalized,),
            ).fetchone()
        return dict(row) if row else None

    def save_data_sync_item(
        self,
        pack_name: str,
        workshop_id: str,
        source_path: str,
        source_size: int,
        source_mtime_ns: int,
        target_path: str,
        target_size: int,
        target_mtime_ns: int,
    ) -> dict[str, Any]:
        normalized = Path(str(pack_name)).name
        if not normalized.casefold().endswith(".pack"):
            raise ValueError("同步记录必须使用有效的 Pack 文件名")
        now = int(time.time() * 1000)
        values = (
            normalized,
            str(workshop_id or ""),
            str(source_path),
            int(source_size),
            int(source_mtime_ns),
            str(target_path),
            int(target_size),
            int(target_mtime_ns),
            now,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO data_sync_items(
                    pack_name, workshop_id, source_path, source_size, source_mtime_ns,
                    target_path, target_size, target_mtime_ns, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pack_name) DO UPDATE SET
                    workshop_id = excluded.workshop_id,
                    source_path = excluded.source_path,
                    source_size = excluded.source_size,
                    source_mtime_ns = excluded.source_mtime_ns,
                    target_path = excluded.target_path,
                    target_size = excluded.target_size,
                    target_mtime_ns = excluded.target_mtime_ns,
                    updated_at = excluded.updated_at
                """,
                values,
            )
        return {
            "pack_name": normalized,
            "workshop_id": str(workshop_id or ""),
            "source_path": str(source_path),
            "source_size": int(source_size),
            "source_mtime_ns": int(source_mtime_ns),
            "target_path": str(target_path),
            "target_size": int(target_size),
            "target_mtime_ns": int(target_mtime_ns),
            "updated_at": now,
        }

    @staticmethod
    def _validate_mod_type_name(name: str) -> str:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("类型名称不能为空")
        if len(clean_name) > 40:
            raise ValueError("类型名称不能超过 40 个字符")
        return clean_name

    @staticmethod
    def _canonical_mod_types(type_ids: list[str] | tuple[str, ...] | None) -> list[str]:
        normalized = list(
            dict.fromkeys(
                str(item or "").strip()
                for item in (type_ids or [])
                if str(item or "").strip()
            )
        )
        if len(normalized) > 1 and DEFAULT_MOD_TYPE_ID in normalized:
            normalized.remove(DEFAULT_MOD_TYPE_ID)
        return normalized or [DEFAULT_MOD_TYPE_ID]

    @classmethod
    def _decode_mod_types(cls, raw_value: Any, legacy_type: Any = "") -> list[str]:
        values: list[str] = []
        try:
            decoded = json.loads(str(raw_value or "[]"))
            if isinstance(decoded, list):
                values = [str(item) for item in decoded]
        except (TypeError, ValueError, json.JSONDecodeError):
            values = []
        if not values:
            values = [str(legacy_type or DEFAULT_MOD_TYPE_ID)]
        return cls._canonical_mod_types(values)

    @staticmethod
    def _ensure_custom_type_name_available(
        connection: sqlite3.Connection,
        name: str,
        excluded_id: str = "",
    ) -> None:
        if name.casefold() in DEFAULT_MOD_TYPE_NAMES:
            raise ValueError("类型名称与默认类型重复")
        row = connection.execute(
            "SELECT id FROM custom_mod_types WHERE name = ? COLLATE NOCASE AND id <> ?",
            (name, excluded_id),
        ).fetchone()
        if row:
            raise ValueError("类型名称已存在")

    def list_playsets(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            playset_rows = connection.execute(
                """
                SELECT id, name, created_at, updated_at
                FROM playsets
                ORDER BY CASE WHEN id = ? THEN 0 ELSE 1 END, name COLLATE NOCASE, id
                """,
                (DEFAULT_PLAYSET_ID,),
            ).fetchall()
            item_rows = connection.execute(
                "SELECT playset_id, mod_id, position FROM playset_items "
                "ORDER BY playset_id, position, mod_id"
            ).fetchall()
        items_by_playset: dict[str, list[str]] = {}
        for row in item_rows:
            items_by_playset.setdefault(row["playset_id"], []).append(row["mod_id"])
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "is_default": row["id"] == DEFAULT_PLAYSET_ID,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "mod_ids": items_by_playset.get(row["id"], []),
            }
            for row in playset_rows
        ]

    def get_current_playset_id(self) -> str:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_state WHERE key = 'current_playset_id'"
            ).fetchone()
            playset_id = str(row["value"] if row else DEFAULT_PLAYSET_ID)
            if not connection.execute(
                "SELECT 1 FROM playsets WHERE id = ?",
                (playset_id,),
            ).fetchone():
                playset_id = DEFAULT_PLAYSET_ID
                self._write_app_state(connection, "current_playset_id", playset_id)
        return playset_id

    def get_current_playset(self) -> dict[str, Any]:
        current_id = self.get_current_playset_id()
        return next(
            item for item in self.list_playsets() if item["id"] == current_id
        )

    def are_playsets_initialized(self) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM app_state WHERE key = 'playsets_initialized'"
            ).fetchone()
        return bool(row and str(row["value"]) == "1")

    def mark_playsets_initialized(self) -> None:
        with self._lock, self._connect() as connection:
            self._write_app_state(connection, "playsets_initialized", "1")

    def create_playset(self, name: str, mod_ids: list[str]) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("播放集名称不能为空")
        now = int(time.time() * 1000)
        playset_id = uuid.uuid4().hex
        with self._lock, self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM playsets WHERE name = ? COLLATE NOCASE",
                (clean_name,),
            ).fetchone():
                raise ValueError("播放集名称已存在")
            connection.execute(
                "INSERT INTO playsets(id, name, created_at, updated_at) VALUES(?, ?, ?, ?)",
                (playset_id, clean_name, now, now),
            )
            normalized = self._replace_playset_items(connection, playset_id, mod_ids)
            self._write_app_state(connection, "current_playset_id", playset_id)
            self._write_app_state(
                connection,
                "enabled_order",
                json.dumps(normalized, ensure_ascii=False),
            )
            self._write_app_state(connection, "playsets_initialized", "1")
        return next(item for item in self.list_playsets() if item["id"] == playset_id)

    def rename_playset(self, playset_id: str, name: str) -> dict[str, Any]:
        if playset_id == DEFAULT_PLAYSET_ID:
            raise ValueError("默认播放集无法重命名")
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("播放集名称不能为空")
        now = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM playsets WHERE id = ?",
                (playset_id,),
            ).fetchone():
                raise ValueError("播放集不存在")
            if connection.execute(
                "SELECT 1 FROM playsets WHERE name = ? COLLATE NOCASE AND id <> ?",
                (clean_name, playset_id),
            ).fetchone():
                raise ValueError("播放集名称已存在")
            connection.execute(
                "UPDATE playsets SET name = ?, updated_at = ? WHERE id = ?",
                (clean_name, now, playset_id),
            )
        return next(item for item in self.list_playsets() if item["id"] == playset_id)

    def update_playset(self, playset_id: str, mod_ids: list[str]) -> dict[str, Any]:
        now = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM playsets WHERE id = ?",
                (playset_id,),
            ).fetchone():
                raise ValueError("播放集不存在")
            normalized = self._replace_playset_items(connection, playset_id, mod_ids)
            connection.execute(
                "UPDATE playsets SET updated_at = ? WHERE id = ?",
                (now, playset_id),
            )
            current_row = connection.execute(
                "SELECT value FROM app_state WHERE key = 'current_playset_id'"
            ).fetchone()
            if current_row and str(current_row["value"]) == playset_id:
                self._write_app_state(
                    connection,
                    "enabled_order",
                    json.dumps(normalized, ensure_ascii=False),
                )
            self._write_app_state(connection, "playsets_initialized", "1")
        return next(item for item in self.list_playsets() if item["id"] == playset_id)

    def update_current_playset(self, mod_ids: list[str]) -> dict[str, Any]:
        return self.update_playset(self.get_current_playset_id(), mod_ids)

    def switch_playset(self, playset_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            if not connection.execute(
                "SELECT 1 FROM playsets WHERE id = ?",
                (playset_id,),
            ).fetchone():
                raise ValueError("播放集不存在")
            item_rows = connection.execute(
                "SELECT mod_id FROM playset_items WHERE playset_id = ? ORDER BY position, mod_id",
                (playset_id,),
            ).fetchall()
            mod_ids = [str(row["mod_id"]) for row in item_rows]
            self._write_app_state(connection, "current_playset_id", playset_id)
            self._write_app_state(
                connection,
                "enabled_order",
                json.dumps(mod_ids, ensure_ascii=False),
            )
            self._write_app_state(connection, "playsets_initialized", "1")
        return next(item for item in self.list_playsets() if item["id"] == playset_id)

    def delete_playset(self, playset_id: str) -> dict[str, Any]:
        if playset_id == DEFAULT_PLAYSET_ID:
            raise ValueError("默认播放集无法删除")
        with self._lock, self._connect() as connection:
            current_row = connection.execute(
                "SELECT value FROM app_state WHERE key = 'current_playset_id'"
            ).fetchone()
            cursor = connection.execute("DELETE FROM playsets WHERE id = ?", (playset_id,))
            if cursor.rowcount == 0:
                raise ValueError("播放集不存在")
            if current_row and str(current_row["value"]) == playset_id:
                item_rows = connection.execute(
                    "SELECT mod_id FROM playset_items WHERE playset_id = ? ORDER BY position, mod_id",
                    (DEFAULT_PLAYSET_ID,),
                ).fetchall()
                default_ids = [str(row["mod_id"]) for row in item_rows]
                self._write_app_state(connection, "current_playset_id", DEFAULT_PLAYSET_ID)
                self._write_app_state(
                    connection,
                    "enabled_order",
                    json.dumps(default_ids, ensure_ascii=False),
                )
        return self.get_current_playset()

    def add_backup(self, file_path: str, ordered_mod_ids: list[str]) -> dict[str, Any]:
        backup_id = uuid.uuid4().hex
        created_at = int(time.time() * 1000)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO load_order_backups(id, file_path, created_at, ordered_mod_ids)
                VALUES(?, ?, ?, ?)
                """,
                (
                    backup_id,
                    file_path,
                    created_at,
                    json.dumps(ordered_mod_ids, ensure_ascii=False),
                ),
            )
        return {
            "id": backup_id,
            "file_path": file_path,
            "created_at": created_at,
            "ordered_mod_ids": list(ordered_mod_ids),
        }

    def list_backups(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, file_path, created_at, ordered_mod_ids
                FROM load_order_backups
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        result = []
        for row in rows:
            try:
                ordered_ids = json.loads(row["ordered_mod_ids"])
            except (TypeError, ValueError, json.JSONDecodeError):
                ordered_ids = []
            result.append(
                {
                    "id": row["id"],
                    "file_path": row["file_path"],
                    "created_at": row["created_at"],
                    "ordered_mod_ids": ordered_ids,
                }
            )
        return result
