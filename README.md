# Clash Royale Clan Tools

[![CI](https://github.com/MetehanQF/clash-royale-clan-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/MetehanQF/clash-royale-clan-tools/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Two small self-hosted tools for running a Clash Royale clan's **River Race**
(clan war) without anyone having to open the game and count decks by hand.

| Part | What it does |
|---|---|
| [`bot/`](bot/) | Telegram bot: war-day reminders, lists of members who left decks unused, a weekly medal check and on-demand commands for admins |
| [`web/`](web/) | **Riverwatch** — a single-page dashboard of today's race and the last four weeks, refreshed every 30 s |

Both read the official [Clash Royale API](https://developer.clashroyale.com)
and nothing else. User-facing text is in Turkish, because the clan is; the code
and this README are in English.

## The rules they enforce

Each member has 4 war decks per war day (Friday–Monday). The clan's rules are:

- leaving decks unused past **10:00** three times is grounds for removal;
- skipping the war entirely on two of the four war days is grounds for removal;
- a member should reach **2400 medals** a week.

The thresholds live as constants at the top of `bot/cr_war_bot.py`
(`MAX_DECKS_PER_DAY`, `REMINDER_TIMES`, `WAR_DAYS`, the 2400 medal line), so a clan
with different rules changes them in one place.

## Bot

Scheduled, on war days only:

- reminders at 10:00, 10:30, 11:00, 12:00 and 12:30;
- a silent API health check at 09:55 that only speaks up when the Clash Royale
  API is unreachable or rejects the key (with a hint when the cause is a changed
  home IP, the usual reason for a 403);
- every Monday at 12:40, the members who finished the week under 2400 medals.

Commands (also registered with Telegram so they show in the `/` menu):

| Command | Reply |
|---|---|
| `/hak` | members with decks still unused, most remaining first |
| `/yapmayan` | the same list as the 12:30 deadline report, with the skipped-war rule |
| `/madalya` | members under 2400 medals this week |
| `/hafta` | weekly summary: medals, decks used this week and today |
| `/komut` | command list |

Design choices worth knowing:

- **Former members are filtered out.** The race data keeps players who left the
  clan mid-week; every list is intersected with the current member list.
- **On a training day there is no list**, just a note that it is not a war day.
- **Only the configured chat, and only its admins,** can trigger commands
  (anonymous group admins included). Each command has a 30 s cooldown, and
  commands sent before a restart are ignored rather than replayed.
- **Secrets never reach a log or a message.** Tokens come only from the
  environment; API error bodies are reduced to their `reason`/`message` fields
  with the keys, JWTs and bearer tokens redacted; transport exceptions, which can
  carry header values, are replaced with a generic message.
- `bot/state/status.json` records a secret-free diagnostic snapshot (last poll,
  last command, member/participant counts) for troubleshooting.

## Dashboard

Riverwatch shows today's race with filters (decks remaining, 0/4, under 2400,
completed) and tabs for the last four finished weeks from the River Race log.
It has no login and no write actions: the API key stays on the server, the
browser only sees the aggregated JSON from `/api/river-race` and `/api/history`.
Without credentials both routes answer `503` instead of guessing.

## Setup

1. Create an API key at <https://developer.clashroyale.com> for the public IP of
   the machine that will run this, and a bot with [@BotFather](https://t.me/BotFather).
   Add the bot to your clan's group.
2. Copy `.env.example` to `/etc/crbot.env` (and `/etc/clan-web.env` for the
   dashboard, which needs only `CR_API_KEY` and `CLAN_TAG`), owned by root,
   mode `0600`, and fill it in.
3. Install and run:

   ```bash
   cd bot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   cd ../web && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```

   Example systemd units are in `bot/crbot.service.example` and
   `web/clan-web.service.example`. The dashboard binds to `127.0.0.1:5000`; put a
   reverse proxy or a tunnel in front of it if it should be reachable from
   outside.

## Tests

```bash
cd bot && python3 -m unittest -v test_cr_war_bot
```

The tests load the bot with fake credentials and mock every HTTP call, so they
never reach Telegram or the Clash Royale API. CI also smoke-tests the dashboard
with no configuration and runs a privacy gate that fails the build on anything
identifying a real installation.

## Disclaimer

This material is unofficial and is not endorsed by Supercell. For more
information see Supercell's [Fan Content Policy](https://supercell.com/en/fan-content-policy/).

## License

[MIT](LICENSE)
