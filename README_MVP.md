# Development Engine MVP V1

## 설치

ZIP 안의 파일을 `C:\DevelopmentEngine`에 복사합니다.

```cmd
cd /d C:\DevelopmentEngine
py -m pip install -r requirements_dev_engine.txt
```

`.env` 파일을 만듭니다.

```env
OPENAI_API_KEY=본인의_API_KEY
OPENAI_MODEL=gpt-5.2
```

## 첫 테스트

`run_development_engine.cmd`를 더블클릭하고 아래 지시를 입력합니다.

```text
README.md 마지막 줄에 Hello AI CEO를 추가하라.
```

성공 기준:

- README.md 실제 수정
- 자동 테스트 성공
- 새 Git commit 생성
- `development_evidence` 폴더에 증거 JSON 생성

이 MVP는 안전을 위해 자동 push는 하지 않습니다.
