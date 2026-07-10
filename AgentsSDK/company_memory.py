from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


# =========================================================
# 저장 위치
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "company_assets"
MEMORY_FILE = ASSETS_DIR / "company_memory.json"


# =========================================================
# 예외
# =========================================================

class CompanyMemoryError(Exception):
    """Company Memory 처리 중 발생하는 기본 예외."""


class MemoryValidationError(CompanyMemoryError):
    """Memory 요청값이 올바르지 않을 때 발생한다."""


class MemoryNotFoundError(CompanyMemoryError):
    """요청한 Memory를 찾지 못했을 때 발생한다."""


# =========================================================
# Memory 자산 구조
# =========================================================

@dataclass
class MemoryRecord:
    memory_id: str
    category: str
    title: str
    content: str
    source: str
    source_agent_id: str | None
    project_id: str | None
    related_agent_ids: list[str]
    tags: list[str]
    importance: int
    status: str = "active"
    reusable: bool = True
    approved: bool = True
    created_at: str = ""
    updated_at: str = ""


# =========================================================
# Company Memory
# =========================================================

class CompanyMemory:
    """
    Business AI OS의 회사 공용 기억 저장소.

    저장 대상:
    1. 회사헌법
    2. 운영원칙
    3. 대표 지시
    4. 프로젝트 상태
    5. Agent 업무 결과
    6. 승인 및 반려 기록
    7. 중요 의사결정
    8. 다음 수행 업무
    9. 기존 회사 자산 검색용 요약

    설계 원칙:
    - 모든 Memory는 JSON 파일에 영구 저장한다.
    - 삭제보다 비활성화를 우선한다.
    - 중요도는 1~5 범위로 관리한다.
    - 승인되지 않은 Memory는 기본 검색에서 제외할 수 있다.
    - 동일 category/title/content의 중복 저장을 방지한다.
    """

    ALLOWED_CATEGORIES = {
        "constitution",
        "operating_policy",
        "owner_instruction",
        "project_status",
        "agent_result",
        "approval",
        "rejection",
        "decision",
        "next_action",
        "company_asset",
        "workflow",
        "report",
        "general",
    }

    ALLOWED_STATUSES = {
        "active",
        "inactive",
        "archived",
    }

    def __init__(
        self,
        memory_file: Path = MEMORY_FILE,
    ) -> None:
        self.memory_file = memory_file
        self._ensure_memory_file()

    # =====================================================
    # 파일 관리
    # =====================================================

    def _ensure_memory_file(self) -> None:
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

        if not self.memory_file.exists():
            self._write_data(
                {
                    "version": "2.0",
                    "memories": [],
                }
            )

    def _read_data(self) -> dict[str, Any]:
        try:
            with self.memory_file.open("r", encoding="utf-8") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                return {
                    "version": "2.0",
                    "memories": [],
                }

            if not isinstance(data.get("memories"), list):
                data["memories"] = []

            if not isinstance(data.get("version"), str):
                data["version"] = "2.0"

            return data

        except (json.JSONDecodeError, OSError):
            return {
                "version": "2.0",
                "memories": [],
            }

    def _write_data(self, data: dict[str, Any]) -> None:
        try:
            with self.memory_file.open("w", encoding="utf-8") as file:
                json.dump(
                    data,
                    file,
                    ensure_ascii=False,
                    indent=2,
                )
        except OSError as exc:
            raise CompanyMemoryError(
                f"Company Memory 저장에 실패했습니다: {self.memory_file}"
            ) from exc

    # =====================================================
    # 생성 및 저장
    # =====================================================

    def add_memory(
        self,
        *,
        category: str,
        title: str,
        content: str,
        source: str,
        source_agent_id: str | None = None,
        project_id: str | None = None,
        related_agent_ids: list[str] | None = None,
        tags: list[str] | None = None,
        importance: int = 3,
        reusable: bool = True,
        approved: bool = True,
        prevent_duplicate: bool = True,
    ) -> dict[str, Any]:
        """
        새로운 회사 Memory를 저장한다.

        동일 category/title/content가 있으면 기본적으로 중복 저장하지 않는다.
        """

        cleaned_category = self._clean_text(category).lower()
        cleaned_title = self._clean_text(title)
        cleaned_content = self._clean_multiline(content)
        cleaned_source = self._clean_text(source)
        cleaned_source_agent_id = self._clean_optional_text(source_agent_id)
        cleaned_project_id = self._clean_optional_text(project_id)
        cleaned_related_agents = self._clean_string_list(
            related_agent_ids or []
        )
        cleaned_tags = self._clean_string_list(tags or [])

        self._validate_memory_values(
            category=cleaned_category,
            title=cleaned_title,
            content=cleaned_content,
            source=cleaned_source,
            importance=importance,
        )

        if prevent_duplicate:
            existing = self.find_duplicate(
                category=cleaned_category,
                title=cleaned_title,
                content=cleaned_content,
            )

            if existing is not None:
                return {
                    "created": False,
                    "reason": "duplicate_memory_exists",
                    "memory": existing,
                }

        now = self._utc_now()

        record = MemoryRecord(
            memory_id=self._generate_memory_id(),
            category=cleaned_category,
            title=cleaned_title,
            content=cleaned_content,
            source=cleaned_source,
            source_agent_id=cleaned_source_agent_id,
            project_id=cleaned_project_id,
            related_agent_ids=cleaned_related_agents,
            tags=cleaned_tags,
            importance=importance,
            status="active",
            reusable=reusable,
            approved=approved,
            created_at=now,
            updated_at=now,
        )

        data = self._read_data()
        memory_data = asdict(record)
        data["memories"].append(memory_data)
        self._write_data(data)

        return {
            "created": True,
            "reason": "memory_registered",
            "memory": memory_data,
        }

    def remember_owner_instruction(
        self,
        *,
        title: str,
        content: str,
        project_id: str | None = None,
        importance: int = 5,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        대표의 지시를 저장한다.
        """

        return self.add_memory(
            category="owner_instruction",
            title=title,
            content=content,
            source="owner",
            project_id=project_id,
            tags=tags,
            importance=importance,
            reusable=True,
            approved=True,
        )

    def remember_agent_result(
        self,
        *,
        title: str,
        content: str,
        source_agent_id: str,
        project_id: str | None = None,
        related_agent_ids: list[str] | None = None,
        importance: int = 3,
        approved: bool = True,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Agent의 업무 결과를 저장한다.
        """

        return self.add_memory(
            category="agent_result",
            title=title,
            content=content,
            source="agent",
            source_agent_id=source_agent_id,
            project_id=project_id,
            related_agent_ids=related_agent_ids,
            tags=tags,
            importance=importance,
            reusable=True,
            approved=approved,
        )

    def remember_project_status(
        self,
        *,
        project_id: str,
        title: str,
        content: str,
        source_agent_id: str | None = None,
        importance: int = 4,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        프로젝트 진행 상태를 저장한다.
        """

        return self.add_memory(
            category="project_status",
            title=title,
            content=content,
            source="project",
            source_agent_id=source_agent_id,
            project_id=project_id,
            tags=tags,
            importance=importance,
            reusable=True,
            approved=True,
        )

    def remember_decision(
        self,
        *,
        title: str,
        content: str,
        source: str,
        source_agent_id: str | None = None,
        project_id: str | None = None,
        importance: int = 5,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        중요 의사결정을 저장한다.
        """

        return self.add_memory(
            category="decision",
            title=title,
            content=content,
            source=source,
            source_agent_id=source_agent_id,
            project_id=project_id,
            tags=tags,
            importance=importance,
            reusable=True,
            approved=True,
        )

    def remember_approval(
        self,
        *,
        title: str,
        content: str,
        project_id: str | None = None,
        source_agent_id: str | None = None,
        approved: bool = True,
        importance: int = 5,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        승인 또는 반려 결과를 저장한다.
        """

        category = "approval" if approved else "rejection"

        return self.add_memory(
            category=category,
            title=title,
            content=content,
            source="owner",
            source_agent_id=source_agent_id,
            project_id=project_id,
            tags=tags,
            importance=importance,
            reusable=True,
            approved=True,
        )

    def remember_next_action(
        self,
        *,
        title: str,
        content: str,
        source_agent_id: str | None = None,
        project_id: str | None = None,
        importance: int = 4,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        다음 수행 업무를 저장한다.
        """

        return self.add_memory(
            category="next_action",
            title=title,
            content=content,
            source="system",
            source_agent_id=source_agent_id,
            project_id=project_id,
            tags=tags,
            importance=importance,
            reusable=True,
            approved=True,
        )

    # =====================================================
    # 조회
    # =====================================================

    def get_memory_by_id(
        self,
        memory_id: str,
    ) -> dict[str, Any] | None:
        """
        memory_id로 Memory를 조회한다.
        """

        for memory in self._read_data()["memories"]:
            if memory.get("memory_id") == memory_id:
                return memory

        return None

    def list_memories(
        self,
        *,
        category: str | None = None,
        status: str | None = "active",
        source_agent_id: str | None = None,
        project_id: str | None = None,
        approved_only: bool = False,
        reusable_only: bool = False,
        min_importance: int | None = None,
        limit: int | None = None,
        newest_first: bool = True,
    ) -> list[dict[str, Any]]:
        """
        조건에 맞는 Memory 목록을 반환한다.
        """

        memories = self._read_data()["memories"]
        results: list[dict[str, Any]] = []

        cleaned_category = (
            self._clean_text(category).lower()
            if category is not None
            else None
        )

        for memory in memories:
            if (
                cleaned_category is not None
                and memory.get("category") != cleaned_category
            ):
                continue

            if status and memory.get("status") != status:
                continue

            if (
                source_agent_id is not None
                and memory.get("source_agent_id") != source_agent_id
            ):
                continue

            if (
                project_id is not None
                and memory.get("project_id") != project_id
            ):
                continue

            if approved_only and not bool(memory.get("approved")):
                continue

            if reusable_only and not bool(memory.get("reusable")):
                continue

            if (
                min_importance is not None
                and int(memory.get("importance", 0)) < min_importance
            ):
                continue

            results.append(memory)

        results.sort(
            key=lambda item: str(item.get("updated_at", "")),
            reverse=newest_first,
        )

        if limit is not None:
            if limit < 1:
                return []

            results = results[:limit]

        return results

    def search_memories(
        self,
        query: str,
        *,
        categories: list[str] | None = None,
        project_id: str | None = None,
        source_agent_id: str | None = None,
        approved_only: bool = True,
        reusable_only: bool = True,
        min_importance: int = 1,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        제목, 본문, 태그, 출처를 기준으로 Memory를 검색한다.

        검색 점수:
        - 제목 일치: 높은 점수
        - 태그 일치: 높은 점수
        - 본문 일치: 기본 점수
        - 중요도: 가산점
        """

        cleaned_query = self._normalize_search_text(query)

        if not cleaned_query:
            raise MemoryValidationError(
                "검색어는 비어 있을 수 없습니다."
            )

        query_tokens = self._tokenize(query)
        allowed_categories = {
            self._clean_text(category).lower()
            for category in (categories or [])
            if self._clean_text(category)
        }

        candidates = self.list_memories(
            status="active",
            source_agent_id=source_agent_id,
            project_id=project_id,
            approved_only=approved_only,
            reusable_only=reusable_only,
            min_importance=min_importance,
            newest_first=True,
        )

        scored_results: list[tuple[int, dict[str, Any]]] = []

        for memory in candidates:
            if (
                allowed_categories
                and memory.get("category") not in allowed_categories
            ):
                continue

            score = self._calculate_search_score(
                memory=memory,
                normalized_query=cleaned_query,
                query_tokens=query_tokens,
            )

            if score <= 0:
                continue

            result = dict(memory)
            result["search_score"] = score
            scored_results.append((score, result))

        scored_results.sort(
            key=lambda item: (
                item[0],
                int(item[1].get("importance", 0)),
                str(item[1].get("updated_at", "")),
            ),
            reverse=True,
        )

        return [
            result
            for _, result in scored_results[:max(limit, 0)]
        ]

    def find_duplicate(
        self,
        *,
        category: str,
        title: str,
        content: str,
    ) -> dict[str, Any] | None:
        """
        동일 category/title/content의 기존 Memory를 찾는다.
        """

        normalized_category = self._clean_text(category).lower()
        normalized_title = self._normalize_search_text(title)
        normalized_content = self._normalize_search_text(content)

        for memory in self._read_data()["memories"]:
            if memory.get("category") != normalized_category:
                continue

            if (
                self._normalize_search_text(
                    str(memory.get("title", ""))
                )
                != normalized_title
            ):
                continue

            if (
                self._normalize_search_text(
                    str(memory.get("content", ""))
                )
                != normalized_content
            ):
                continue

            return memory

        return None

    def get_project_context(
        self,
        project_id: str,
        *,
        limit: int = 30,
    ) -> dict[str, Any]:
        """
        특정 프로젝트에 관련된 Memory를 카테고리별로 묶어 반환한다.
        """

        memories = self.list_memories(
            project_id=project_id,
            status="active",
            approved_only=True,
            limit=limit,
        )

        grouped: dict[str, list[dict[str, Any]]] = {}

        for memory in memories:
            category = str(memory.get("category", "general"))
            grouped.setdefault(category, []).append(memory)

        return {
            "project_id": project_id,
            "memory_count": len(memories),
            "categories": grouped,
            "memories": memories,
        }

    def get_agent_context(
        self,
        agent_id: str,
        *,
        limit: int = 30,
    ) -> dict[str, Any]:
        """
        특정 Agent가 생성했거나 관련된 Memory를 반환한다.
        """

        results: list[dict[str, Any]] = []

        for memory in self.list_memories(
            status="active",
            approved_only=True,
            newest_first=True,
        ):
            related_agent_ids = memory.get("related_agent_ids", [])

            if (
                memory.get("source_agent_id") == agent_id
                or agent_id in related_agent_ids
            ):
                results.append(memory)

            if len(results) >= limit:
                break

        return {
            "agent_id": agent_id,
            "memory_count": len(results),
            "memories": results,
        }

    def build_context_text(
        self,
        *,
        query: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        categories: list[str] | None = None,
        limit: int = 15,
    ) -> str:
        """
        Agent instructions 또는 Runner input에 넣을 수 있는
        텍스트 형태의 회사 Memory Context를 생성한다.
        """

        if query:
            memories = self.search_memories(
                query,
                categories=categories,
                project_id=project_id,
                source_agent_id=None,
                approved_only=True,
                reusable_only=True,
                limit=limit,
            )
        else:
            memories = self.list_memories(
                project_id=project_id,
                approved_only=True,
                reusable_only=True,
                limit=limit,
            )

        if agent_id:
            memories = [
                memory
                for memory in memories
                if (
                    memory.get("source_agent_id") == agent_id
                    or agent_id in memory.get("related_agent_ids", [])
                    or memory.get("category")
                    in {
                        "constitution",
                        "operating_policy",
                        "owner_instruction",
                        "decision",
                    }
                )
            ]

        if not memories:
            return "검색된 회사 Memory가 없습니다."

        lines: list[str] = [
            "[Business AI OS Company Memory]",
        ]

        for index, memory in enumerate(memories, start=1):
            lines.extend(
                [
                    "",
                    f"{index}. [{memory.get('category')}] "
                    f"{memory.get('title')}",
                    f"중요도: {memory.get('importance')}",
                    f"내용: {memory.get('content')}",
                ]
            )

            if memory.get("project_id"):
                lines.append(
                    f"프로젝트: {memory.get('project_id')}"
                )

            if memory.get("source_agent_id"):
                lines.append(
                    f"작성 Agent: {memory.get('source_agent_id')}"
                )

        return "\n".join(lines)

    # =====================================================
    # 수정
    # =====================================================

    def update_memory(
        self,
        memory_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """
        기존 Memory를 수정한다.
        memory_id와 created_at은 변경할 수 없다.
        """

        if not isinstance(updates, dict):
            raise MemoryValidationError(
                "updates는 dict 형식이어야 합니다."
            )

        allowed_fields = {
            "category",
            "title",
            "content",
            "source",
            "source_agent_id",
            "project_id",
            "related_agent_ids",
            "tags",
            "importance",
            "status",
            "reusable",
            "approved",
        }

        safe_updates = {
            key: value
            for key, value in updates.items()
            if key in allowed_fields
        }

        if not safe_updates:
            return {
                "updated": False,
                "reason": "no_valid_updates",
                "memory": self.get_memory_by_id(memory_id),
            }

        data = self._read_data()

        for memory in data["memories"]:
            if memory.get("memory_id") != memory_id:
                continue

            cleaned_updates = self._prepare_updates(
                current_memory=memory,
                updates=safe_updates,
            )

            memory.update(cleaned_updates)
            memory["updated_at"] = self._utc_now()
            self._write_data(data)

            return {
                "updated": True,
                "reason": "memory_updated",
                "memory": memory,
            }

        return {
            "updated": False,
            "reason": "memory_not_found",
            "memory": None,
        }

    def approve_memory(
        self,
        memory_id: str,
    ) -> dict[str, Any]:
        """
        Memory를 승인 상태로 변경한다.
        """

        return self.update_memory(
            memory_id,
            {
                "approved": True,
            },
        )

    def reject_memory(
        self,
        memory_id: str,
    ) -> dict[str, Any]:
        """
        Memory의 승인 상태를 해제한다.
        """

        return self.update_memory(
            memory_id,
            {
                "approved": False,
            },
        )

    def deactivate_memory(
        self,
        memory_id: str,
    ) -> dict[str, Any]:
        """
        Memory를 비활성화한다.
        """

        return self.update_memory(
            memory_id,
            {
                "status": "inactive",
            },
        )

    def activate_memory(
        self,
        memory_id: str,
    ) -> dict[str, Any]:
        """
        Memory를 다시 활성화한다.
        """

        return self.update_memory(
            memory_id,
            {
                "status": "active",
            },
        )

    def archive_memory(
        self,
        memory_id: str,
    ) -> dict[str, Any]:
        """
        Memory를 보관 상태로 변경한다.
        """

        return self.update_memory(
            memory_id,
            {
                "status": "archived",
            },
        )

    # =====================================================
    # 삭제 및 정리
    # =====================================================

    def delete_memory(
        self,
        memory_id: str,
    ) -> dict[str, Any]:
        """
        Memory를 실제 삭제한다.

        운영에서는 deactivate_memory() 또는 archive_memory()를 우선 사용한다.
        """

        data = self._read_data()
        original_count = len(data["memories"])

        data["memories"] = [
            memory
            for memory in data["memories"]
            if memory.get("memory_id") != memory_id
        ]

        if len(data["memories"]) == original_count:
            return {
                "deleted": False,
                "reason": "memory_not_found",
            }

        self._write_data(data)

        return {
            "deleted": True,
            "reason": "memory_deleted",
        }

    def remove_project_memories(
        self,
        project_id: str,
        *,
        delete: bool = False,
    ) -> dict[str, Any]:
        """
        특정 프로젝트의 Memory를 비활성화하거나 삭제한다.
        """

        data = self._read_data()
        affected = 0
        now = self._utc_now()

        if delete:
            retained: list[dict[str, Any]] = []

            for memory in data["memories"]:
                if memory.get("project_id") == project_id:
                    affected += 1
                    continue

                retained.append(memory)

            data["memories"] = retained

        else:
            for memory in data["memories"]:
                if (
                    memory.get("project_id") == project_id
                    and memory.get("status") == "active"
                ):
                    memory["status"] = "inactive"
                    memory["updated_at"] = now
                    affected += 1

        self._write_data(data)

        return {
            "success": True,
            "affected": affected,
            "mode": "delete" if delete else "deactivate",
            "project_id": project_id,
        }

    def cleanup_duplicates(self) -> dict[str, Any]:
        """
        완전히 동일한 category/title/content 중복 Memory를 정리한다.

        가장 최근 Memory 하나만 유지한다.
        """

        data = self._read_data()
        memories = sorted(
            data["memories"],
            key=lambda item: str(item.get("updated_at", "")),
            reverse=True,
        )

        seen: set[tuple[str, str, str]] = set()
        unique_memories: list[dict[str, Any]] = []
        removed_ids: list[str] = []

        for memory in memories:
            key = (
                str(memory.get("category", "")),
                self._normalize_search_text(
                    str(memory.get("title", ""))
                ),
                self._normalize_search_text(
                    str(memory.get("content", ""))
                ),
            )

            if key in seen:
                removed_ids.append(
                    str(memory.get("memory_id", ""))
                )
                continue

            seen.add(key)
            unique_memories.append(memory)

        unique_memories.sort(
            key=lambda item: str(item.get("created_at", ""))
        )
        data["memories"] = unique_memories
        self._write_data(data)

        return {
            "success": True,
            "removed_count": len(removed_ids),
            "removed_memory_ids": removed_ids,
        }

    # =====================================================
    # 통계 및 검증
    # =====================================================

    def get_statistics(self) -> dict[str, Any]:
        """
        Company Memory 저장소 통계를 반환한다.
        """

        memories = self._read_data()["memories"]
        category_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        project_counts: dict[str, int] = {}

        approved_count = 0
        reusable_count = 0

        for memory in memories:
            category = str(memory.get("category", "general"))
            status = str(memory.get("status", "active"))
            project_id = memory.get("project_id")

            category_counts[category] = (
                category_counts.get(category, 0) + 1
            )
            status_counts[status] = status_counts.get(status, 0) + 1

            if project_id:
                project_key = str(project_id)
                project_counts[project_key] = (
                    project_counts.get(project_key, 0) + 1
                )

            if memory.get("approved"):
                approved_count += 1

            if memory.get("reusable"):
                reusable_count += 1

        return {
            "total": len(memories),
            "approved": approved_count,
            "reusable": reusable_count,
            "by_category": category_counts,
            "by_status": status_counts,
            "by_project": project_counts,
        }

    def validate_memory_store(self) -> dict[str, Any]:
        """
        전체 Memory 자산 구조를 검사한다.
        """

        errors: list[dict[str, Any]] = []
        memory_ids: set[str] = set()

        for index, memory in enumerate(
            self._read_data()["memories"]
        ):
            memory_id = str(memory.get("memory_id", ""))

            if not memory_id:
                errors.append(
                    {
                        "index": index,
                        "type": "missing_memory_id",
                    }
                )
            elif memory_id in memory_ids:
                errors.append(
                    {
                        "index": index,
                        "type": "duplicate_memory_id",
                        "memory_id": memory_id,
                    }
                )
            else:
                memory_ids.add(memory_id)

            category = str(memory.get("category", ""))

            if category not in self.ALLOWED_CATEGORIES:
                errors.append(
                    {
                        "index": index,
                        "type": "invalid_category",
                        "memory_id": memory_id,
                        "value": category,
                    }
                )

            status = str(memory.get("status", ""))

            if status not in self.ALLOWED_STATUSES:
                errors.append(
                    {
                        "index": index,
                        "type": "invalid_status",
                        "memory_id": memory_id,
                        "value": status,
                    }
                )

            importance = memory.get("importance")

            if (
                not isinstance(importance, int)
                or importance < 1
                or importance > 5
            ):
                errors.append(
                    {
                        "index": index,
                        "type": "invalid_importance",
                        "memory_id": memory_id,
                        "value": importance,
                    }
                )

            if not self._clean_text(
                str(memory.get("title", ""))
            ):
                errors.append(
                    {
                        "index": index,
                        "type": "missing_title",
                        "memory_id": memory_id,
                    }
                )

            if not self._clean_text(
                str(memory.get("content", ""))
            ):
                errors.append(
                    {
                        "index": index,
                        "type": "missing_content",
                        "memory_id": memory_id,
                    }
                )

        return {
            "valid": len(errors) == 0,
            "memory_count": len(memory_ids),
            "errors": errors,
        }

    # =====================================================
    # 내부 유틸리티
    # =====================================================

    def _prepare_updates(
        self,
        *,
        current_memory: dict[str, Any],
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        prepared = dict(updates)

        if "category" in prepared:
            prepared["category"] = self._clean_text(
                str(prepared["category"])
            ).lower()

        if "title" in prepared:
            prepared["title"] = self._clean_text(
                str(prepared["title"])
            )

        if "content" in prepared:
            prepared["content"] = self._clean_multiline(
                str(prepared["content"])
            )

        if "source" in prepared:
            prepared["source"] = self._clean_text(
                str(prepared["source"])
            )

        if "source_agent_id" in prepared:
            prepared["source_agent_id"] = self._clean_optional_text(
                prepared["source_agent_id"]
            )

        if "project_id" in prepared:
            prepared["project_id"] = self._clean_optional_text(
                prepared["project_id"]
            )

        if "related_agent_ids" in prepared:
            prepared["related_agent_ids"] = self._clean_string_list(
                prepared["related_agent_ids"]
            )

        if "tags" in prepared:
            prepared["tags"] = self._clean_string_list(
                prepared["tags"]
            )

        category = prepared.get(
            "category",
            current_memory.get("category"),
        )
        title = prepared.get(
            "title",
            current_memory.get("title"),
        )
        content = prepared.get(
            "content",
            current_memory.get("content"),
        )
        source = prepared.get(
            "source",
            current_memory.get("source"),
        )
        importance = prepared.get(
            "importance",
            current_memory.get("importance"),
        )

        self._validate_memory_values(
            category=str(category),
            title=str(title),
            content=str(content),
            source=str(source),
            importance=importance,
        )

        if "status" in prepared:
            status = str(prepared["status"])

            if status not in self.ALLOWED_STATUSES:
                raise MemoryValidationError(
                    f"지원하지 않는 status입니다: {status}"
                )

        if "reusable" in prepared:
            prepared["reusable"] = bool(
                prepared["reusable"]
            )

        if "approved" in prepared:
            prepared["approved"] = bool(
                prepared["approved"]
            )

        return prepared

    def _validate_memory_values(
        self,
        *,
        category: str,
        title: str,
        content: str,
        source: str,
        importance: int,
    ) -> None:
        if category not in self.ALLOWED_CATEGORIES:
            allowed = ", ".join(
                sorted(self.ALLOWED_CATEGORIES)
            )
            raise MemoryValidationError(
                f"지원하지 않는 category입니다: {category}. "
                f"허용값: {allowed}"
            )

        if not title:
            raise MemoryValidationError(
                "title은 비어 있을 수 없습니다."
            )

        if not content:
            raise MemoryValidationError(
                "content는 비어 있을 수 없습니다."
            )

        if not source:
            raise MemoryValidationError(
                "source는 비어 있을 수 없습니다."
            )

        if (
            not isinstance(importance, int)
            or importance < 1
            or importance > 5
        ):
            raise MemoryValidationError(
                "importance는 1~5 사이의 정수여야 합니다."
            )

    @staticmethod
    def _calculate_search_score(
        *,
        memory: dict[str, Any],
        normalized_query: str,
        query_tokens: list[str],
    ) -> int:
        title = CompanyMemory._normalize_search_text(
            str(memory.get("title", ""))
        )
        content = CompanyMemory._normalize_search_text(
            str(memory.get("content", ""))
        )
        source = CompanyMemory._normalize_search_text(
            str(memory.get("source", ""))
        )
        tags = [
            CompanyMemory._normalize_search_text(str(tag))
            for tag in memory.get("tags", [])
        ]

        score = 0

        if normalized_query == title:
            score += 100
        elif normalized_query in title:
            score += 60

        if normalized_query in content:
            score += 30

        if normalized_query in tags:
            score += 50

        if normalized_query in source:
            score += 10

        for token in query_tokens:
            if token in title:
                score += 12

            if token in content:
                score += 5

            if token in tags:
                score += 10

        score += int(memory.get("importance", 1)) * 2

        return score

    @staticmethod
    def _tokenize(value: str) -> list[str]:
        normalized = CompanyMemory._normalize_search_text(value)

        if not normalized:
            return []

        raw_tokens = re.split(
            r"[^0-9a-zA-Z가-힣_]+",
            normalized,
        )

        return [
            token
            for token in raw_tokens
            if len(token) >= 2
        ]

    @staticmethod
    def _clean_text(value: Any) -> str:
        if value is None:
            return ""

        return " ".join(str(value).strip().split())

    @staticmethod
    def _clean_multiline(value: Any) -> str:
        if value is None:
            return ""

        lines = [
            line.rstrip()
            for line in str(value).strip().splitlines()
        ]

        return "\n".join(lines).strip()

    @staticmethod
    def _clean_optional_text(
        value: Any,
    ) -> str | None:
        cleaned = CompanyMemory._clean_text(value)
        return cleaned or None

    @staticmethod
    def _clean_string_list(
        values: Any,
    ) -> list[str]:
        if values is None:
            return []

        if isinstance(values, str):
            values = [values]

        if not isinstance(values, list):
            raise MemoryValidationError(
                "목록 필드는 list 또는 문자열이어야 합니다."
            )

        cleaned_values: list[str] = []

        for value in values:
            cleaned = CompanyMemory._clean_text(value)

            if cleaned and cleaned not in cleaned_values:
                cleaned_values.append(cleaned)

        return cleaned_values

    @staticmethod
    def _normalize_search_text(value: str) -> str:
        return "".join(
            value.lower().split()
        )

    @staticmethod
    def _generate_memory_id() -> str:
        return f"mem_{uuid4().hex[:16]}"

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()


# =========================================================
# 공용 Company Memory 인스턴스
# =========================================================

company_memory = CompanyMemory()


# =========================================================
# 단독 실행 테스트
# =========================================================

if __name__ == "__main__":
    owner_result = company_memory.remember_owner_instruction(
        title="AI CEO 운영 원칙",
        content=(
            "AI CEO는 직접 실무를 수행하지 않는다. "
            "대표의 목표를 분석하고 지점장에게 업무를 위임한다."
        ),
        importance=5,
        tags=[
            "AI CEO",
            "운영원칙",
            "업무위임",
        ],
    )

    project_result = company_memory.remember_project_status(
        project_id="project_melatonin_001",
        title="식물성 멜라토닌 프로젝트 상태",
        content=(
            "제품 출시 전 단계이며 OEM 견적 조사 업무를 진행한다."
        ),
        source_agent_id="manager_product_001",
        importance=4,
        tags=[
            "멜라토닌",
            "OEM",
            "제품출시",
        ],
    )

    agent_result = company_memory.remember_agent_result(
        title="OEM 조사 업무 배정",
        content=(
            "제품 관리 지점장이 OEM 직원에게 "
            "제조사, MOQ, 견적 조사 업무를 위임했다."
        ),
        source_agent_id="manager_product_001",
        project_id="project_melatonin_001",
        related_agent_ids=[
            "oem_staff_001",
        ],
        importance=4,
        tags=[
            "OEM",
            "Handoff",
        ],
    )

    search_results = company_memory.search_memories(
        "멜라토닌 OEM",
        project_id="project_melatonin_001",
        limit=10,
    )

    context_text = company_memory.build_context_text(
        query="AI CEO 운영 원칙",
        limit=10,
    )

    validation = company_memory.validate_memory_store()
    statistics = company_memory.get_statistics()

    print("=" * 60)
    print("Company Memory 테스트 완료")
    print("대표 지시 저장:", owner_result["reason"])
    print("프로젝트 상태 저장:", project_result["reason"])
    print("Agent 결과 저장:", agent_result["reason"])
    print("검색 결과 수:", len(search_results))
    print("Memory 구조 정상:", validation["valid"])
    print("전체 Memory 수:", statistics["total"])
    print("Context:")
    print(context_text)
    print("=" * 60)
