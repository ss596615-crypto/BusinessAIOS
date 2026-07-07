"""
Business AI OS - AI CEO
Version: 0.1
"""

from agents import Agent

AI_CEO = Agent(
    name="AI CEO",
    instructions="""
당신은 Business AI OS의 최고경영자이다.

운영 원칙
1. 대표의 목표를 최우선으로 한다.
2. 기존 회사 자산을 먼저 검색한다.
3. 기존 자산으로 해결 가능하면 재사용한다.
4. 필요할 때만 AI 직원을 생성하거나 업무를 위임한다.
5. 반복 업무는 자동화(Zapier)를 우선 검토한다.
6. 모든 결과물은 회사 자산으로 저장한다.
7. 업무 완료 후 운영보고서를 작성한다.
8. 대표 승인이 필요한 사항은 승인요청서를 작성한다.
"""
)

class BusinessAIOS:

    def __init__(self):
        self.company = "Business AI OS"
        self.assets = []
        self.employees = []

    def search_assets(self):
        print("Searching company assets...")

    def analyze(self, instruction):
        print(f"Analyzing: {instruction}")

    def hire_employee(self, role):
        self.employees.append(role)
        print(f"Hired AI Employee: {role}")

    def assign(self, role, task):
        print(f"{role} -> {task}")

    def report(self):
        print("Creating operation report...")

def main():

    company = BusinessAIOS()

    print("=" * 50)
    print("Business AI OS")
    print("AI CEO Started")
    print("=" * 50)

    while True:

        cmd = input("\n대표 > ")

        if cmd.lower() in ["exit", "quit"]:
            break

        company.search_assets()
        company.analyze(cmd)
        company.report()

if __name__ == "__main__":
    main()
