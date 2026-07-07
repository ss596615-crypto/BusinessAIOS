"""
Business AI OS
employees.py
"""

class AIEmployee:
    def __init__(self, name, role):
        self.name = name
        self.role = role
        self.status = "Idle"
        self.task = None

    def assign(self, task):
        self.task = task
        self.status = "Working"
        print(f"[{self.name}] Task Assigned: {task}")

    def complete(self):
        print(f"[{self.name}] Task Completed")
        self.task = None
        self.status = "Idle"


class EmployeeManager:

    def __init__(self):
        self.employees = {}

    def hire(self, name, role):
        self.employees[name] = AIEmployee(name, role)
        print(f"Hired: {name} ({role})")

    def fire(self, name):
        if name in self.employees:
            del self.employees[name]
            print(f"Removed: {name}")

    def assign(self, name, task):
        if name in self.employees:
            self.employees[name].assign(task)

    def complete(self, name):
        if name in self.employees:
            self.employees[name].complete()

    def list(self):
        print("\n=== AI Employees ===")
        for e in self.employees.values():
            print(f"{e.name} | {e.role} | {e.status}")


if __name__ == "__main__":
    manager = EmployeeManager()

    manager.hire("Automation AI","Automation")
    manager.hire("Marketing AI","Marketing")

    manager.list()

    manager.assign("Automation AI","Create Zap")
    manager.complete("Automation AI")

    manager.list()
