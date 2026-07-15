from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from tool_registry import ToolRegistry, tool_registry


# =========================================================
# Errors
# =========================================================

class ToolSelectionError(RuntimeError):
    """Tool 선택 엔진 공통 오류."""


# =========================================================
# Selection Result
# =========================================================

@dataclass
class ToolSelectionResult:
    status: str
    selected_tool: dict[str, Any] | None
    candidates: list[dict[str, Any]]
    query: str
    reason: str
    creation_required: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "selected_tool": self.selected_tool,
            "candidates": self.candidates,
            "query": self.query,
            "reason": self.reason,
            "creation_required": self.creation_required,
        }


# =========================================================
# Tool Selection Engine
# =========================================================

class ToolSelectionEngine:
    """
    Business AI OS Tool Selection Engine.

    역할:
    1. 직원 업무 설명을 분석한다.
    2. Tool Registry에서 기존 Tool을 검색한다.
    3. 업무와 Tool의 적합도를 계산한다.
    4. 가장 적합한 Tool을 선택한다.
    5. 적합한 Tool이 없으면 신규 Tool 생성이 필요하다고 판단한다.

    선택 조건:
    - status == active
    - approval_status == approved
    - test_status == passed
    - reusable == True
    """

    MINIMUM_SELECTION_SCORE = 20

    def __init__(
        self,
        registry: ToolRegistry | None = None,
    ) -> None:
        self.registry = registry or tool_registry

    # =====================================================
    # Public API
    # =====================================================

    def select_tool(
        self,
        *,
        task: str,
        category: str | None = None,
        preferred_tool_id: str | None = None,
        required_capabilities: list[str] | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """
        업무에 가장 적합한 기존 Tool을 선택한다.
        """

        normalized_task = self._normalize(task)

        if not normalized_task:
            raise ToolSelectionError(
                "Tool 선택에 필요한 업무 설명이 없습니다."
            )

        # 1. 명시된 Tool ID 우선
        if preferred_tool_id:
            preferred = self.registry.find_tool(
                tool_id=preferred_tool_id,
                status="active",
                approval_status="approved",
                test_status="passed",
                reusable_only=True,
            )

            if preferred:
                return ToolSelectionResult(
                    status="selected",
                    selected_tool=preferred,
                    candidates=[preferred],
                    query=task,
                    reason="대표 또는 시스템이 지정한 기존 Tool을 선택했습니다.",
                    creation_required=False,
                ).to_dict()

        # 2. Registry 전체 검색
        tools = self.registry.list_tools(
            category=category,
            status="active",
            approval_status="approved",
            test_status="passed",
            reusable_only=True,
        )

        required_capabilities = [
            self._normalize(value)
            for value in (required_capabilities or [])
            if self._normalize(value)
        ]

        ranked: list[dict[str, Any]] = []

        for tool in tools:
            score, evidence = self._score_tool(
                tool=tool,
                task=normalized_task,
                category=category,
                required_capabilities=required_capabilities,
            )

            if score <= 0:
                continue

            candidate = dict(tool)
            candidate["selection_score"] = score
            candidate["selection_evidence"] = evidence
            ranked.append(candidate)

        ranked.sort(
            key=lambda item: (
                item.get("selection_score", 0),
                self._version_key(item.get("version", "0.0.0")),
                item.get("updated_at", ""),
            ),
            reverse=True,
        )

        candidates = ranked[:max(int(top_k), 1)]

        if not candidates:
            return ToolSelectionResult(
                status="tool_not_found",
                selected_tool=None,
                candidates=[],
                query=task,
                reason="업무와 일치하는 기존 Tool이 없습니다.",
                creation_required=True,
            ).to_dict()

        selected = candidates[0]
        selected_score = int(
            selected.get("selection_score", 0)
        )

        if selected_score < self.MINIMUM_SELECTION_SCORE:
            return ToolSelectionResult(
                status="tool_not_found",
                selected_tool=None,
                candidates=candidates,
                query=task,
                reason=(
                    "검색된 Tool의 적합도가 기준보다 낮아 "
                    "신규 Tool 생성이 필요합니다."
                ),
                creation_required=True,
            ).to_dict()

        return ToolSelectionResult(
            status="selected",
            selected_tool=selected,
            candidates=candidates,
            query=task,
            reason=(
                f"업무 적합도 점수 {selected_score}점으로 "
                f"'{selected.get('name')}'을 선택했습니다."
            ),
            creation_required=False,
        ).to_dict()

    def select_or_prepare_creation(
        self,
        *,
        task: str,
        category: str | None = None,
        preferred_tool_id: str | None = None,
        required_capabilities: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        기존 Tool을 선택하거나 신규 Tool 생성 요청에 필요한 정보를 만든다.
        """

        selection = self.select_tool(
            task=task,
            category=category,
            preferred_tool_id=preferred_tool_id,
            required_capabilities=required_capabilities,
        )

        if not selection.get("creation_required"):
            return selection

        suggested_name = self._suggest_tool_name(task)

        selection["creation_request"] = {
            "requested_name": suggested_name,
            "requested_category": category or "general",
            "requested_description": (
                f"업무 '{task}'를 수행하기 위한 실행 Tool"
            ),
            "requested_capability": task,
            "creation_reason": (
                "Tool Registry 검색 결과 업무 적합도가 기준을 "
                "충족하는 기존 Tool이 없기 때문에 신규 Tool이 필요함"
            ),
            "reuse_search_query": task,
        }

        return selection

    # =====================================================
    # Scoring
    # =====================================================

    def _score_tool(
        self,
        *,
        tool: dict[str, Any],
        task: str,
        category: str | None,
        required_capabilities: list[str],
    ) -> tuple[int, list[str]]:
        score = 0
        evidence: list[str] = []

        tool_id = self._normalize(
            tool.get("tool_id", "")
        )
        name = self._normalize(
            tool.get("name", "")
        )
        tool_category = self._normalize(
            tool.get("category", "")
        )
        description = self._normalize(
            tool.get("description", "")
        )
        entrypoint = self._normalize(
            tool.get("entrypoint", "")
        )

        metadata = tool.get("metadata") or {}
        tags = self._normalize(
            " ".join(
                str(value)
                for value in (
                    metadata.get("tags") or []
                )
            )
        )
        capability = self._normalize(
            metadata.get("requested_capability", "")
        )

        task_tokens = self._tokens(task)

        fields = {
            "tool_id": tool_id,
            "name": name,
            "category": tool_category,
            "description": description,
            "entrypoint": entrypoint,
            "tags": tags,
            "capability": capability,
        }

        # 정확한 문구 일치
        for field_name, field_value in fields.items():
            if task and task in field_value:
                weight = {
                    "name": 50,
                    "tool_id": 45,
                    "description": 35,
                    "tags": 30,
                    "capability": 30,
                    "category": 20,
                    "entrypoint": 10,
                }[field_name]
                score += weight
                evidence.append(
                    f"{field_name}에 업무 문구 포함 +{weight}"
                )

        # 단어 단위 일치
        for token in task_tokens:
            if len(token) < 2:
                continue

            token_score = 0

            if token in name:
                token_score += 10
            if token in tool_id:
                token_score += 8
            if token in description:
                token_score += 6
            if token in tags:
                token_score += 6
            if token in capability:
                token_score += 6
            if token in tool_category:
                token_score += 4
            if token in entrypoint:
                token_score += 2

            if token_score:
                score += token_score
                evidence.append(
                    f"키워드 '{token}' 일치 +{token_score}"
                )

        # 분류 일치
        normalized_category = self._normalize(category)

        if normalized_category:
            if normalized_category == tool_category:
                score += 30
                evidence.append("Tool 분류 정확히 일치 +30")
            elif normalized_category in tool_category:
                score += 15
                evidence.append("Tool 분류 부분 일치 +15")

        # 필수 능력 일치
        combined_text = " ".join(fields.values())

        for capability_value in required_capabilities:
            if capability_value in combined_text:
                score += 15
                evidence.append(
                    f"필수 능력 '{capability_value}' 일치 +15"
                )
            else:
                score -= 10
                evidence.append(
                    f"필수 능력 '{capability_value}' 미확인 -10"
                )

        # 핵심 Tool 우대
        if bool(metadata.get("core_tool")):
            score += 5
            evidence.append("공식 Core Tool +5")

        return max(score, 0), evidence

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

    @classmethod
    def _tokens(cls, value: Any) -> list[str]:
        normalized = cls._normalize(value)

        return [
            token
            for token in re.split(
                r"[^0-9a-zA-Z가-힣_]+",
                normalized,
            )
            if token
        ]

    @classmethod
    def _suggest_tool_name(cls, task: str) -> str:
        tokens = cls._tokens(task)[:6]

        if not tokens:
            return "Generated Execution Tool"

        readable = " ".join(tokens)
        return f"{readable} Tool"

    @staticmethod
    def _version_key(
        version: Any,
    ) -> tuple[int, int, int, str]:
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


# =========================================================
# Shared Instance
# =========================================================

tool_selection_engine = ToolSelectionEngine()


if __name__ == "__main__":
    result = tool_selection_engine.select_tool(
        task=(
            "Execution Tool Core와 Tool Registry 연결 상태를 "
            "점검하고 통합 테스트 보고서를 생성하라."
        )
    )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
