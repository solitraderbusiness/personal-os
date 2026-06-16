"""Terminal front-end: talk to the assistant locally and watch memory form.

Run from the repo root:   venv/bin/python -m scripts.chat

Plain lines are sent to the assistant. Local slash commands (handled here, no engine):
  /recall <q>     show what hybrid search retrieves for <q> (with sources)
  /snapshot       rebuild + show the injection snapshot (meta + head)
  /reindex [--reset]   rebuild the vector index from all sources
  /stats          index statistics (chunk counts, backend, vector mode)
  /feedback <useful|noise> <item>   record salience feedback
  /help           this help
  /quit | /exit   leave
"""
from __future__ import annotations

import sys

from . import assistant as _assistant
from . import config as _config
from . import feedback as _feedback
from . import index as _index
from . import paths as _paths
from . import snapshot as _snapshot

BANNER = "personal-os — terminal. Type a message, or /help for commands. Ctrl-D to quit."


def _print_reply(reply: dict) -> None:
    print("\n" + reply["answer"].strip() + "\n")
    cites = reply.get("citations") or []
    if cites:
        ids = " ".join(f"[{c['source_id']}]" for c in cites[:6])
        print(f"  sources: {ids}  (confidence: {reply.get('confidence')})")
    if reply.get("engine_error"):
        print("  (engine error — nothing was saved for this turn)")


def _handle_slash(line: str) -> bool:
    parts = line.strip().split()
    cmd = parts[0].lower()
    rest = line.strip()[len(cmd):].strip()
    if cmd in ("/quit", "/exit"):
        return False
    if cmd == "/help":
        print(__doc__)
    elif cmd == "/recall":
        if not rest:
            print("usage: /recall <query>")
        else:
            from . import recall as _recall
            r = _recall.recall(rest)
            print(f"  found={r['found']} confidence={r['confidence']} top_sim={r['top_sim']}")
            for h in r["hits"]:
                print(f"  [{h['vec_sim']:.2f} kw={h['kw']}] ({h['source_id']}) {h['text'][:100]!r}")
    elif cmd == "/snapshot":
        s = _snapshot.build_snapshot()
        print(f"  generated_at={s['generated_at']} tokens~{s['token_estimate']}/{s['token_cap']} "
              f"over_cap={s['over_cap']} omitted={s['omitted']}")
        print("  sources:", ", ".join(s["sources"]) or "(none — fill authored/ files)")
        print("---\n" + s["body"][:1200])
    elif cmd == "/reindex":
        counts = _index.reindex_all(reset=("--reset" in parts))
        print("  reindexed:", counts)
    elif cmd == "/stats":
        import json
        print(json.dumps(_index.stats(), indent=2))
    elif cmd == "/feedback":
        fp = rest.split(None, 1)
        if len(fp) < 2:
            print("usage: /feedback <useful|noise> <item>")
        else:
            try:
                res = _feedback.record_feedback(fp[1], fp[0])
                print(f"  recorded {res['verdict']} at {res['recorded_at']}")
            except ValueError as e:
                print(f"  {e}")
    else:
        print(f"  unknown command {cmd!r} — /help for options")
    return True


def main() -> None:
    if not _paths.config_file().exists():
        print("No config/config.yml found. Run ./install.sh first.", file=sys.stderr)
        raise SystemExit(1)
    print(BANNER)
    print(f"instance: {_config.instance_name()}\n")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye.")
            break
        if not line:
            continue
        if line.startswith("/"):
            if not _handle_slash(line):
                print("bye.")
                break
            continue
        reply = _assistant.respond(line, conversation_id="terminal")
        _print_reply(reply)


if __name__ == "__main__":
    main()
