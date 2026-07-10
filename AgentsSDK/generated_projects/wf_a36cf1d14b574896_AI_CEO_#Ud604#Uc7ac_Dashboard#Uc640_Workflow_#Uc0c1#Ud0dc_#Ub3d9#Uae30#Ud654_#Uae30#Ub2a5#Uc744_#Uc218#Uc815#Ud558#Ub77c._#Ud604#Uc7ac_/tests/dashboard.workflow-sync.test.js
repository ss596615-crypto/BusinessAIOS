import { render, screen } from '@testing-library/react';
import Dashboard from '../src/components/Dashboard';

const workflowA = { id: 'wf_1', name: '신규 리포트 생성', status: 'in_progress' };
const workflowB = { id: 'wf_2', name: '정산 완료', status: 'completed' };

describe('Dashboard workflow sync', () => {
  test('진행 중 Workflow 1건이 있으면 자동 표시된다', () => {
    render(<Dashboard workflows={[workflowA, workflowB]} currentWorkflowId={null} />);
    expect(screen.getByTestId('current-workflow-card')).toBeInTheDocument();
    expect(screen.getByText('신규 리포트 생성')).toBeInTheDocument();
  });

  test('완료 처리 시 자동으로 현재 Workflow에서 제거된다', () => {
    const { rerender } = render(<Dashboard workflows={[workflowA]} currentWorkflowId="wf_1" />);
    expect(screen.getByTestId('current-workflow-card')).toBeInTheDocument();

    rerender(<Dashboard workflows={[{ ...workflowA, status: 'completed' }]} currentWorkflowId="wf_1" />);
    expect(screen.queryByTestId('current-workflow-card')).toBeNull();
  });

  test('새로운 진행 중 Workflow가 있으면 자동으로 교체된다', () => {
    const { rerender } = render(<Dashboard workflows={[workflowA]} currentWorkflowId="wf_1" />);
    expect(screen.getByText('신규 리포트 생성')).toBeInTheDocument();

    rerender(<Dashboard workflows={[{ id: 'wf_3', name: '고객 응대', status: 'in_progress' }]} currentWorkflowId={null} />);
    expect(screen.getByText('고객 응대')).toBeInTheDocument();
  });
});
