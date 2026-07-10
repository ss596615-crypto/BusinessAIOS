# AI CEO Development Engine V1

## 적용 기능
- 회의실 개발 지시 자동 감지
- `C:\BusinessAIOS` 실제 파일 읽기·쓰기
- 관련 Python 파일 자동 검색 및 코드 분석
- 변경 전 자동 백업
- AI Worker의 전체 파일 완성본 생성
- `py_compile` 및 `pytest` 자동 실행
- 테스트 실패 시 자동 복구
- 성공 시 `ai-ceo-dev` 브랜치에 자동 commit
- 대표 승인 후 `git push origin ai-ceo-dev`
- 수정 파일, 테스트, diff, commit, push 증거 저장

## 필수 조건
- 현재 Git 브랜치가 `ai-ceo-dev`
- 작업 시작 전 `git status`가 clean 상태
- GitHub CLI 로그인 완료
- `.env`에 `OPENAI_API_KEY` 설정

## 첫 테스트 지시
`승인 완료된 Workflow에서 승인·반려 버튼이 계속 보이는 오류를 수정하라. 실제 파일을 수정하고 자동 테스트 후 Git commit을 생성하라.`
