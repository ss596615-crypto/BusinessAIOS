const state = {
  directives: [
    { title: '대표 지시 접수', sub: 'Business AI OS 운영 홈페이지 구축 및 출시', badge: '완료' },
    { title: '승인/반려 프로세스 연결', sub: '워크플로우 상태 반영 및 이력 관리', badge: '진행중' },
    { title: '보고서 조회 구조', sub: '운영보고 및 결과물 목록 표시', badge: '완료' }
  ],
  workflows: [
    { title: '화면 설계', sub: '운영/관리자 구조 반영', badge: '완료' },
    { title: '데이터 상태관리', sub: '현황 카드 및 목록 렌더링', badge: '완료' },
    { title: '외부 연동', sub: 'Google Drive/GitHub 등 권한 필요 시 연결', badge: '보류' }
  ],
  staff: [
    { title: '운영총괄지점장', sub: '승인/상향보고 판단', badge: '관리' },
    { title: '운영대시보드 개발·연동 담당자', sub: 'UI/연동 구현', badge: '실행' },
    { title: '운영화면·업무흐름 분석 담당자', sub: '구조/흐름 정의', badge: '지원' }
  ],
  permissions: [
    { title: 'GitHub 저장소 연결', sub: '배포/형상관리 연동 필요 시 요청', badge: '승인대기' }
  ],
  reports: [
    { title: '운영보고서', text: '프로젝트 진행률, 승인 상태, 권한 요청, 완료 결과물 요약을 포함합니다.' },
    { title: '결과물 목록', text: 'index.html, assets/style.css, assets/app.js 등 실행 파일을 포함합니다.' },
    { title: '미해결 이슈', text: '실계정 연동 및 배포는 외부 권한이 필요할 수 있습니다.' }
  ]
};

function renderList(targetId, items) {
  const el = document.getElementById(targetId);
  const tpl = document.getElementById('itemTemplate');
  el.innerHTML = '';
  items.forEach(item => {
    const node = tpl.content.cloneNode(true);
    node.querySelector('.item-title').textContent = item.title;
    node.querySelector('.item-sub').textContent = item.sub;
    node.querySelector('.item-badge').textContent = item.badge;
    el.appendChild(node);
  });
}

function renderReports() {
  const el = document.getElementById('reportList');
  el.innerHTML = state.reports.map(r => `<div class="report-card"><h3>${r.title}</h3><p>${r.text}</p></div>`).join('');
}

function refreshMetrics() {
  document.getElementById('projectProgress').textContent = '82%';
  document.getElementById('pendingApprovals').textContent = '3';
  document.getElementById('permissionCount').textContent = String(state.permissions.length);
  document.getElementById('deliverablesCount').textContent = '5';
  document.getElementById('progressText').textContent = '배포 전 검수 단계';
  document.getElementById('progressBar').style.width = '82%';
}

document.getElementById('btnRefresh').addEventListener('click', () => {
  renderList('directiveList', state.directives);
  renderList('workflowList', state.workflows);
  renderList('staffList', state.staff);
  renderList('permissionList', state.permissions);
  renderReports();
  refreshMetrics();
});

document.getElementById('btnSampleReport').addEventListener('click', () => {
  state.reports.unshift({
    title: '샘플 운영 보고',
    text: '대시보드 기본 구조가 구현되었으며, 추가 연동은 권한 확보 후 재개 가능합니다.'
  });
  renderReports();
});

renderList('directiveList', state.directives);
renderList('workflowList', state.workflows);
renderList('staffList', state.staff);
renderList('permissionList', state.permissions);
renderReports();
refreshMetrics();
