import React, { useEffect, useMemo, useState } from 'react';

export default function Dashboard({ workflows = [], currentWorkflowId, onSelectWorkflow }) {
  const [currentWorkflow, setCurrentWorkflow] = useState(null);

  const inProgressWorkflows = useMemo(
    () => workflows.filter((workflow) => workflow.status === 'in_progress'),
    [workflows]
  );

  useEffect(() => {
    if (currentWorkflowId) {
      const matched = workflows.find((workflow) => workflow.id === currentWorkflowId);
      if (matched && matched.status === 'in_progress') {
        setCurrentWorkflow(matched);
        return;
      }
    }

    if (inProgressWorkflows.length > 0) {
      const latest = inProgressWorkflows[0];
      setCurrentWorkflow(latest);
      if (onSelectWorkflow) onSelectWorkflow(latest.id);
      return;
    }

    setCurrentWorkflow(null);
  }, [workflows, currentWorkflowId, inProgressWorkflows, onSelectWorkflow]);

  return (
    <div className="dashboard">
      <section className="dashboard-current-workflow">
        <h2>현재 Workflow</h2>
        {currentWorkflow ? (
          <div className="workflow-card" data-testid="current-workflow-card">
            <div className="workflow-title">{currentWorkflow.name}</div>
            <div className="workflow-meta">상태: 진행 중</div>
          </div>
        ) : (
          <div className="workflow-empty" data-testid="current-workflow-empty" style={{ display: 'none' }} />
        )}
      </section>
    </div>
  );
}
