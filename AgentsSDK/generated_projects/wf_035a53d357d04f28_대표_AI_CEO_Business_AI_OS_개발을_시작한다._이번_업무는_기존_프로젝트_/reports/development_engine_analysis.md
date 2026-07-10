# Development Engine 구축 분석 보고서

## 1. 업무 목적
대표의 개발 지시("오류 수정", "기능 추가", "기능 수정", "새 기능 생성")를 입력받은 AI CEO가 다음 절차를 자동 수행하도록 Development Engine을 구축한다.

1. 기존 프로젝트 검색
2. GitHub 최신 프로젝트 검색
3. 관련 Python 파일 검색
4. 함수·클래스 분석
5. 수정 대상 결정
6. Worker 배정
7. 실제 코드 수정
8. 자동 테스트
9. 테스트 실패 시 재수정
10. Git Commit
11. 대표 승인
12. Git Push

핵심 제약:
- 기존 CEO / Workflow / Dashboard / Worker 구조 유지
- 신규 생성보다 기존 코드 수정 우선
- 회의실 개발 운영 체계로 전환

## 2. 현재 분석 결론
현재 제공된 컨텍스트만으로는 저장소 파일 트리와 실제 Python 소스가 노출되지 않아, 구체적인 파일명 단위 수정은 아직 확정할 수 없다. 따라서 먼저 기존 코드 위치를 찾아야 한다.

## 3. 우선 탐색 대상
다음 패턴의 파일/모듈을 우선 검색한다.

- CEO 엔트리 포인트: `ceo.py`, `main.py`, `app.py`, `engine.py`
- Workflow 정의: `workflow.py`, `workflows/`, `workflow_engine.py`
- Worker 정의: `worker.py`, `workers/`, `task_worker.py`
- 대시보드/UI: `dashboard.py`, `ui/`, `streamlit_app.py`, `gradio_app.py`
- Git 연동/배포: `git_utils.py`, `deploy.py`, `github_sync.py`
- 테스트: `tests/`, `test_*.py`

## 4. 필요한 기능 설계
Development Engine은 최소 다음 컴포넌트를 가져야 한다.

### 4.1 지시 분류기
대표 메시지를 분류해 작업 유형을 결정한다.
- 오류 수정
- 기능 추가
- 기능 수정
- 새 기능 생성

### 4.2 검색 모듈
- 프로젝트 내 관련 파일 검색
- GitHub 최신 버전 검색(권한 필요 가능)
- 함수/클래스/호출관계 탐색

### 4.3 수정 계획 생성기
- 수정 대상 파일 목록화
- 영향 범위 산정
- Worker 배정안 작성

### 4.4 실행 오케스트레이터
- Worker 작업 요청
- 코드 수정 반영
- 테스트 실행
- 실패 시 재시도
- 커밋/푸시 준비

### 4.5 승인 단계 추적기
- 대표 승인 전 상태 보류
- 승인 후 Git Push 실행

## 5. 기존 구조에 대한 영향도
### 유지 필요
- CEO: 지시 수신 및 의사결정
- Workflow: 작업 상태 전이
- Dashboard: 진행 현황 표시
- Worker: 실제 실행 담당

### 수정 가능성 높은 영역
- Workflow 상태 정의 확장
- CEO의 작업 해석/분기 로직 추가
- Worker의 작업 타입 추가
- 테스트/커밋/푸시 단계 상태 추가

## 6. 구현 우선순위
1. 기존 파일 탐색 및 구조 파악
2. CEO/Workflow/Worker의 현재 인터페이스 확인
3. 수정 중심의 Development Engine 추가
4. 테스트 단계 자동화
5. 커밋/승인/푸시 상태 추적

## 7. 권한 필요 가능성
다음 작업은 외부 권한이 필요할 수 있다.
- GitHub 최신 프로젝트 조회
- Git commit / push
- 원격 배포 연결

## 8. 다음 실행 액션
실제 저장소에서 관련 Python 파일을 탐색하여:
- 현재 CEO/Workflow/Worker 구현 위치 식별
- 변경 대상 함수/클래스 확정
- 수정 패치 작성
- 테스트 코드 확인

## 9. 결론
이번 업무는 신규 시스템을 새로 만드는 것이 아니라, 기존 Business AI OS의 CEO/Workflow/Worker 기반에 Development Engine을 덧붙여 회의실 개발 운영이 가능하도록 확장하는 작업이다. 다음 단계는 실 저장소 분석 후 구체 코드 수정안을 작성하는 것이다.
