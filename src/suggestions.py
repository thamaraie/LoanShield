"""Create deterministic, OPA-verified suggestions for failed loans."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import httpx

from src.evaluate import evaluate_batch
from src.rag import AssetRag


@dataclass(frozen=True)
class Suggestion:
    loan_id: str
    rule: int
    action: str
    explanation: str
    source_page: int | None
    asset_name: str | None
    verified: bool


class SuggestionCache:
    """Cache suggestions by company, failed rule, and safe value bucket."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, int, int], Suggestion] = {}
        self.hits = 0
        self.misses = 0

    def key(
        self,
        loan: dict[str, Any],
        rule: int,
        profile: dict[str, Any],
        rule3_failed: bool = False,
    ) -> tuple[str, int, int]:
        """Return a key whose bucket preserves the selected asset outcome."""
        if rule == 3 or (rule == 2 and rule3_failed):
            qualifying_count = sum(
                asset["value"] >= 0.5 * loan["loan_value"]
                for asset in profile["assets"]
            )
            bucket = qualifying_count
        else:
            bucket = 0
        return loan["company_name"], rule, bucket

    def get(self, key: tuple[str, int, int]) -> Suggestion | None:
        suggestion = self._items.get(key)
        if suggestion is None:
            self.misses += 1
        else:
            self.hits += 1
        return suggestion

    def put(self, key: tuple[str, int, int], suggestion: Suggestion) -> None:
        self._items[key] = suggestion

    @property
    def opa_calls(self) -> int:
        """Return cache misses that required OPA revalidation."""
        return sum(
            suggestion.rule in (2, 3) and suggestion.verified
            for suggestion in self._items.values()
        )


def load_profiles(path: Path) -> dict[str, dict[str, Any]]:
    """Load company profiles once and index them by company name."""
    profiles = json.loads(path.read_text(encoding="utf-8"))
    return {profile["name"]: profile for profile in profiles}


def _replacement_asset(profile: dict[str, Any], minimum_value: float) -> dict[str, Any] | None:
    """Return the smallest profile asset meeting the coverage threshold."""
    asset, _ = AssetRag().suggest(profile, minimum_value)
    if asset is None:
        return None
    return {"name": asset.name, "value": asset.value}


def _revalidate(
    loan: dict[str, Any],
    client: httpx.Client,
    opa_url: str,
) -> bool:
    """Return whether OPA accepts all three rules for a corrected loan."""
    decision = evaluate_batch([loan], client, opa_url)[0]
    return all(decision[f"rule{rule}_pass"] for rule in (1, 2, 3))


def suggest(
    loan: dict[str, Any],
    verdict: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    client: httpx.Client,
    opa_url: str,
    rag: AssetRag | None = None,
) -> Suggestion:
    """Return one useful suggestion for the first failed rule."""
    rag = rag or AssetRag()
    if not verdict["rule1_pass"]:
        return Suggestion(
            loan_id=loan["loan_id"],
            rule=1,
            action="remove_from_report",
            explanation="Loan value is not greater than EUR 25,000; remove it from the compliance report.",
            source_page=None,
            asset_name=None,
            verified=True,
        )

    if not verdict["rule2_pass"]:
        corrected = {**loan, "loan_currency": loan["expected_currency"]}
        asset_name = None
        source_page = None
        action = "change_currency"
        explanation = f"Change the loan currency to {loan['expected_currency']}."
        if not verdict["rule3_pass"]:
            profile = profiles[loan["company_name"]]
            asset, asset_explanation = rag.suggest(profile, 0.5 * loan["loan_value"])
            if asset is None:
                return Suggestion(
                    loan_id=loan["loan_id"],
                    rule=2,
                    action="no_qualifying_asset",
                    explanation=(
                        f"Change the loan currency to {loan['expected_currency']}, "
                        f"but no profile asset covers 50% of the loan."
                    ),
                    source_page=profile["source_page"],
                    asset_name=None,
                    verified=False,
                )
            corrected["asset_value"] = asset.value
            asset_name = asset.name
            source_page = asset.source_page
            action = "change_currency_and_asset"
            explanation = (
                f"Change the loan currency to {loan['expected_currency']} and use "
                f"{asset_explanation}"
            )
        verified = _revalidate(corrected, client, opa_url)
        return Suggestion(
            loan_id=loan["loan_id"],
            rule=2,
            action=action,
            explanation=explanation,
            source_page=source_page,
            asset_name=asset_name,
            verified=verified,
        )

    profile = profiles[loan["company_name"]]
    minimum_value = 0.5 * loan["loan_value"]
    asset, explanation = rag.suggest(profile, minimum_value)
    if asset is None:
        return Suggestion(
            loan_id=loan["loan_id"],
            rule=3,
            action="no_qualifying_asset",
            explanation=f"No asset in the {loan['company_name']} profile covers EUR {minimum_value:,.0f}.",
            source_page=profile["source_page"],
            asset_name=None,
            verified=False,
        )

    corrected = {**loan, "asset_value": asset.value}
    verified = _revalidate(corrected, client, opa_url)
    return Suggestion(
        loan_id=loan["loan_id"],
        rule=3,
        action="substitute_asset",
        explanation=explanation,
        source_page=asset.source_page,
        asset_name=asset.name,
        verified=verified,
    )


def suggest_cached(
    loan: dict[str, Any],
    verdict: dict[str, Any],
    profiles: dict[str, dict[str, Any]],
    cache: SuggestionCache,
    client: httpx.Client,
    opa_url: str,
    rag: AssetRag | None = None,
) -> tuple[Suggestion, bool]:
    """Create or reuse a suggestion and return it with its cache-hit flag."""
    rule = next(
        rule for rule in (1, 2, 3) if not verdict[f"rule{rule}_pass"]
    )
    profile = profiles.get(loan["company_name"], {"assets": []})
    key = cache.key(loan, rule, profile, not verdict["rule3_pass"])
    cached = cache.get(key)
    if cached is not None:
        return Suggestion(**{**cached.__dict__, "loan_id": loan["loan_id"]}), True

    suggestion = suggest(loan, verdict, profiles, client, opa_url, rag)
    cache.put(key, suggestion)
    return suggestion, False
