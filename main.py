import argparse
import csv
import json

from db import open_database, save_verdicts
from opa import evaluate_batch
from review import check_results
from schemas import Loan


def load_loans(path: str) -> list[Loan]:
    with open(path, newline="", encoding="utf-8") as file:
        return [Loan.from_dict(row) for row in csv.DictReader(file)]


def run(path: str, database: str, batch_size: int, opa_url: str | None) -> int:
    loans = load_loans(path)
    connection = open_database(database)
    verdicts = []
    for start in range(0, len(loans), batch_size):
        verdicts.extend(evaluate_batch(loans[start : start + batch_size], opa_url))
    check_results(loans, verdicts)
    save_verdicts(connection, verdicts)
    connection.close()
    return len(verdicts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate loans with Stage 3 policy rules")
    parser.add_argument("--input", default="loans.csv")
    parser.add_argument("--db", default="stage3.db")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--opa-url")
    args = parser.parse_args()
    print(json.dumps({"verdicts": run(args.input, args.db, args.batch_size, args.opa_url)}))