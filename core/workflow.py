class WorkflowManager:

    def analyze(self, instruction):

        departments = []

        if any(word in instruction for word in ["제품", "출시", "개발", "상품"]):
            departments.append("제품 AI")

        if any(word in instruction for word in ["판매", "광고", "마케팅", "홍보"]):
            departments.append("마케팅 AI")

        if any(word in instruction for word in ["돈", "자금", "비용", "투자"]):
            departments.append("재무 AI")

        if not departments:
            departments.append("AI CEO 직접 분석")

        return f"""
업무 분석 완료

대표 지시:
{instruction}

필요 부서:
{', '.join(departments)}
"""