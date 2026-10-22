"""Lancer une délibération d'équipe depuis le terminal.

    python -m agent.team.cli --scripted
"""
import argparse
import os

from dotenv import load_dotenv

from agent.individuel.cli import show


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--scripted", action="store_true", help="cerveau de démo, sans appel LLM")
    args = ap.parse_args()
    if args.scripted:
        os.environ["AGENT_MODE"] = "scripted"
    from agent.team import council

    r = council.run(on_message=show)
    print(f"\nrun #{r['run_id']} : {r['status']}, {len(r['rules'])} règle(s) suggérée(s)")


if __name__ == "__main__":
    main()
