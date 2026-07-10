# Development Engine 구축 보고서

## 1. 요청 요약
대표 지시를 AI CEO가 직접 개발 업무로 수행할 수 있도록 Business AI OS 내부에 Development Engine을 구축한다.
핵심 요구는 다음 순서의 자동화이다.

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

기존 CEO / Workflow / Dashboard / Worker 구조는 유지하고, 신규 생성보다 기존 코드 수정을 우선한다.

## 2. 기존 구조 유지 원칙
- CEO: 의사결정과 지시 발행 유지
- Workflow: 업무 단계 상태 관리 유지
- Dashboard: 진행 현황/결과 표시 유지
- Worker: 분석/구현/검증 역할 유지
- Development Engine: 기존 구조를 연결하는 실행 계층으로 추가

## 3. 기능 분해
### 3.1 입력 해석
대표 지시를 다음 유형으로 분류:
- 오류 수정
- 기능 추가
- 기능 수정
- 새 기능 생성

### 3.2 프로젝트 탐색
- 로컬 기존 프로젝트 우선 검색
- GitHub 최신 버전 검색은 외부 권한 필요 시 요청
- 관련 Python 파일 탐색
- 함수/클래스/의존관계 식별

### 3.3 영향 분석
- 수정 대상 파일 목록 산출
- 재사용 가능 코드 우선 선정
- 신규 생성 최소화

### 3.4 작업 배정
- 분석 Worker: 파일/의존관계/변경 범위 산출
- 구현 Worker: 코드 수정
- 테스트 Worker: 자동 테스트 및 재수정 판단

### 3.5 실행/검증
- 코드 수정 후 테스트 실행
- 실패 시 원인 분석 후 재수정
- 성공 시 commit 대상 정리

### 3.6 형상관리
- Git Commit 생성
- 대표 승인 대기
- 승인 후 Git Push

## 4. 권장 구현 포인트
### 4.1 신규 모듈보다 기존 모듈 확장
- `CEO`에 지시 분류/작업 생성 기능 추가
- `Workflow`에 상태 전이 추가
- `Worker`에 분석/구현/테스트 역할 확장
- `Dashboard`에 개발 진행/테스트/승인 상태 노출

### 4.2 핵심 데이터 구조
- `task_type`
- `target_repo`
- `matched_files`
- `affected_functions`
- `worker_assignments`
- `test_results`
- `commit_hash`
- `approval_status`

### 4.3 필수 상태
- `searching`
- `analyzing`
- `assigning`
- `modifying`
- `testing`
- `retrying`
- `awaiting_approval`
- `committing`
- `pushing`
- `completed`

## 5. 영향 범위
- 대표 지시 해석 로직
- 파일 검색/분석 로직
- Worker 오케스트레이션
- 테스트 실행기
- Git 작업 단계
- 승인 대기 상태 관리

## 6. 외부 권한 필요 여부
실제 GitHub 검색, commit, push, 배포 연동은 현재 환경에서 직접 수행 불가 또는 권한 필요.
따라서 구현 시 아래 권한이 필요할 수 있음.
- GitHub 저장소 접근 권한
- Git 인증/푸시 권한
- CI/CD 연동 권한

## 7. 결론
이번 과제는 기존 Business AI OS의 구조를 유지하면서, 대표 지시를 실제 개발 작업으로 변환하고 실행/검증/형상관리까지 연결하는 Development Engine을 추가하는 것이다. 우선순위는 기존 코드 재사용이며, 신규 기능은 오케스트레이션 계층 중심으로 최소화하는 것이 적절하다.
