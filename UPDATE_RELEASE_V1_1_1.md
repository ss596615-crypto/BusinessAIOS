# Business AI OS RELEASE V1.1.1

- 승인 후 Worker 재개 시 None 값에 대한 `.strip()` 오류 방어
- 빈 Agent 설명은 OpenAI Agents SDK에 전달하지 않도록 수정
- 승인 메모/승인자 문자열 정규화
- 승인 오류 발생 시 회의실에 상세 traceback 표시
