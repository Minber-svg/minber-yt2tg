#!/usr/bin/env python3
"""Minber KZ YouTube арнасындағы жаңа видеоларды Telegram арнаға жариялайды.

Тек Python стандартты кітапханасы қолданылады (қосымша пакет керек емес).

Орта айнымалылары (environment variables):
  TELEGRAM_BOT_TOKEN  – @BotFather берген Minber_bot токені (міндетті)
  TELEGRAM_CHAT_ID    – Telegram арна: @atauy немесе -100... ID (міндетті)
  YOUTUBE_CHANNEL_ID  – YouTube арна ID (әдепкі: Minber KZ)
  INCLUDE_SHORTS      – "true" / "false" (әдепкі: true)
  STATE_FILE          – жарияланған видеолар тізімі сақталатын файл
  DRY_RUN             – "true" болса, Telegram-ға жібермей, тек экранға шығарады
  FEED_FILE           – (тест үшін) RSS-ті интернеттен емес, файлдан оқу
"""
import html
import json
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

CHANNEL_ID = os.environ.get("YOUTUBE_CHANNEL_ID", "UCstUsyjSW_N83GwdtW5T9nw")
FEED_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
INCLUDE_SHORTS = os.environ.get("INCLUDE_SHORTS", "true").lower() == "true"
STATE_FILE = os.environ.get("STATE_FILE", "posted.json")
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
FEED_FILE = os.environ.get("FEED_FILE")

# Хабарлама баптаулары
DESCRIPTION_CHARS = 300          # сипаттамадан қанша таңба көрсетіледі
HASHTAGS = "#minber"             # хабарлама соңындағы хэштег ("" – өшіру)
BUTTON_TEXT = "▶️ Көру"
SHORTS_BUTTON_TEXT = "▶️ Shorts көру"
MAX_REMEMBERED = 500             # state файлында сақталатын ID саны

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


def load_feed() -> str:
    if FEED_FILE:
        with open(FEED_FILE, encoding="utf-8") as f:
            return f.read()
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    videos = []
    for e in root.findall("atom:entry", NS):
        vid = e.findtext("yt:videoId", default="", namespaces=NS)
        link_el = e.find("atom:link[@rel='alternate']", NS)
        link = link_el.get("href") if link_el is not None else f"https://www.youtube.com/watch?v={vid}"
        group = e.find("media:group", NS)
        desc = ""
        thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        if group is not None:
            desc = group.findtext("media:description", default="", namespaces=NS) or ""
            t = group.find("media:thumbnail", NS)
            if t is not None and t.get("url"):
                thumb = t.get("url")
        videos.append({
            "id": vid,
            "title": e.findtext("atom:title", default="", namespaces=NS).strip(),
            "link": link,
            "published": e.findtext("atom:published", default="", namespaces=NS),
            "description": desc.strip(),
            "thumbnail": thumb,
            "is_short": "/shorts/" in link,
        })
    return videos


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"initialized": False, "posted": []}
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    state["posted"] = state["posted"][-MAX_REMEMBERED:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_caption(v: dict) -> str:
    parts = [f"<b>{html.escape(v['title'])}</b>"]
    desc = v["description"]
    if desc and DESCRIPTION_CHARS > 0:
        if len(desc) > DESCRIPTION_CHARS:
            desc = desc[:DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
        parts.append(html.escape(desc))
    parts.append(html.escape(v["link"]))
    if HASHTAGS:
        parts.append(HASHTAGS)
    caption = "\n\n".join(parts)
    # Telegram фото жазбасының шегі – 1024 таңба
    if len(caption) > 1024:
        caption = "\n\n".join([parts[0], html.escape(v["link"]), HASHTAGS]).strip()
    return caption


def tg_call(method: str, payload: dict) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(payload).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as err:
        return json.loads(err.read().decode() or "{}")


def post(v: dict) -> bool:
    caption = build_caption(v)
    keyboard = json.dumps({"inline_keyboard": [[{
        "text": SHORTS_BUTTON_TEXT if v["is_short"] else BUTTON_TEXT,
        "url": v["link"],
    }]]})
    if DRY_RUN:
        print("--- DRY RUN ---\n" + caption + "\n")
        return True
    res = tg_call("sendPhoto", {
        "chat_id": CHAT_ID, "photo": v["thumbnail"], "caption": caption,
        "parse_mode": "HTML", "reply_markup": keyboard,
    })
    if not res.get("ok"):
        print(f"sendPhoto сәтсіз ({res.get('description')}), мәтінмен жіберемін", file=sys.stderr)
        res = tg_call("sendMessage", {
            "chat_id": CHAT_ID, "text": caption, "parse_mode": "HTML",
            "reply_markup": keyboard,
        })
    if not res.get("ok"):
        print(f"ҚАТЕ {v['id']}: {res}", file=sys.stderr)
        return False
    return True


def main() -> int:
    if not DRY_RUN and (not BOT_TOKEN or not CHAT_ID):
        print("TELEGRAM_BOT_TOKEN және TELEGRAM_CHAT_ID керек", file=sys.stderr)
        return 1

    videos = parse_feed(load_feed())
    state = load_state()
    posted = set(state["posted"])

    # Алғашқы іске қосу: бар видеоларды жарияламай, тек "көрдім" деп белгілейміз,
    # әйтпесе арнаға бірден 15 ескі видео түсіп кетеді.
    if not state.get("initialized"):
        state["posted"] = [v["id"] for v in reversed(videos)]
        state["initialized"] = True
        save_state(state)
        print(f"Алғашқы іске қосу: {len(videos)} бар видео белгіленді, ештеңе жарияланбады.")
        return 0

    new = [v for v in reversed(videos) if v["id"] not in posted]  # ескісінен жаңасына
    failed = 0
    for v in new:
        if v["is_short"] and not INCLUDE_SHORTS:
            print(f"Shorts өткізілді: {v['title']}")
            state["posted"].append(v["id"])
            continue
        if post(v):
            print(f"Жарияланды: {v['title']}")
            state["posted"].append(v["id"])
        else:
            failed += 1  # келесі жолы қайта тырысады
    save_state(state)
    if not new:
        print("Жаңа видео жоқ.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
