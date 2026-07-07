from core.asset_manager import AssetManager
from core.employee_manager import EmployeeManager
from core.report_manager import ReportManager
from core.approval_manager import ApprovalManager
from core.workflow import WorkflowManager


class AICEO:

    def __init__(self):

        self.assets = AssetManager()
        self.employees = EmployeeManager()
        self.reports = ReportManager()
        self.approvals = ApprovalManager()
        self.workflow = WorkflowManager()


    def start(self):

        print("===================================")
        print("Business AI OS")
        print("AI CEO Started")
        print("===================================")

        while True:

            command = input("\n대표 > ")

            if command in ["exit", "종료"]:
                break

            # 1. 회사 자산 검색
            self.assets.scan()

            # 2. 업무 분석
            analysis = self.workflow.analyze(command)

            # 3. AI 직원 배정
            employee_result = self.employees.assign(command)

            # 4. 결과 취합
            result = f"""
{analysis}

{employee_result}
"""

            # 5. 운영보고 저장
            self.reports.create_operation_report(
                command,
                result
            )

            print("\nAI CEO 실행 결과")
            print(result)
        print("===================================")

        while True:

            command = input("\n대표 > ")

            if command in ["exit", "종료"]:
                break

            self.assets.scan()

            result = self.workflow.analyze(command)

            self.reports.create_operation_report(
                command,
                result
            )

            print("\nAI CEO 분석 완료")
            print(result)