# Business AI OS 운영 홈페이지 구축·출시 사양서

## 1. 목적
Business AI OS 운영 홈페이지는 일반 소개용 웹사이트가 아니라, 대표 지시를 접수하고 승인/반려/진행/결과보고까지 추적하는 운영 대시보드다.

## 2. 핵심 사용자
- 대표
- 지점장
- 담당 직원
- 운영/관리자

## 3. 핵심 업무 흐름
1. 대표 지시 등록
2. 지점장 검토 및 승인/반려
3. 승인 시 담당자 배정 및 진행 상태 변경
4. 진행 중 코멘트/증빙/파일 업로드
5. 완료 후 결과보고 등록
6. 지점장 최종 확인 및 아카이브

## 4. 화면 구성

### 4.1 대시보드
- 오늘의 지시 건수
- 승인 대기/진행 중/완료/반려 건수
- 지점장 승인 요청
- 권한 요청 현황
- 최근 결과보고

### 4.2 대표 지시 상세
필드:
- 지시 ID
- 제목
- 내용
- 우선순위
- 기한
- 요청 부서/담당자
- 첨부파일
- 상태
- 생성자
- 생성일
- 최종 업데이트일

상태값:
- draft
- pending_approval
- approved
- rejected
- in_progress
- waiting_permission
- completed
- archived

### 4.3 승인/반려 화면
- 승인 사유
- 반려 사유
- 추가 요청 사항
- 승인자
- 승인일시

### 4.4 진행 관리 화면
- 담당자
- 진행 단계
- 작업 메모
- 파일 첨부
- 장애/권한 이슈
- 진행률

### 4.5 결과보고 화면
- 결과 요약
- 수행 내용
- 산출물 링크
- 미해결 이슈
- 후속 조치
- 보고자
- 보고일

### 4.6 권한 요청 화면
- 요청 서비스명
- 요청 사유
- 필요 권한 범위
- 승인 후 재개 작업
- 요청 상태

## 5. 권한 규칙
- 대표: 지시 생성, 최종 확인
- 지점장: 승인/반려, 담당자 배정, 결과 검수
- 담당 직원: 진행 등록, 증빙 첨부, 결과보고 작성
- 운영자: 화면/권한/상태 관리

## 6. 운영 규칙
- 승인 전에는 진행 상태로 전환 불가
- 권한 부족 시 waiting_permission으로 전환
- 권한 승인 후 중단 지점부터 재개
- 결과보고 없이는 완료 처리 불가
- 반려 건은 사유 필수

## 7. 데이터 구조 초안

### 7.1 Task
- id
- title
- content
- priority
- due_date
- status
- requester
- assignee
- approver
- created_at
- updated_at

### 7.2 Approval
- task_id
- decision
- reason
- decided_by
- decided_at

### 7.3 PermissionRequest
- service
- reason
- requested_scope
- resume_action
- status

### 7.4 Report
- task_id
- summary
- details
- attachments
- issues
- next_actions
- reported_by
- reported_at

## 8. 출시 기준
- 대표 지시 등록 가능
- 승인/반려 가능
- 진행 및 결과보고 추적 가능
- 권한 요청 기록 가능
- 대시보드에서 전체 상태 한눈에 확인 가능

## 9. 구현 우선순위
1. 운영 대시보드
2. 지시/승인/반려 플로우
3. 진행/결과보고 화면
4. 권한 요청 화면
5. 로그/아카이브
