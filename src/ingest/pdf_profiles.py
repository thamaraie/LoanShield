"""Extract company profiles from the supplied reference PDF."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

import pdfplumber

from src.reference.currencies import validate_observed_mapping


HEADING = re.compile(r"^(C\d{3}) — (.+)$")
ASSET = re.compile(r"^(.+?) ([\d,]+) ([A-Z]{3})$")


@dataclass
class Asset:
    """A pledgeable company asset from one PDF profile."""

    name: str
    value: int
    currency: str


@dataclass
class Company:
    """The parsed, source-linked representation of a company profile."""

    company_id: str
    name: str
    hq_country: str
    industry: str
    assets: list[Asset]
    related_entities: list[str]
    source_page: int
    raw_text: str


def parse_profiles(pdf_path: Path) -> list[Company]:
    """Parse all company profiles from a text-based reference PDF."""
    profiles: list[Company] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines or not HEADING.match(lines[0]):
                continue
            profiles.append(parse_profile(lines, page_number, text))

    validate_profiles(profiles)
    return profiles


def parse_profile(lines: list[str], source_page: int, raw_text: str) -> Company:
    """Parse one profile page using the fixed headings in the PDF."""
    heading = HEADING.match(lines[0])
    if not heading:
        raise ValueError(f"Invalid profile heading on page {source_page}")

    country_line = next((line for line in lines if line.startswith("Headquarters country ")), None)
    industry_line = next((line for line in lines if line.startswith("Industry ")), None)
    if not country_line or not industry_line:
        raise ValueError(f"Missing profile fields on page {source_page}")

    assets: list[Asset] = []
    for line in lines:
        match = ASSET.match(line)
        if match:
            assets.append(Asset(match.group(1), int(match.group(2).replace(",", "")), match.group(3)))

    related_entities: list[str] = []
    marker = "The following entities may appear as the recorded owner of an asset pledged by "
    for line in lines:
        if marker in line and ":" in line:
            related_entities = [item.strip().rstrip(".") for item in line.split(":", 1)[1].split(",")]

    return Company(
        company_id=heading.group(1),
        name=heading.group(2),
        hq_country=country_line.removeprefix("Headquarters country "),
        industry=industry_line.removeprefix("Industry "),
        assets=assets,
        related_entities=related_entities,
        source_page=source_page,
        raw_text=raw_text,
    )


def validate_profiles(profiles: list[Company]) -> None:
    """Fail when the PDF profiles or their currencies are incomplete or invalid."""
    if len(profiles) != 100:
        raise ValueError(f"Expected 100 profiles, found {len(profiles)}")
    if len({profile.company_id for profile in profiles}) != 100:
        raise ValueError("Company IDs are not unique")
    if len({profile.name for profile in profiles}) != 100:
        raise ValueError("Company names are not unique")

    observed: dict[str, str] = {}
    for profile in profiles:
        if not profile.assets:
            raise ValueError(f"No assets found for {profile.name}")
        for asset in profile.assets:
            if not isinstance(asset.value, int) or len(asset.currency) != 3:
                raise ValueError(f"Invalid asset in {profile.name}: {asset}")
            observed.setdefault(profile.hq_country, asset.currency)
            if observed[profile.hq_country] != asset.currency:
                raise ValueError(f"Mixed asset currencies for {profile.name}")
    validate_observed_mapping(observed)


def write_profiles(profiles: list[Company], output_path: Path) -> None:
    """Write profiles as readable, stable JSON for downstream stages."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for profile in profiles:
        record = asdict(profile)
        records.append(record)
    output_path.write_text(json.dumps(records, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> None:
    """Extract the default reference PDF into data/companies.json."""
    profiles = parse_profiles(Path("company-reference.pdf"))
    write_profiles(profiles, Path("data/companies.json"))
    print(f"Wrote {len(profiles)} company profiles")


if __name__ == "__main__":
    main()