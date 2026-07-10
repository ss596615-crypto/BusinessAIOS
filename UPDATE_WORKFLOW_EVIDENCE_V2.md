# Business AI OS 업데이트

## 적용 기능
- 기존 Workflow ID가 포함된 조회·검증·재실행·재개·취소 요청은 신규 Workflow를 생성하지 않음
- 기존 Workflow 동일 ID 직접 처리
- 산출물, Worker 실행 결과, Git status/diff, 테스트 증거 자동 수집
- 증거 필수 업무는 성공한 테스트 증거가 없으면 completed 차단
- 증거 부족 시 failed 상태와 다음 작업 기록
- AI CEO 회의실에 완료 증거 요약 표시

## 수정 파일
- AgentsSDK/ceo_meeting.py
- AgentsSDK/runtime.py
- AgentsSDK/workflow_manager.py
