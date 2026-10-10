import pytest
from classifiers.doc_classifier import classify, DocType
from cleaner import resolve_prompt_path, load_prompt, load_prompt_for_text


def test_classify_technical_document():
    text = """
    # Service Architecture Overview v2.1.0
    The following diagram illustrates the workflow:
    API Gateway -> Auth Service -> Microservices
    ```python
    def handle_request(req):
        return {"status": "ok"}
    ```
    Endpoints available:
    POST /api/v1/auth/login
    GET /api/v1/users
    Deployment uses Docker and Kubernetes pipeline.
    """
    assert classify(text) == DocType.TECHNICAL


def test_classify_financial_document():
    text = """
    永豐商業銀行 信用卡對帳單
    帳號：1234-****-****-5678
    結帳日：2026/02/15
    本期應繳總金額：NT$ 25,680
    交易明細：
    2026-02-01 餐廳消費 1,200.00
    2026-02-03 超商購物 350.00
    循環信用年利率：15%
    """
    assert classify(text) == DocType.FINANCE


def test_classify_general_document():
    text = """
    秋天的校園十分美麗。樹葉漸漸變黃，微風徐徐吹過湖面。
    同學們在草地上看書、聊天，享受這難得的悠閒午後時光。
    生活中的點點滴滴，都是成長過程中最珍貴的回憶。
    """
    assert classify(text) == DocType.GENERAL


def test_classify_empty_text():
    assert classify("") == DocType.GENERAL
    assert classify(None) == DocType.GENERAL


def test_resolve_prompt_path():
    tech_path = resolve_prompt_path("technical", translate_zh_hant=False)
    assert tech_path is not None
    assert tech_path.endswith("technical.txt")

    tech_zh_path = resolve_prompt_path("technical", translate_zh_hant=True)
    assert tech_zh_path is not None
    assert tech_zh_path.endswith("technical_zh_hant.txt")

    fin_path = resolve_prompt_path("finance", translate_zh_hant=False)
    assert fin_path is not None
    assert fin_path.endswith("finance.txt")


def test_load_prompt_auto_sentinel():
    config = {"ai": {"backend": "gemini"}}
    assert load_prompt(config, prompt_name="auto") == "__auto__"


def test_load_prompt_technical_content():
    config = {"ai": {"backend": "gemini"}}
    prompt = load_prompt(config, prompt_name="technical")
    assert "technical document cleaning AI" in prompt
    assert "Mermaid" in prompt


def test_load_prompt_for_text_dynamic():
    config = {"ai": {"backend": "gemini"}}
    tech_text = """
    # Architecture Overview
    API Gateway -> Auth Service
    ```python
    def main(): pass
    ```
    Endpoints: POST /api/v1/auth
    Deploy with docker and kubernetes.
    """
    prompt = load_prompt_for_text(tech_text, config)
    assert "technical document cleaning AI" in prompt

    # General text falls back to default.txt
    general_text = "今天天氣真好，大家一起到戶外散步踏青。"
    gen_prompt = load_prompt_for_text(general_text, config)
    assert "You are a document cleaning AI" in gen_prompt
