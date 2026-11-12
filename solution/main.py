
import argparse
import json
from pathlib import Path

from solution.database.db import initialize_database
from solution.ingestion.lead_ingestion import ingest_leads
from solution.ingestion.event_ingestion import ingest_events
from solution.reporting.reports import generate_reports


def main():
    parser = argparse.ArgumentParser(
        description="Interaction Ledger and Reporting Pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Ingest leads and events from a data drop",
    )
    ingest_parser.add_argument("drop_path")

    report_parser = subparsers.add_parser(
        "report",
        help="Generate the five required reports",
    )
    report_parser.add_argument(
        "--out",
        default="reports",
        help="Output directory",
    )

    args = parser.parse_args()
    initialize_database()

    if args.command == "ingest":
        drop = Path(args.drop_path)

        lead_result = ingest_leads(drop)
        event_result = ingest_events(drop)

        print("LEAD INGESTION")
        print(json.dumps(lead_result, indent=2))

        print("\nEVENT INGESTION")
        print(json.dumps(event_result, indent=2))

    elif args.command == "report":
        result = generate_reports(args.out)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
