"""Country-to-currency reference data and consistency checks."""

COUNTRY_CURRENCY = {
    "Germany": "EUR",
    "Ireland": "EUR",
    "Spain": "EUR",
    "France": "EUR",
    "Italy": "EUR",
    "Netherlands": "EUR",
    "Portugal": "EUR",
    "Belgium": "EUR",
    "Austria": "EUR",
    "Finland": "EUR",
    "Luxembourg": "EUR",
    "United Kingdom": "GBP",
    "United States": "USD",
    "Switzerland": "CHF",
    "Sweden": "SEK",
    "Canada": "CAD",
    "Poland": "PLN",
    "Japan": "JPY",
}


def currency_for(country: str) -> str:
    """Return the reporting currency for a known country."""
    try:
        return COUNTRY_CURRENCY[country]
    except KeyError as exc:
        raise ValueError(f"Unknown HQ country: {country}") from exc


def validate_observed_mapping(observed: dict[str, str]) -> None:
    """Ensure observed PDF country/currency pairs match the reference table."""
    for country, currency in observed.items():
        if currency_for(country) != currency:
            raise ValueError(
                f"Currency mismatch for {country}: expected "
                f"{currency_for(country)}, observed {currency}"
            )

    missing = set(observed) - set(COUNTRY_CURRENCY)
    if missing:
        raise ValueError(f"Countries missing from reference table: {sorted(missing)}")