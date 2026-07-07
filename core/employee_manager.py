from ai_employees.product_ai import ProductAI
from ai_employees.marketing_ai import MarketingAI
from ai_employees.finance_ai import FinanceAI


class EmployeeManager:

    def __init__(self):

        self.employees = {
            "제품 AI": ProductAI(),
            "마케팅 AI": MarketingAI(),
            "재무 AI": FinanceAI()
        }


    def assign(self, task):

        results = []

        if "제품" in task or "출시" in task:
            results.append(
                self.employees["제품 AI"].work(task)
            )

        if "마케팅" in task or "판매" in task:
            results.append(
                self.employees["마케팅 AI"].work(task)
            )

        if "비용" in task or "자금" in task:
            results.append(
                self.employees["재무 AI"].work(task)
            )

        if not results:
            results.append(
                "현재 연결된 AI 직원 없음"
            )

        return "\n".join(results)
