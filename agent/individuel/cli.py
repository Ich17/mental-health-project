"""Lancer une délibération depuis le terminal.

    python -m agent.individuel.cli                         # run « semaine », mode auto
    python -m agent.individuel.cli --kind jour
    python -m agent.individuel.cli --kind chat --question "Pourquoi je suis à plat le jeudi ?"
    python -m agent.individuel.cli --scripted              # sans clé API
    python -m agent.individuel.cli --trace                 # affiche aussi les appels d'outils
    python -m agent.individuel.cli --persona closing       # faux positif : pic de clôture puis retour à la normale
"""
import argparse
import json
import os

from dotenv import load_dotenv

COLORS = {"detection": "\033[36m", "analyse": "\033[35m", "action": "\033[32m",
          "orchestrateur": "\033[33m", "personne": "\033[34m",
          "observateur": "\033[36m", "conseiller": "\033[32m"}
RESET, DIM = "\033[0m", "\033[2m"


def show(msg: dict):
    c = COLORS.get(msg["author"], "")
    print(f"\n{c}● {msg['author']} → {msg['to']}  [{msg['kind']}]{RESET}")
    print(msg["content"])
    if msg.get("data"):
        print(f"{DIM}{json.dumps(msg['data'], ensure_ascii=False)}{RESET}")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=os.getenv("USER_ID", "ichane"))
    ap.add_argument("--kind", default="semaine", choices=["semaine", "jour", "chat"])
    ap.add_argument("--question")
    ap.add_argument("--scripted", action="store_true", help="cerveau de démo, sans appel LLM")
    ap.add_argument("--trace", action="store_true", help="affiche les appels d'outils")
    ap.add_argument("--persona", choices=["closing"], help="profil simulé (défaut : celui de contracts.py)")
    args = ap.parse_args()
    if args.scripted:
        os.environ["AGENT_MODE"] = "scripted"

    from agent.individuel import council, personas

    if args.persona:
        personas.use_persona(args.persona)

    result = council.run(args.user, args.kind, args.question, on_message=show)
    print(f"\n{DIM}run #{result['run_id']} : {result['status']}, "
          f"{len(result['actions'])} action(s) proposée(s){RESET}")
    if args.trace:
        for t in result["tool_trace"]:
            print(f"{DIM}  {t['agent']}.{t['tool']}({t['input']}){RESET}")


if __name__ == "__main__":
    main()
