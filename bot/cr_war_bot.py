import os
import json
import logging
import re
import threading
from urllib.parse import quote, unquote
import time
import requests
import schedule
from datetime import datetime


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Zorunlu ortam değişkeni eksik: {name}")
    return value

CR_API_KEY = required_env("CR_API_KEY")
CLAN_TAG = required_env("CLAN_TAG")
TG_BOT_TOKEN = required_env("TG_BOT_TOKEN")
TG_CHAT_ID = required_env("TG_CHAT_ID")

MAX_DECKS_PER_DAY = 4

NOTE_10 = "Not: 3 kere hakkını 10’dan sonraya bırakmak kurallarımız gereği çıkarılma sebebidir."
NOTE_1230 = "Not: 4 savaş gününün 2'sinde savaşını yapmamak kurallarımız gereği çıkarılma sebebidir."

def send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }
    try:
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        raise RuntimeError("Telegram API isteği başarısız oldu") from None

logger = logging.getLogger(__name__)


def safe_api_error_body(response) -> str:
    # Log only diagnostic fields; never dump headers, requests or raw bodies.
    try:
        body = response.json()
    except ValueError:
        return "JSON olmayan hata gövdesi güvenlik nedeniyle kaydedilmedi"
    if not isinstance(body, dict):
        return "Beklenmeyen hata gövdesi güvenlik nedeniyle kaydedilmedi"

    details = {}
    for field in ("reason", "message"):
        value = body.get(field)
        if not isinstance(value, str):
            continue
        for secret in (CR_API_KEY, TG_BOT_TOKEN):
            if secret:
                for variant in (secret, quote(secret, safe="")):
                    value = value.replace(variant, "[REDACTED]")
        value = re.sub(r"eyJ[A-Za-z0-9_.-]+", "[REDACTED_JWT]", value)
        value = re.sub(r"(?i)Bearer\s+\S+", "Bearer [REDACTED]", value)
        # Redact before truncating, and JSON-escape newlines/control characters.
        details[field] = value[:1000]
    return json.dumps(details, ensure_ascii=True)


def cr_get(path: str) -> dict:
    tag = unquote(CLAN_TAG).strip()
    encoded_tag = quote("#" + tag.lstrip("#"), safe="")
    url = f"https://api.clashroyale.com/v1/clans/{encoded_tag}{path}"
    headers = {"Authorization": f"Bearer {CR_API_KEY}"}
    try:
        r = requests.get(url, headers=headers, timeout=20, allow_redirects=False)
    except requests.RequestException:
        # Some transport errors include header values in their exception text.
        raise RuntimeError("Clash Royale API bağlantı isteği başarısız oldu") from None
    if r.status_code >= 400:
        logger.error("Clash Royale API HTTP %s: %s", r.status_code, safe_api_error_body(r))
    if 300 <= r.status_code < 400:
        raise RuntimeError("Clash Royale API beklenmeyen yönlendirme döndürdü")
    r.raise_for_status()
    return r.json()


def fetch_current_river_race() -> dict:
    return cr_get("/currentriverrace")


def fetch_member_tags() -> set:
    # Savaş verisi hafta içinde klandan ayrılanları da içerir; listeler yalnız
    # şu anki üyelerle sınırlanır.
    data = cr_get("/members")
    return {m["tag"] for m in data.get("items", []) if m.get("tag")}


def is_war_day(data: dict) -> bool:
    # Alan hiç gelmezse listeleri engellememek için savaş günü varsayılır.
    return data.get("periodType", "warDay") != "training"


NOT_WAR_DAY_TEXT = "📅 Bugün savaş günü değil (eğitim günü), hak listesi savaş günlerinde çıkar."


def clan_participants(data: dict, member_tags: set | None) -> list:
    participants = data.get("clan", {}).get("participants", [])
    if member_tags is None:
        return participants
    return [p for p in participants if p.get("tag") in member_tags]


def build_report(data: dict, mode: str, member_tags: set | None = None) -> str:
    participants = clan_participants(data, member_tags)
    today = datetime.now().strftime("%d.%m.%Y")

    hak_birakanlar = []

    for p in participants:
        name = p.get("name", "Unknown")
        used = int(p.get("decksUsedToday", 0))
        remaining = MAX_DECKS_PER_DAY - used

        if remaining > 0:
            hak_birakanlar.append((remaining, name))

    hak_birakanlar.sort(reverse=True)

    msg = []

    if mode == "1000":
        msg.append(f"{today} (Saat 10’dan sonraya hak bırakanlar)")
    elif mode == "1230":
        msg.append(f"{today} (Savaşını Yapmayanlar)")
    else:
        msg.append(f"{today} (Kontrol)")

    msg.append("")

    if hak_birakanlar:
        for remaining, name in hak_birakanlar:
            msg.append(f"{name} {remaining}")
    else:
        msg.append("Kimse hak bırakmamış ✅")

    msg.append("")

    if mode == "1000":
        msg.append(NOTE_10)
    elif mode == "1230":
        msg.append(NOTE_1230)

    return "\n".join(msg)


def send_error(e: Exception) -> None:
    try:
        send_telegram(f"❌ Bot hata: {e}")
    except Exception:
        pass


def job(mode: str):
    print(f"JOB CALISTI -> {mode} / {datetime.now().strftime('%H:%M:%S')}")
    try:
        data = fetch_current_river_race()
        if not is_war_day(data):
            send_telegram(NOT_WAR_DAY_TEXT)
            return
        text = build_report(data, mode, fetch_member_tags())
        send_telegram(text)
        print("MESAJ GONDERILDI")
    except Exception as e:
        print("HATA:", e)
        send_error(e)

def build_weekly_medal_report(data: dict, week: int, member_tags: set | None = None) -> str:
    participants = clan_participants(data, member_tags)

    under_2400 = []

    for p in participants:
        name = p.get("name", "Unknown")
        fame = int(p.get("fame", 0))

        if fame < 2400:
            under_2400.append((fame, name))

    under_2400.sort(reverse=True)

    msg = []
    msg.append(f"{week}. Hafta 2400 Madalya Altında Kalanlar")
    msg.append("")

    if under_2400:
        for fame, name in under_2400:
            msg.append(f"{name} — {fame}")
    else:
        msg.append("2400 madalya altında kalan kimse yok ✅")

    return "\n".join(msg)


def weekly_medal_job(week: int):
    print(f"{week}. HAFTA MADALYA KONTROLU")

    try:
        data = fetch_current_river_race()
        text = build_weekly_medal_report(data, week, fetch_member_tags())
        send_telegram(text)
        print("MADALYA RAPORU GONDERILDI")

    except Exception as e:
        print("HATA:", e)


def build_week_summary(data: dict, member_tags: set | None = None) -> str:
    week = int(data.get("sectionIndex", 0)) + 1
    participants = clan_participants(data, member_tags)
    rows = sorted(participants, key=lambda p: (int(p.get("fame", 0)), p.get("name", "")))

    msg = [f"📊 {week}. Hafta Özeti", "", "İsim — madalya · haftalık hak · bugün", ""]
    for p in rows:
        msg.append(f"{p.get('name', 'Unknown')} — {int(p.get('fame', 0))} · "
                   f"{int(p.get('decksUsed', 0))} · {int(p.get('decksUsedToday', 0))}/{MAX_DECKS_PER_DAY}")
    if not rows:
        msg.append("Bu hafta veri yok.")
    msg += ["", f"Klan toplamı: {int(data.get('clan', {}).get('fame', 0))} madalya"]
    if not is_war_day(data):
        msg.append("📅 Bugün savaş günü değil (eğitim günü).")
    return "\n".join(msg)


def week_command():
    print(f"KOMUT -> hafta / {datetime.now().strftime('%H:%M:%S')}")
    try:
        send_telegram(build_week_summary(fetch_current_river_race(), fetch_member_tags()))
    except Exception as e:
        print("HATA:", e)
        send_error(e)


def health_check(notify: bool) -> bool:
    # Sessiz API kontrolü: yalnız sorun varsa (notify=True iken) mesaj atar.
    now = datetime.now().isoformat(timespec="seconds")
    try:
        data = fetch_current_river_race()
        members = fetch_member_tags()
    except Exception as e:
        print("API KONTROL HATA:", e)
        write_status(api_ok=False, api_checked=now, api_error=str(e)[:300])
        if notify:
            hint = ""
            if "403" in str(e):
                hint = "\nAPI anahtarı reddetti; ev internetinin IP adresi değişmiş olabilir."
            try:
                send_telegram("⚠️ Bot kontrolü: Clash Royale verisi alınamadı, "
                              f"komutlar çalışmayabilir.\n{e}{hint}")
            except Exception:
                pass
        return False
    participant_tags = {p.get("tag") for p in data.get("clan", {}).get("participants", [])}
    write_status(api_ok=True, api_checked=now, api_error=None,
                 period_type=data.get("periodType"), period_index=data.get("periodIndex"),
                 section_index=data.get("sectionIndex"),
                 participants=len(participant_tags), members=len(members),
                 former_members_in_race=len(participant_tags - members),
                 members_missing_from_race=len(members - participant_tags))
    return True


REMINDER_TIMES = ["10:00", "10:30", "11:00", "12:00", "12:30"]
WAR_DAYS = ["friday", "saturday", "sunday", "monday"]
HEALTH_CHECK_TIME = "09:55"

REMINDER_TEXT = "⚔️ Klan Savaşı Hatırlatması"


def reminder_job():
    print(f"HATIRLATMA -> {datetime.now().strftime('%H:%M:%S')}")
    try:
        send_telegram(REMINDER_TEXT)
    except Exception as e:
        print("HATA:", e)


# --- Telegram komutları -------------------------------------------------

def medal_command():
    print(f"KOMUT -> madalya / {datetime.now().strftime('%H:%M:%S')}")
    try:
        data = fetch_current_river_race()
        week = int(data.get("sectionIndex", 0)) + 1
        send_telegram(build_weekly_medal_report(data, week, fetch_member_tags()))
    except Exception as e:
        print("HATA:", e)
        send_error(e)


def help_command():
    lines = ["📋 Komutlar", ""]
    lines += [f"/{name} — {desc}" for name, _, desc in COMMANDS]
    send_telegram("\n".join(lines))


# (komut, işleyici, açıklama). Telegram komut adları yalnız a-z/0-9/_ kabul eder.
COMMANDS = [
    ("hak", lambda: job("1000"), "Saat 10'dan sonraya hak bırakanlar"),
    ("yapmayan", lambda: job("1230"), "Savaşını yapmayanlar"),
    ("madalya", medal_command, "2400 madalya altında kalanlar"),
    ("hafta", week_command, "Haftalık özet: madalya ve kullanılan haklar"),
    ("komut", help_command, "Komut listesi"),
]
# Eski/uzun yazımlar ve yaygın yardım komutları da çalışsın.
ALIASES = {
    "hakbirakan": "hak", "hakbırakan": "hak", "hakbirakanlar": "hak", "hakbırakanlar": "hak",
    "yapmayanlar": "yapmayan", "komutlar": "komut", "yardim": "komut", "yardım": "komut",
    "help": "komut", "start": "komut",
}
COMMAND_HANDLERS = {name: handler for name, handler, _ in COMMANDS}
COMMAND_COOLDOWN = 30          # saniye; aynı komutu art arda tetiklemeyi engeller
STALE_UPDATE_SECONDS = 120     # yeniden başlamadan önce yazılmış eski komutlar yok sayılır
TG_ANON_ADMIN_ID = 1087968824  # GroupAnonymousBot (anonim grup yöneticisi)

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state", "status.json")
_status = {}
_status_lock = threading.Lock()
_last_command_at: dict[str, float] = {}


def write_status(**fields) -> None:
    # Sırsız teşhis dosyası; token/anahtar asla yazılmaz.
    with _status_lock:
        _status.update(fields)
        _write_status_file()


def _write_status_file() -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_status, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def telegram_api(method: str, payload: dict | None = None, timeout: int = 20) -> dict:
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/{method}"
    try:
        response = requests.post(url, json=payload or {}, timeout=timeout)
    except requests.RequestException:
        raise RuntimeError(f"Telegram {method} isteği başarısız oldu") from None
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method} HTTP {response.status_code}: {body.get('description', '')[:200]}")
    return body.get("result")


def parse_command(text: str, bot_username: str) -> str | None:
    if not text:
        return None
    first = text.strip().split()[0].lower() if text.strip() else ""
    if not first.startswith("/"):
        return None
    first = first[1:]
    if "@" in first:
        first, _, target = first.partition("@")
        if bot_username and target != bot_username.lower():
            return None
    name = ALIASES.get(first, first)
    return name if name in COMMAND_HANDLERS else None


def is_authorized(message: dict) -> bool:
    chat_id = str(message.get("chat", {}).get("id", ""))
    if chat_id != str(TG_CHAT_ID).strip():
        return False
    if message.get("chat", {}).get("type") == "private":
        return True
    sender = message.get("from", {}) or {}
    sender_chat = message.get("sender_chat", {}) or {}
    if sender.get("id") == TG_ANON_ADMIN_ID and str(sender_chat.get("id", "")) == chat_id:
        return True
    try:
        member = telegram_api("getChatMember", {"chat_id": TG_CHAT_ID, "user_id": sender.get("id")})
    except RuntimeError as e:
        print("HATA:", e)
        return False
    return member.get("status") in ("creator", "administrator")


def handle_update(update: dict, bot_username: str, started_at: float) -> None:
    message = update.get("message")
    if not message:
        return
    name = parse_command(message.get("text", ""), bot_username)
    if name is None:
        return
    if message.get("date", 0) < started_at - STALE_UPDATE_SECONDS:
        return
    if not is_authorized(message):
        print("YETKISIZ KOMUT YOK SAYILDI")
        return
    now = time.monotonic()
    last = _last_command_at.get(name)
    if last is not None and now - last < COMMAND_COOLDOWN:
        return
    _last_command_at[name] = now
    print(f"KOMUT -> /{name} / {datetime.now().strftime('%H:%M:%S')}")
    write_status(last_command=f"/{name} {datetime.now().isoformat(timespec='seconds')}")
    COMMAND_HANDLERS[name]()


def poll_commands() -> None:
    started_at = time.time()
    bot_username = ""
    offset = None
    while True:
        try:
            if not bot_username:
                me = telegram_api("getMe")
                bot_username = me.get("username", "")
                chat = telegram_api("getChat", {"chat_id": TG_CHAT_ID})
                telegram_api("setMyCommands", {"commands": [
                    {"command": name, "description": desc} for name, _, desc in COMMANDS
                ]})
                write_status(bot_username=bot_username,
                             can_read_all_group_messages=me.get("can_read_all_group_messages"),
                             chat_type=chat.get("type"),
                             started=datetime.now().isoformat(timespec="seconds"))
            payload = {"timeout": 50, "allowed_updates": ["message"]}
            if offset is not None:
                payload["offset"] = offset
            updates = telegram_api("getUpdates", payload, timeout=60)
            write_status(last_poll_ok=datetime.now().isoformat(timespec="seconds"), last_poll_error=None)
            for update in updates:
                offset = update["update_id"] + 1
                try:
                    handle_update(update, bot_username, started_at)
                except Exception as e:
                    print("HATA:", e)
        except Exception as e:
            print("POLL HATA:", e)
            write_status(last_poll_error=str(e)[:300],
                         last_poll_error_at=datetime.now().isoformat(timespec="seconds"))
            time.sleep(15)


def main():
    for day_name in WAR_DAYS:
        for at in REMINDER_TIMES:
            getattr(schedule.every(), day_name).at(at).do(reminder_job)

    for day_name in WAR_DAYS:
        getattr(schedule.every(), day_name).at(HEALTH_CHECK_TIME).do(health_check, True)

    schedule.every().monday.at("12:40").do(weekly_medal_job, 1)

    health_check(notify=False)
    threading.Thread(target=poll_commands, name="telegram-poll", daemon=True).start()

    print("Bot basladi...")
    print(schedule.get_jobs())

    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
