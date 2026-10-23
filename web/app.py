"""Local Clash Royale River Race dashboard."""

import os
from urllib.parse import quote

import requests
from flask import Flask, jsonify, render_template


app = Flask(__name__)
API_BASE = "https://api.clashroyale.com/v1"


def fetch_river_race():
    api_key = os.environ.get("CR_API_KEY", "").strip()
    clan_tag = os.environ.get("CLAN_TAG", "").strip().lstrip("#").upper()

    if not api_key or not clan_tag:
        raise ValueError("CR_API_KEY ve CLAN_TAG ortam değişkenlerini ayarlayın.")

    url = f"{API_BASE}/clans/{quote('#' + clan_tag, safe='')}/currentriverrace"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=12,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Clash Royale API bağlantısı kurulamadı. Biraz sonra tekrar deneyin.") from exc

    if response.status_code == 403:
        raise RuntimeError("API erişimi reddedildi. API anahtarını ve izin verilen IP adresini kontrol edin.")
    if response.status_code == 404:
        raise RuntimeError("Klan bulunamadı. CLAN_TAG değerini kontrol edin.")
    if response.status_code == 429:
        raise RuntimeError("API istek sınırına ulaşıldı. Biraz sonra tekrar deneyin.")
    if not response.ok:
        raise RuntimeError(f"Clash Royale API şu anda yanıt vermiyor (HTTP {response.status_code}).")

    try:
        race = response.json()
    except ValueError as exc:
        raise RuntimeError("API geçerli veri göndermedi. Biraz sonra tekrar deneyin.") from exc

    clan = race.get("clan") or {}
    participants = clan.get("participants") or []
    players = []
    for participant in participants:
        today = max(0, int(participant.get("decksUsedToday") or 0))
        players.append({
            "name": participant.get("name") or "Bilinmeyen oyuncu",
            "tag": participant.get("tag") or "",
            "fame": max(0, int(participant.get("fame") or 0)),
            "decksUsedToday": today,
            "decksUsed": max(0, int(participant.get("decksUsed") or 0)),
            "remainingToday": max(0, 4 - today),
        })

    players.sort(key=lambda p: (-p["fame"], -p["decksUsedToday"], p["name"].casefold()))
    return {
        "clanName": clan.get("name") or "Klan Savaşı",
        "clanTag": clan.get("tag") or f"#{clan_tag}",
        "state": race.get("state") or "",
        "players": players,
        "summary": {
            "participants": len(players),
            "completed": sum(p["decksUsedToday"] >= 4 for p in players),
            "remaining": sum(p["remainingToday"] > 0 for p in players),
            "zero": sum(p["decksUsedToday"] == 0 for p in players),
            "under2400": sum(p["fame"] < 2400 for p in players),
        },
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/river-race")
def river_race():
    try:
        return jsonify(fetch_river_race())
    except (ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 503


@app.get("/api/history")
def river_race_history():
    """Return up to four completed races from the clan's River Race Log."""
    api_key = os.environ.get("CR_API_KEY", "").strip()
    clan_tag = os.environ.get("CLAN_TAG", "").strip().lstrip("#").upper()
    if not api_key or not clan_tag:
        return jsonify({"error": "CR_API_KEY ve CLAN_TAG ortam değişkenlerini ayarlayın."}), 503

    url = f"{API_BASE}/clans/{quote('#' + clan_tag, safe='')}/riverracelog"
    try:
        response = requests.get(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            params={"limit": 10},
            timeout=12,
        )
    except requests.RequestException:
        return jsonify({"error": "Geçmiş yarış verilerine bağlanılamadı. Biraz sonra tekrar deneyin."}), 503

    if response.status_code == 403:
        return jsonify({"error": "Geçmiş veriler için API erişimi reddedildi. Anahtar ve izin verilen IP adresini kontrol edin."}), 503
    if response.status_code == 404:
        return jsonify({"error": "Klan geçmişi bulunamadı. CLAN_TAG değerini kontrol edin."}), 503
    if response.status_code == 429:
        return jsonify({"error": "API istek sınırına ulaşıldı. Biraz sonra tekrar deneyin."}), 503
    if not response.ok:
        return jsonify({"error": f"Geçmiş yarış verileri alınamadı (HTTP {response.status_code})."}), 503
    try:
        log = response.json()
    except ValueError:
        return jsonify({"error": "Geçmiş yarış API'si geçerli veri göndermedi."}), 503

    weeks = []
    tag = f"#{clan_tag}"
    for entry in sorted(log.get("items") or [], key=lambda item: item.get("createdDate") or "", reverse=True):
        standing = next(
            (item for item in entry.get("standings") or []
             if (item.get("clan") or {}).get("tag", "").upper() == tag),
            None,
        )
        if standing is None:
            continue
        clan = standing.get("clan") or {}
        participants = clan.get("participants") or []
        players = [{
            "name": player.get("name") or "Bilinmeyen oyuncu",
            "tag": player.get("tag") or "",
            "fame": max(0, int(player.get("fame") or 0)),
        } for player in participants]
        players.sort(key=lambda player: (-player["fame"], player["name"].casefold()))
        weeks.append({
            "seasonId": entry.get("seasonId"),
            "sectionIndex": entry.get("sectionIndex"),
            "createdDate": entry.get("createdDate"),
            "players": players,
        })
        if len(weeks) == 4:
            break
    return jsonify({"weeks": weeks})


@app.get("/api/status")
def status():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
