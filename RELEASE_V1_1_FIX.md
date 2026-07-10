# Business AI OS Release V1.1 — Approval Blocker Fix

- `approval_status == pending` 및 `status == waiting_approval`일 때만 승인·반려 표시
- approved/rejected/not_required 상태에서는 승인 영역 숨김
- 선택된 Workflow가 없으면 진행 중 또는 승인 대기 Workflow 자동 선택
- AI 분석 결과의 선택 입력값이 `None`이어도 `.strip()` 오류가 발생하지 않도록 보정
- Worker 상태값 `None` 방어 처리
- 승인·반려 오류에 예외 유형 표시

## 적용
기존 `C:\BusinessAIOS`를 백업한 뒤 이 ZIP을 덮어쓰고 회의실을 다시 실행합니다.
