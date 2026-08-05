"""Load the immutable loan CSV and parsed profiles into DuckDB."""

import json
from pathlib import Path

import duckdb


def load_database(
    csv_path: Path,
    profiles_path: Path,
    database_path: Path,
) -> tuple[int, int]:
    """Create a fresh DuckDB database and return loan and company counts."""
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    by_name = {profile["name"]: profile for profile in profiles}
    if len(by_name) != len(profiles):
        raise ValueError("Company names in companies.json are not unique")

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        connection.execute("DROP TABLE IF EXISTS loans")
        connection.execute("DROP TABLE IF EXISTS companies")
        connection.execute(
            """
            CREATE TABLE companies (
                company_id VARCHAR PRIMARY KEY,
                name VARCHAR UNIQUE NOT NULL,
                hq_country VARCHAR NOT NULL,
                industry VARCHAR NOT NULL,
                assets JSON NOT NULL,
                related_entities JSON NOT NULL,
                source_page INTEGER NOT NULL,
                raw_text VARCHAR NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO companies VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    profile["company_id"],
                    profile["name"],
                    profile["hq_country"],
                    profile["industry"],
                    json.dumps(profile["assets"]),
                    json.dumps(profile["related_entities"]),
                    profile["source_page"],
                    profile["raw_text"],
                )
                for profile in profiles
            ],
        )
        connection.execute(
            "CREATE TABLE loans AS SELECT * FROM read_csv_auto(?)",
            [str(csv_path)],
        )
        connection.execute("CREATE INDEX loans_company_idx ON loans(company_name)")

        unresolved = connection.execute(
            """
            SELECT COUNT(*)
            FROM loans AS loan
            LEFT JOIN companies AS company ON company.name = loan.company_name
            WHERE company.name IS NULL
            """
        ).fetchone()[0]
        if unresolved:
            raise ValueError(f"{unresolved} loan rows reference unknown companies")

        country_mismatches = connection.execute(
            """
            SELECT COUNT(*)
            FROM loans AS loan
            JOIN companies AS company ON company.name = loan.company_name
            WHERE loan.hq_country <> company.hq_country
            """
        ).fetchone()[0]
        if country_mismatches:
            raise ValueError(f"{country_mismatches} loan rows have the wrong HQ country")

        loan_count = connection.execute("SELECT COUNT(*) FROM loans").fetchone()[0]
        company_count = connection.execute("SELECT COUNT(*) FROM companies").fetchone()[0]

    return loan_count, company_count


def main() -> None:
    """Load the default CSV and profile artifact into data/loanguard.duckdb."""
    loan_count, company_count = load_database(
        Path("loans.csv"),
        Path("data/companies.json"),
        Path("data/loanguard.duckdb"),
    )
    print(f"Loaded {loan_count} loans for {company_count} companies")


if __name__ == "__main__":
    main()