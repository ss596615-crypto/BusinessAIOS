# Development Engine MVP V2

## 기능
- AI 코드 수정
- 변경 파일별 자동 테스트
- Git commit 자동 생성
- Evidence 상태 `waiting_approval`
- 대표 승인 후 `git push origin ai-ceo-dev`
- Push 성공 시 Evidence를 `completed`로 갱신

## 적용
ZIP의 파일을 `C:\DevelopmentEngine`에 덮어씁니다.

```cmd
cd /d C:\DevelopmentEngine
git add development_engine_mvp.py run_development_engine.cmd approve_development_push.cmd README_MVP.md requirements_dev_engine.txt
git commit -m "Add representative approval push flow"
```

## 사용
1. `run_development_engine.cmd` 실행
2. AI 수정·테스트·commit 완료 확인
3. 대표가 결과 검토
4. `approve_development_push.cmd` 실행
5. `Y` 입력
6. GitHub `ai-ceo-dev` Push 완료 확인
