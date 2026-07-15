from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# =========================================================
# Paths
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "company_assets"
REGISTRY_FILE = ASSETS_DIR / "tools.json"


# =========================================================
# Tool Record
# =========================================================

@dataclass
class ToolRecord:
    tool_id: str
    name: str
    category: str
    description: str
    entrypoint: str
    version: str = "1.0.0"
    status: str = "active"
    reusable: bool = True
    approval_status: str = "approved"
    created_reason: str = ""
    created_by_agent_id: str = ""
    test_status: str = "not_tested"
    test_command: str = ""
    permissions: list[str] | None = None
    metadata: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["permissions"] = list(self.permissions or [])
        data["metadata"] = dict(self.metadata or {})
        return data


# =========================================================
# Errors
# =========================================================

class ToolRegistryError(RuntimeError):
    """Base error for Tool Registry operations."""


class ToolValidationError(ToolRegistryError):
    """Raised when a Tool record is invalid."""


class ToolNotFoundError(ToolRegistryError):
    """Raised when a required Tool does not exist."""


# =========================================================
# Tool Registry
# =========================================================

class ToolRegistry:
    """
    Business AI OS Tool Registry.

    Responsibilities:
    1. Search reusable Tools.
    2. Register newly approved and tested Tools.
    3. Prevent duplicate Tool creation.
    4. Manage Tool version and status.
    5. Preserve Tool execution metadata.
    """

    VALID_STATUSES = {
        "active",
        "inactive",
        "deprecated",
        "testing",
        "failed",
    }

    VALID_APPROVAL_STATUSES = {
        "pending",
        "approved",
        "rejected",
    }

    VALID_TEST_STATUSES = {
        "not_tested",
        "pending",
        "passed",
        "failed",
    }

    def __init__(self, registry_file: Path = REGISTRY_FILE) -> None:
        self.registry_file = Path(registry_file)
        self._ensure_registry_file()

    # =====================================================
    # Storage
    # =====================================================

    def _ensure_registry_file(self) -> None:
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)

        if not self.registry_file.exists():
            self._write_data(
                {
                    "schema_version": "1.0",
                    "tools": [],
                    "updated_at": self._now(),
                }
            )

    def _read_data(self) -> dict[str, Any]:
        try:
            with self.registry_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            return {
                "schema_version": "1.0",
                "tools": [],
                "updated_at": self._now(),
            }

        if not isinstance(data, dict):
            data = {}

        if not isinstance(data.get("tools"), list):
            data["tools"] = []

        data.setdefault("schema_version", "1.0")
        data.setdefault("updated_at", self._now())

        return data

    def _write_data(self, data: dict[str, Any]) -> None:
        data["updated_at"] = self._now()

        temporary_file = self.registry_file.with_suffix(
            self.registry_file.suffix + ".tmp"
        )

        with temporary_file.open("w", encoding="utf-8") as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        temporary_file.replace(self.registry_file)

    # =====================================================
    # Read
    # =====================================================

    def list_tools(
        self,
        *,
        category: str | None = None,
        status: str | None = "active",
        approval_status: str | None = "approved",
        test_status: str | None = None,
        reusable_only: bool = False,
    ) -> list[dict[str, Any]]:
        tools = self._read_data()["tools"]
        results: list[dict[str, Any]] = []

        normalized_category = self._normalize(category)

        for tool in tools:
            if normalized_category:
                saved_category = self._normalize(tool.get("category", ""))
                if normalized_category != saved_category:
                    continue

            if status and tool.get("status") != status:
                continue

            if (
                approval_status
                and tool.get("approval_status") != approval_status
            ):
                continue

            if test_status and tool.get("test_status") != test_status:
                continue

            if reusable_only and not bool(tool.get("reusable", False)):
                continue

            results.append(dict(tool))

        return results

    def get_tool_by_id(self, tool_id: str) -> dict[str, Any] | None:
        normalized_tool_id = self._normalize_identifier(tool_id)

        for tool in self._read_data()["tools"]:
            if self._normalize_identifier(tool.get("tool_id", "")) == normalized_tool_id:
                return dict(tool)

        return None

    def require_tool(self, tool_id: str) -> dict[str, Any]:
        tool = self.get_tool_by_id(tool_id)

        if tool is None:
            raise ToolNotFoundError(
                f"Tool Registry에 Tool이 없습니다: {tool_id}"
            )

        return tool

    def find_tool(
        self,
        *,
        tool_id: str | None = None,
        name: str | None = None,
        category: str | None = None,
        entrypoint: str | None = None,
        status: str | None = "active",
        approval_status: str | None = "approved",
        test_status: str | None = "passed",
        reusable_only: bool = True,
    ) -> dict[str, Any] | None:
        """
        Search for an existing reusable Tool.

        Search priority:
        1. tool_id
        2. exact entrypoint
        3. name/category match
        """

        if tool_id:
            tool = self.get_tool_by_id(tool_id)

            if tool and self._matches_filters(
                tool,
                status=status,
                approval_status=approval_status,
                test_status=test_status,
                reusable_only=reusable_only,
            ):
                return tool

            return None

        normalized_name = self._normalize(name)
        normalized_category = self._normalize(category)
        normalized_entrypoint = self._normalize_entrypoint(entrypoint)

        for tool in self._read_data()["tools"]:
            if not self._matches_filters(
                tool,
                status=status,
                approval_status=approval_status,
                test_status=test_status,
                reusable_only=reusable_only,
            ):
                continue

            if normalized_entrypoint:
                saved_entrypoint = self._normalize_entrypoint(
                    tool.get("entrypoint", "")
                )
                if normalized_entrypoint != saved_entrypoint:
                    continue

            if normalized_name:
                saved_name = self._normalize(tool.get("name", ""))
                saved_description = self._normalize(
                    tool.get("description", "")
                )

                if (
                    normalized_name not in saved_name
                    and normalized_name not in saved_description
                ):
                    continue

            if normalized_category:
                saved_category = self._normalize(
                    tool.get("category", "")
                )
                if normalized_category != saved_category:
                    continue

            return dict(tool)

        return None

    def search_tools(
        self,
        query: str,
        *,
        category: str | None = None,
        include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Search Tool name, category, description, entrypoint and tags.
        """

        normalized_query = self._normalize(query)
        normalized_category = self._normalize(category)

        if not normalized_query:
            return self.list_tools(
                category=category,
                status=None if include_inactive else "active",
                approval_status=None,
            )

        results: list[tuple[int, dict[str, Any]]] = []

        for tool in self._read_data()["tools"]:
            if not include_inactive and tool.get("status") != "active":
                continue

            if normalized_category:
                saved_category = self._normalize(
                    tool.get("category", "")
                )
                if saved_category != normalized_category:
                    continue

            metadata = tool.get("metadata") or {}
            tags = metadata.get("tags") or []

            search_fields = {
                "tool_id": self._normalize(tool.get("tool_id", "")),
                "name": self._normalize(tool.get("name", "")),
                "category": self._normalize(tool.get("category", "")),
                "description": self._normalize(
                    tool.get("description", "")
                ),
                "entrypoint": self._normalize(
                    tool.get("entrypoint", "")
                ),
                "tags": self._normalize(" ".join(map(str, tags))),
            }

            score = 0

            if normalized_query == search_fields["tool_id"]:
                score += 100
            if normalized_query == search_fields["name"]:
                score += 80
            if normalized_query in search_fields["name"]:
                score += 50
            if normalized_query in search_fields["category"]:
                score += 30
            if normalized_query in search_fields["description"]:
                score += 20
            if normalized_query in search_fields["entrypoint"]:
                score += 15
            if normalized_query in search_fields["tags"]:
                score += 10

            if score:
                results.append((score, dict(tool)))

        results.sort(
            key=lambda item: (
                item[0],
                self._version_key(item[1].get("version", "0.0.0")),
                item[1].get("updated_at", ""),
            ),
            reverse=True,
        )

        return [tool for _, tool in results]

    def tool_exists(
        self,
        *,
        tool_id: str | None = None,
        name: str | None = None,
        category: str | None = None,
        entrypoint: str | None = None,
        active_only: bool = False,
    ) -> bool:
        if tool_id and self.get_tool_by_id(tool_id):
            return True

        return (
            self.find_tool(
                name=name,
                category=category,
                entrypoint=entrypoint,
                status="active" if active_only else None,
                approval_status=None,
                test_status=None,
                reusable_only=False,
            )
            is not None
        )

    # =====================================================
    # Register
    # =====================================================

    def register_tool(
        self,
        record: ToolRecord,
        *,
        require_approval: bool = True,
        require_test_passed: bool = True,
    ) -> dict[str, Any]:
        """
        Register a Tool after validation.

        A Tool must normally be:
        - owner approved
        - automatically tested
        - reusable
        """

        tool_data = record.to_dict()
        self._prepare_tool_data(tool_data)
        self._validate_tool_data(
            tool_data,
            require_approval=require_approval,
            require_test_passed=require_test_passed,
        )

        data = self._read_data()
        tools = data["tools"]

        existing_by_id = self.get_tool_by_id(tool_data["tool_id"])

        if existing_by_id:
            return {
                "created": False,
                "reason": "same_tool_id_exists",
                "tool": existing_by_id,
            }

        existing_by_entrypoint = self.find_tool(
            entrypoint=tool_data["entrypoint"],
            status=None,
            approval_status=None,
            test_status=None,
            reusable_only=False,
        )

        if existing_by_entrypoint:
            return {
                "created": False,
                "reason": "same_entrypoint_exists",
                "tool": existing_by_entrypoint,
            }

        existing_by_name = self.find_tool(
            name=tool_data["name"],
            category=tool_data["category"],
            status=None,
            approval_status=None,
            test_status=None,
            reusable_only=False,
        )

        if existing_by_name:
            return {
                "created": False,
                "reason": "same_tool_exists",
                "tool": existing_by_name,
            }

        tools.append(tool_data)
        self._write_data(data)

        return {
            "created": True,
            "reason": "registered",
            "tool": tool_data,
        }

    # =====================================================
    # Update
    # =====================================================

    def update_tool(
        self,
        tool_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        data = self._read_data()

        allowed_fields = {
            "name",
            "category",
            "description",
            "entrypoint",
            "version",
            "status",
            "reusable",
            "approval_status",
            "created_reason",
            "created_by_agent_id",
            "test_status",
            "test_command",
            "permissions",
            "metadata",
        }

        clean_updates = {
            key: value
            for key, value in updates.items()
            if key in allowed_fields
        }

        if not clean_updates:
            return {
                "updated": False,
                "reason": "no_allowed_updates",
                "tool": self.get_tool_by_id(tool_id),
            }

        for index, tool in enumerate(data["tools"]):
            if self._normalize_identifier(
                tool.get("tool_id", "")
            ) != self._normalize_identifier(tool_id):
                continue

            updated_tool = dict(tool)
            updated_tool.update(clean_updates)
            self._prepare_tool_data(
                updated_tool,
                preserve_created_at=True,
            )
            self._validate_tool_data(
                updated_tool,
                require_approval=False,
                require_test_passed=False,
            )

            data["tools"][index] = updated_tool
            self._write_data(data)

            return {
                "updated": True,
                "reason": "updated",
                "tool": updated_tool,
            }

        raise ToolNotFoundError(
            f"수정할 Tool이 없습니다: {tool_id}"
        )

    def set_status(
        self,
        tool_id: str,
        status: str,
    ) -> dict[str, Any]:
        if status not in self.VALID_STATUSES:
            raise ToolValidationError(
                f"허용되지 않은 Tool 상태입니다: {status}"
            )

        return self.update_tool(
            tool_id,
            {"status": status},
        )

    def set_approval_status(
        self,
        tool_id: str,
        approval_status: str,
    ) -> dict[str, Any]:
        if approval_status not in self.VALID_APPROVAL_STATUSES:
            raise ToolValidationError(
                f"허용되지 않은 승인 상태입니다: {approval_status}"
            )

        return self.update_tool(
            tool_id,
            {"approval_status": approval_status},
        )

    def set_test_result(
        self,
        tool_id: str,
        *,
        passed: bool,
        test_command: str = "",
        test_detail: str = "",
    ) -> dict[str, Any]:
        tool = self.require_tool(tool_id)
        metadata = dict(tool.get("metadata") or {})
        metadata["last_test_detail"] = test_detail
        metadata["last_tested_at"] = self._now()

        return self.update_tool(
            tool_id,
            {
                "test_status": "passed" if passed else "failed",
                "test_command": test_command,
                "metadata": metadata,
                "status": "active" if passed else "failed",
            },
        )

    def register_new_version(
        self,
        tool_id: str,
        *,
        version: str,
        entrypoint: str | None = None,
        description: str | None = None,
        test_status: str = "passed",
        test_command: str = "",
        created_reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = self.require_tool(tool_id)

        if self._version_key(version) <= self._version_key(
            current.get("version", "0.0.0")
        ):
            raise ToolValidationError(
                "새 버전은 현재 버전보다 높아야 합니다."
            )

        updates: dict[str, Any] = {
            "version": version,
            "test_status": test_status,
            "test_command": test_command,
            "created_reason": created_reason
            or current.get("created_reason", ""),
            "status": "active" if test_status == "passed" else "testing",
        }

        if entrypoint is not None:
            updates["entrypoint"] = entrypoint

        if description is not None:
            updates["description"] = description

        merged_metadata = dict(current.get("metadata") or {})
        merged_metadata.update(metadata or {})
        merged_metadata["previous_version"] = current.get("version")
        merged_metadata["version_updated_at"] = self._now()
        updates["metadata"] = merged_metadata

        return self.update_tool(tool_id, updates)

    # =====================================================
    # Delete / Export
    # =====================================================

    def remove_tool(
        self,
        tool_id: str,
        *,
        hard_delete: bool = False,
    ) -> dict[str, Any]:
        if not hard_delete:
            result = self.set_status(tool_id, "inactive")
            return {
                "removed": True,
                "hard_delete": False,
                "tool": result["tool"],
            }

        data = self._read_data()
        before = len(data["tools"])

        data["tools"] = [
            tool
            for tool in data["tools"]
            if self._normalize_identifier(
                tool.get("tool_id", "")
            ) != self._normalize_identifier(tool_id)
        ]

        if len(data["tools"]) == before:
            raise ToolNotFoundError(
                f"삭제할 Tool이 없습니다: {tool_id}"
            )

        self._write_data(data)

        return {
            "removed": True,
            "hard_delete": True,
            "tool_id": tool_id,
        }

    def export_registry(self) -> dict[str, Any]:
        return self._read_data()

    # =====================================================
    # Validation
    # =====================================================

    def _prepare_tool_data(
        self,
        tool_data: dict[str, Any],
        *,
        preserve_created_at: bool = False,
    ) -> None:
        now = self._now()

        tool_data["tool_id"] = self._normalize_identifier(
            tool_data.get("tool_id", "")
        )
        tool_data["name"] = str(tool_data.get("name", "")).strip()
        tool_data["category"] = str(
            tool_data.get("category", "")
        ).strip()
        tool_data["description"] = str(
            tool_data.get("description", "")
        ).strip()
        tool_data["entrypoint"] = str(
            tool_data.get("entrypoint", "")
        ).strip()
        tool_data["version"] = str(
            tool_data.get("version", "1.0.0")
        ).strip()
        tool_data["status"] = str(
            tool_data.get("status", "active")
        ).strip()
        tool_data["approval_status"] = str(
            tool_data.get("approval_status", "pending")
        ).strip()
        tool_data["test_status"] = str(
            tool_data.get("test_status", "not_tested")
        ).strip()
        tool_data["reusable"] = bool(
            tool_data.get("reusable", True)
        )
        tool_data["permissions"] = list(
            tool_data.get("permissions") or []
        )
        tool_data["metadata"] = dict(
            tool_data.get("metadata") or {}
        )

        if not preserve_created_at or not tool_data.get("created_at"):
            tool_data["created_at"] = now

        tool_data["updated_at"] = now

    def _validate_tool_data(
        self,
        tool_data: dict[str, Any],
        *,
        require_approval: bool,
        require_test_passed: bool,
    ) -> None:
        required_fields = {
            "tool_id": tool_data.get("tool_id"),
            "name": tool_data.get("name"),
            "category": tool_data.get("category"),
            "description": tool_data.get("description"),
            "entrypoint": tool_data.get("entrypoint"),
            "version": tool_data.get("version"),
        }

        missing = [
            field
            for field, value in required_fields.items()
            if not str(value or "").strip()
        ]

        if missing:
            raise ToolValidationError(
                "필수 Tool 정보가 없습니다: "
                + ", ".join(missing)
            )

        if not re.fullmatch(
            r"[a-z][a-z0-9_]{2,99}",
            str(tool_data["tool_id"]),
        ):
            raise ToolValidationError(
                "tool_id는 영문 소문자로 시작하고 "
                "영문 소문자, 숫자, 밑줄만 사용할 수 있습니다."
            )

        if tool_data["status"] not in self.VALID_STATUSES:
            raise ToolValidationError(
                f"허용되지 않은 Tool 상태입니다: {tool_data['status']}"
            )

        if (
            tool_data["approval_status"]
            not in self.VALID_APPROVAL_STATUSES
        ):
            raise ToolValidationError(
                "허용되지 않은 승인 상태입니다: "
                f"{tool_data['approval_status']}"
            )

        if tool_data["test_status"] not in self.VALID_TEST_STATUSES:
            raise ToolValidationError(
                "허용되지 않은 테스트 상태입니다: "
                f"{tool_data['test_status']}"
            )

        if not re.fullmatch(
            r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?",
            str(tool_data["version"]),
        ):
            raise ToolValidationError(
                "version은 1.0.0 형식이어야 합니다."
            )

        if require_approval and tool_data["approval_status"] != "approved":
            raise ToolValidationError(
                "대표 승인 완료 전에는 Tool Registry에 "
                "정식 등록할 수 없습니다."
            )

        if require_test_passed and tool_data["test_status"] != "passed":
            raise ToolValidationError(
                "자동 테스트 통과 전에는 Tool Registry에 "
                "정식 등록할 수 없습니다."
            )

    def _matches_filters(
        self,
        tool: dict[str, Any],
        *,
        status: str | None,
        approval_status: str | None,
        test_status: str | None,
        reusable_only: bool,
    ) -> bool:
        if status and tool.get("status") != status:
            return False

        if (
            approval_status
            and tool.get("approval_status") != approval_status
        ):
            return False

        if test_status and tool.get("test_status") != test_status:
            return False

        if reusable_only and not bool(tool.get("reusable", False)):
            return False

        return True

    # =====================================================
    # Helpers
    # =====================================================

    @staticmethod
    def _normalize(value: Any) -> str:
        return re.sub(
            r"\s+",
            " ",
            str(value or "").strip().lower(),
        )

    @staticmethod
    def _normalize_identifier(value: Any) -> str:
        text = str(value or "").strip().lower()
        text = re.sub(r"[^a-z0-9_]+", "_", text)
        return re.sub(r"_+", "_", text).strip("_")

    @staticmethod
    def _normalize_entrypoint(value: Any) -> str:
        return str(value or "").strip().replace("\\", "/").lower()

    @staticmethod
    def _version_key(version: Any) -> tuple[int, int, int, str]:
        text = str(version or "0.0.0")
        match = re.match(
            r"^(\d+)\.(\d+)\.(\d+)(.*)$",
            text,
        )

        if not match:
            return (0, 0, 0, text)

        return (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            match.group(4),
        )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


# =========================================================
# Shared Registry Instance
# =========================================================

tool_registry = ToolRegistry()


# Backward-friendly alias
registry = tool_registry


if __name__ == "__main__":
    print(
        json.dumps(
            tool_registry.export_registry(),
            ensure_ascii=False,
            indent=2,
        )
    )
