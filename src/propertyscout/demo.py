"""Run the three deterministic MVP routes from the command line."""

from __future__ import annotations

import argparse
from datetime import datetime

from langgraph.types import Command

from propertyscout.analyst import create_nebius_reasoner
from propertyscout.bootstrap import initial_state
from propertyscout.graph import build_graph
from propertyscout.meeting_intelligence import create_nebius_meeting_brief_service
from propertyscout.persistence import open_sqlite_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PropertyScout MVP routes")
    parser.add_argument(
        "--llm",
        action="store_true",
        help="Use the configured Nebius model instead of the deterministic reasoner",
    )
    parser.add_argument(
        "--sqlite",
        metavar="PATH",
        help="Persist LangGraph checkpoints in this SQLite file",
    )
    args = parser.parse_args()

    graph_options = {
        "reasoner": create_nebius_reasoner() if args.llm else None,
        "meeting_brief_service": (
            create_nebius_meeting_brief_service() if args.llm else None
        ),
    }
    if args.sqlite:
        with open_sqlite_graph(args.sqlite, **graph_options) as graph:
            run_demo(graph)
    else:
        run_demo(build_graph(**graph_options))


def run_demo(graph) -> None:
    """Run the three fixture routes using an already compiled graph."""

    for property_key in ("reject", "research", "shortlist"):
        thread_id = f"demo-{property_key}"
        config = {"configurable": {"thread_id": thread_id}}
        result = graph.invoke(initial_state(property_key), config)

        if "__interrupt__" in result:
            print(f"{property_key}: paused for shortlist approval")
            result = graph.invoke(
                Command(
                    resume={
                        "decision": "approved",
                        "decided_by": "demo-investor",
                        "feedback": "Approved by the deterministic demo.",
                    }
                ),
                config,
            )

        if "__interrupt__" in result and result.get("contact_candidates"):
            print(f"{property_key}: paused for contact resolution")
            result = graph.invoke(
                Command(
                    resume={
                        "contact_id": str(result["contact_candidates"][0].contact_id),
                    }
                ),
                config,
            )

        if "__interrupt__" in result and result.get("outreach_draft"):
            print(f"{property_key}: paused for outreach approval")
            result = graph.invoke(
                Command(
                    resume={
                        "decision": "approved",
                        "decided_by": "demo-investor",
                    }
                ),
                config,
            )

        if "__interrupt__" in result and result.get("email_send_receipt"):
            print(f"{property_key}: paused while awaiting broker reply")
            result = graph.invoke(
                Command(
                    resume={
                        "message_id": "demo-reply-1",
                        "sender_email": result["selected_contact"].email,
                        "received_at": datetime.now().astimezone().isoformat(),
                        "body": "Wednesday at 14:00 works for me.",
                        "proposed_times": ["2026-10-28T14:00:00+01:00"],
                    }
                ),
                config,
            )

        print(f"{property_key}: {result['outcome'].value}")


if __name__ == "__main__":
    main()
