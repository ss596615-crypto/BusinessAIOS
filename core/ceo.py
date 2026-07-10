from core.asset_manager import AssetManager
from core.employee_manager import EmployeeManager
from core.report_manager import ReportManager
from core.approval_manager import ApprovalManager
from core.ai_brain import AIBrain


class AICEO:

    def __init__(self):
        self.assets = AssetManager()
        self.employees = EmployeeManager()
        self.reports = ReportManager()
        self.approvals = ApprovalManager()
        self.brain = AIBrain()

    def start(self):

        print("===================================")
        print("Business AI OS")
        print("AI CEO Started")
        print("===================================")

        while True:

            command = input("\n대표 > ")

            if command in ["exit", "종료"]:
                print("AI CEO 종료")
                return

            assets = self.assets.search(command)

            analysis = self.brain.analyze(command, assets)

            approval = self.approvals.check(command)

            employee_result = self.employees.assign(command)

            result = f"""

[AI CEO 판단]

{analysis}


[기존 회사 자산]

{assets if assets else "관련 자료 없음"}


[승인 상태]

{approval}


[AI 직원 결과]

{employee_result}

"""

            self.reports.create_operation_report(
                command,
                result
            )

            print("\nAI CEO 실행 결과")
            print(result)