import pytest

from src.reference.currencies import COUNTRY_CURRENCY, currency_for, validate_observed_mapping


def test_known_currencies_are_available():
    assert len(COUNTRY_CURRENCY) == 18
    assert currency_for("Germany") == "EUR"
    assert currency_for("Japan") == "JPY"


def test_unknown_country_fails():
    with pytest.raises(ValueError, match="Unknown HQ country"):
        currency_for("Atlantis")


def test_observed_currency_mismatch_fails():
    with pytest.raises(ValueError, match="Currency mismatch"):
        validate_observed_mapping({"Germany": "USD"})