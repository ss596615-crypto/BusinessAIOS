import { useEffect, useState } from 'react';

export function useWorkflowSync(fetchWorkflows) {
  const [workflows, setWorkflows] = useState([]);

  useEffect(() => {
    let mounted = true;

    async function load() {
      const next = await fetchWorkflows();
      if (mounted) setWorkflows(next || []);
    }

    load();
    const timer = setInterval(load, 3000);

    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [fetchWorkflows]);

  return { workflows, setWorkflows };
}
