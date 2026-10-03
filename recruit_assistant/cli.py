import argparse
import json

from recruit_assistant.models import ResearchRequest
from recruit_assistant.research import run_research
from recruit_assistant.storage import get_job


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Agent-callable tools for the evidence-first recruiting assistant."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    research = subparsers.add_parser(
        "research-job",
        help="Research candidate-provided profiles and analyze job fit with local Qwen.",
    )
    research.add_argument("--job-id", required=True)
    research.add_argument(
        "--consent-confirmed",
        action="store_true",
        help="Confirm candidates received notice/consented to professional-source research.",
    )

    args = parser.parse_args()
    if args.command == "research-job":
        job = get_job(args.job_id)
        run = run_research(
            job,
            ResearchRequest(consent_confirmed=args.consent_confirmed),
        )
        print(run.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
