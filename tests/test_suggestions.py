from src.suggestions import SuggestionCache, load_profiles, suggest, suggest_cached
from src.rag import AssetRag, GroqExplainer, RetrievedAsset


class FakeExplainer:
    def explain(self, company_name, minimum_value, asset):
        return f"LLM explanation for {asset.name}."


class GroqResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "Grounded explanation."}}]}


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self):
        self.payloads = []

    def post(self, url, json):
        self.payloads.append(json)
        loan = json["input"]["loans"][0]
        decision = {
            "loan_id": loan["loan_id"],
            "rule1_pass": loan["loan_value_eur"] > 25000,
            "rule2_pass": loan["loan_currency"] == loan["expected_currency"],
            "rule3_pass": loan["asset_value"] >= 0.5 * loan["loan_value"],
        }
        return Response({"result": [decision]})


def base_loan(**changes):
    loan = {
        "loan_id": "L1",
        "company_name": "Example Co",
        "loan_currency": "EUR",
        "expected_currency": "EUR",
        "loan_value": 100000,
        "loan_value_eur": 100000,
        "asset_value": 10000,
    }
    return {**loan, **changes}


def profile():
    return {
        "name": "Example Co",
        "source_page": 7,
        "assets": [
            {"name": "Large Asset", "value": 90000},
            {"name": "Small Qualifying Asset", "value": 50000},
        ],
    }


def test_rule1_returns_explainable_template():
    suggestion = suggest(
        base_loan(loan_value_eur=25000),
        {"rule1_pass": False, "rule2_pass": True, "rule3_pass": True},
        {"Example Co": profile()},
        FakeClient(),
        "http://opa",
    )

    assert suggestion.action == "remove_from_report"
    assert suggestion.verified is True


def test_rule2_is_revalidated_with_expected_currency():
    client = FakeClient()
    suggestion = suggest(
        base_loan(loan_currency="USD", asset_value=50000),
        {"rule1_pass": True, "rule2_pass": False, "rule3_pass": True},
        {"Example Co": profile()},
        client,
        "http://opa",
    )

    assert suggestion.action == "change_currency"
    assert suggestion.verified is True
    assert client.payloads[0]["input"]["loans"][0]["loan_currency"] == "EUR"


def test_rule2_and_rule3_failures_get_one_verified_combined_fix():
    client = FakeClient()
    suggestion = suggest(
        base_loan(loan_currency="USD", asset_value=10000),
        {"rule1_pass": True, "rule2_pass": False, "rule3_pass": False},
        {"Example Co": profile()},
        client,
        "http://opa",
    )

    assert suggestion.action == "change_currency_and_asset"
    assert suggestion.asset_name == "Small Qualifying Asset"
    assert suggestion.verified is True


def test_rule3_picks_smallest_qualifying_asset_and_cites_source():
    client = FakeClient()
    suggestion = suggest(
        base_loan(asset_value=10000),
        {"rule1_pass": True, "rule2_pass": True, "rule3_pass": False},
        {"Example Co": profile()},
        client,
        "http://opa",
    )

    assert suggestion.action == "substitute_asset"
    assert suggestion.asset_name == "Small Qualifying Asset"
    assert suggestion.source_page == 7
    assert suggestion.verified is True


def test_rule3_can_use_groq_explanation_boundary():
    suggestion = suggest(
        base_loan(asset_value=10000),
        {"rule1_pass": True, "rule2_pass": True, "rule3_pass": False},
        {"Example Co": profile()},
        FakeClient(),
        "http://opa",
        rag=AssetRag(explainer=FakeExplainer()),
    )

    assert suggestion.explanation == "LLM explanation for Small Qualifying Asset."


def test_groq_explainer_sends_grounded_context(monkeypatch):
    monkeypatch.setenv("GROQ_ENABLED", "true")
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return GroqResponse()

    monkeypatch.setattr("src.rag.httpx.post", fake_post)
    explanation = GroqExplainer().explain(
        "Example Co",
        50000,
        RetrievedAsset("Asset", 60000, 7, "grounded context"),
    )

    assert explanation == "Grounded explanation."
    assert calls[0][0].endswith("/chat/completions")
    assert calls[0][2]["model"] == "llama-3.1-8b-instant"
    assert "Source page: 7" in calls[0][2]["messages"][1]["content"]


def test_profiles_are_indexed_by_company_name(tmp_path):
    path = tmp_path / "companies.json"
    path.write_text('[{"name": "Example Co", "source_page": 1, "assets": []}]', encoding="utf-8")

    assert load_profiles(path)["Example Co"]["source_page"] == 1


def test_rule3_reports_no_qualifying_asset():
    loan = base_loan(loan_value=1_000_000, asset_value=10000)
    small_profile = {**profile(), "assets": [{"name": "Small Asset", "value": 100000}]}

    suggestion = suggest(
        loan,
        {"rule1_pass": True, "rule2_pass": True, "rule3_pass": False},
        {"Example Co": small_profile},
        FakeClient(),
        "http://opa",
    )

    assert suggestion.action == "no_qualifying_asset"
    assert suggestion.asset_name is None
    assert "no asset" in suggestion.explanation.lower()


def test_rule3_exact_half_asset_qualifies():
    exact_profile = {**profile(), "assets": [{"name": "Exact Asset", "value": 50000}]}
    suggestion = suggest(
        base_loan(asset_value=10000),
        {"rule1_pass": True, "rule2_pass": True, "rule3_pass": False},
        {"Example Co": exact_profile},
        FakeClient(),
        "http://opa",
    )

    assert suggestion.asset_name == "Exact Asset"
    assert suggestion.verified is True


def test_cached_suggestion_reuses_result():
    client = FakeClient()
    cache = SuggestionCache()
    loan = base_loan(asset_value=10000)
    verdict = {"rule1_pass": True, "rule2_pass": True, "rule3_pass": False}
    profiles = {"Example Co": profile()}

    first, first_hit = suggest_cached(loan, verdict, profiles, cache, client, "http://opa")
    second, second_hit = suggest_cached({**loan, "loan_id": "L2"}, verdict, profiles, cache, client, "http://opa")

    assert first_hit is False
    assert second_hit is True
    assert second.loan_id == "L2"
    assert len(client.payloads) == 1
    assert cache.hits == 1
