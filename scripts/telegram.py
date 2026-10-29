"""Καθημερινή αποστολή στο Telegram: ο αγώνας της ημέρας (με την εικόνα του) και τα πιο πιθανά σημεία.

Χρειάζεται δύο «μυστικά» στο GitHub (Settings → Secrets and variables → Actions):
  TELEGRAM_BOT_TOKEN   ο κωδικός που δίνει ο @BotFather
  TELEGRAM_CHAT_ID     το κανάλι, π.χ. @samuraibet (το bot πρέπει να είναι διαχειριστής του καναλιού)

Στέλνει μία φορά τη μέρα, στην πρώτη πλήρη ενημέρωση μετά τις 07:00 ώρα Ελλάδας.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import pathlib
import urllib.error
import urllib.request
import uuid

import static_pages as SP

E = html.escape
API = "https://api.telegram.org/bot{token}/{method}"
W = {"Champions League": 10, "Europa League": 7, "Conference League": 6, "Premier League": 6, "Super League": 6,
     "La Liga": 5, "Serie A": 5, "Bundesliga": 5, "Ligue 1": 4, "EuroLeague": 6, "NBA": 4}


def is_greek(s: str) -> bool:
    return any("Α" <= c <= "ω" or c in "άέήίόύώ" for c in s)


def importance(m, p) -> float:
    v = (W.get(m["league"], 3) + (4 if is_greek(m["home"]) or is_greek(m["away"]) else 0)
         + 3 * (1 - abs(p["H"] - p["A"])))
    pos = [q for q in ((m.get("info") or {}).get("pos") or []) if q]
    if len(pos) == 2:                      # ματς ψηλά στη βαθμολογία μετράει περισσότερο
        v += 4 * (1 - (pos[0]["rank"] + pos[1]["rank"] - 2) / (2 * max(pos[0]["of"] - 1, 1)))
    return v


def call(token, method, data=None, files=None):
    url = API.format(token=token, method=method)
    if files:
        boundary = uuid.uuid4().hex
        body = b""
        for k, v in (data or {}).items():
            body += f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
        for k, (name, blob, ctype) in files.items():
            body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n").encode() + blob + b"\r\n"
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    else:
        req = urllib.request.Request(url, data=json.dumps(data).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"ok": False, "description": f"{e.code} {e.read().decode(errors='replace')[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "description": str(e)}


def build_messages(matches, now, base):
    """Επιστρέφει (κείμενο λεζάντας, διαδρομή εικόνας ή None, κείμενο λίστας) ή None αν δεν υπάρχουν αγώνες σήμερα."""
    today = now.astimezone(SP.ATHENS).date()
    todays = []
    for m in matches:
        k = SP.local(m["kickoff"])
        if k.date() == today and dt.datetime.fromisoformat(m["kickoff"]) > now:
            todays.append((m, SP.probs_of(m)))
    if not todays:
        return None
    link = lambda m: f"{base}{m['page']}" if base and m.get("page") else base or ""
    t = lambda m: f"{SP.local(m['kickoff']):%H:%M}"

    big, bp = max(todays, key=lambda x: importance(*x))
    if big["sport"] == "football":
        sc = bp["top"]
        line = (f"1: <b>{SP.pct(bp['H'])}</b> · Χ: <b>{SP.pct(bp['D'])}</b> · 2: <b>{SP.pct(bp['A'])}</b>\n"
                f"Πιθανότερο σκορ {sc[0]}-{sc[1]} · Over 2,5: {SP.pct(bp['O25'])}")
    else:
        line = (f"{E(big['home'])}: <b>{SP.pct(bp['H'])}</b> · {E(big['away'])}: <b>{SP.pct(bp['A'])}</b>\n"
                f"Αναμενόμενο σκορ {round(big['expHome'])}-{round(big['expAway'])}")
    caption = (f"⚔️ <b>Ο αγώνας της ημέρας</b>\n\n<b>{E(big['home'])} – {E(big['away'])}</b>\n"
               f"{E(big['league'])} · {t(big)}\n\n{line}\n\n"
               + (f'👉 <a href="{E(link(big))}">Ανάλυση και φόρμα</a>' if link(big) else ""))
    img = None
    if big.get("page"):
        cand = pathlib.Path(SP.HERE.parent / "site" / "og" / (big["page"].split("/")[-1].replace(".html", ".png")))
        img = cand if cand.exists() else None

    picks = []
    for m, p in todays:
        k, pr, team = SP.best(m, p)
        picks.append((pr, k, team, m))
    picks.sort(key=lambda x: -x[0])
    # προτίμηση στις μεγάλες διοργανώσεις και ως 2 ανά διοργάνωση, για να μη γεμίζει η λίστα με άγνωστα ματς
    main = [x for x in picks if x[3]["league"] in W]
    pool, chosen, per = (main if len(main) >= 5 else picks), [], {}
    for x in pool:
        if per.get(x[3]["league"], 0) < 2 and x[0] >= 0.5:
            chosen.append(x); per[x[3]["league"]] = per.get(x[3]["league"], 0) + 1
    chosen += [x for x in pool if x not in chosen][:max(0, 5 - len(chosen))]
    picks = sorted(chosen[:5], key=lambda x: -x[0])
    d = now.astimezone(SP.ATHENS)
    rows = []
    for i, (pr, k, team, m) in enumerate(picks[:5], 1):
        what = "Ισοπαλία" if k == "Χ" else f"{team} νίκη"
        rows.append(f"{i}. <b>{E(what)}</b>: {SP.pct(pr)} (δίκαιη {SP.fair(pr)})\n"
                    f"     {E(m['home'])} – {E(m['away'])} · {t(m)} · {E(m['league'])}")
    text = (f"📋 <b>Τα πιο πιθανά σημεία σήμερα</b>\n{SP.DAYS[d.weekday()]} {d.day} {SP.MONTHS[d.month - 1]}\n\n" + "\n".join(rows))
    fb = [(m, p) for m, p in todays if m["sport"] == "football"]
    if fb:
        gm, gp = max(fb, key=lambda x: x[1]["O25"])
        text += f"\n\n⚽ <b>Περισσότερα γκολ:</b> {E(gm['home'])} – {E(gm['away'])}, Over 2,5 {SP.pct(gp['O25'])}"
    if len(picks) >= 3:
        P = picks[0][0] * picks[1][0] * picks[2][0]
        text += (f"\n🎟 Τα 3 πρώτα σε παρολί: {SP.pct(P)}, δίκαιη απόδοση {SP.fair(P)}. "
                 "Φτιάξε το δικό σου δελτίο στο site.")
    if base:
        text += f'\n\n🔗 <a href="{E(base)}">Όλοι οι {len(todays)} αγώνες της ημέρας</a>'
    text += "\n\n<i>18+ · Πιθανότητες από στατιστικό μοντέλο, όχι σίγουρα στοιχήματα. Παίξε υπεύθυνα.</i>"
    return caption, img, text


def send_daily(matches, history, now, base) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return
    local = now.astimezone(SP.ATHENS)
    today = local.date().isoformat()
    if history.get("tg") == today or local.hour < 7:
        return
    msgs = build_messages(matches, now, base)
    if not msgs:
        print("• Telegram: δεν υπάρχουν αγώνες σήμερα")
        return
    caption, img, text = msgs
    if img:
        r = call(token, "sendPhoto", {"chat_id": chat, "caption": caption, "parse_mode": "HTML"},
                 {"photo": (img.name, img.read_bytes(), "image/png")})
    else:
        r = call(token, "sendMessage", {"chat_id": chat, "text": caption, "parse_mode": "HTML"})
    if not r.get("ok"):
        print(f"  ! Telegram: {r.get('description')}")
        return
    r = call(token, "sendMessage", {"chat_id": chat, "text": text, "parse_mode": "HTML",
                                    "link_preview_options": {"is_disabled": True}})
    if not r.get("ok"):
        print(f"  ! Telegram (λίστα): {r.get('description')}")
    history["tg"] = today
    print("• Telegram: στάλθηκαν τα σημερινά")
