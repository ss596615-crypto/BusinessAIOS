# Development Engine MVP V1.1

수정 내용:
- 지시에 파일명이 있으면 해당 파일만 수정
- 무관한 *_old.py 수정 차단
- 전체 저장소 compileall 제거
- 변경된 Python 파일만 py_compile
- README/문서 수정은 git diff --check로 검증

적용:
1. 파일을 C:\DevelopmentEngine에 덮어쓰기
2. 아래 4개 파일만 커밋
3. run_development_engine.cmd 실행
