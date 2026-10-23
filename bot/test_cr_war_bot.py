import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import requests


# Isolated module with fake credentials; never load production secrets.
spec = importlib.util.spec_from_file_location(
    "bot_under_test", Path(__file__).with_name("cr_war_bot.py")
)
bot = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, {
    "CR_API_KEY": "fake-api-secret",
    "CLAN_TAG": "%23TEST0CLAN",
    "TG_BOT_TOKEN": "fake-telegram-secret",
    "TG_CHAT_ID": "fake-chat",
}):
    spec.loader.exec_module(bot)


class ApiTests(unittest.TestCase):
    def test_success_and_tag_encoding(self):
        payload = {"clan": {"participants": []}}
        for tag in ("%23TEST0CLAN", "#TEST0CLAN", "TEST0CLAN"):
            with self.subTest(tag=tag), patch.object(bot, "CLAN_TAG", tag):
                response = Mock(status_code=200)
                response.json.return_value = payload
                with patch.object(bot.requests, "get", return_value=response) as get:
                    self.assertEqual(bot.fetch_current_river_race(), payload)
                get.assert_called_once_with(
                    "https://api.clashroyale.com/v1/clans/%23TEST0CLAN/currentriverrace",
                    headers={"Authorization": "Bearer fake-api-secret"},
                    timeout=20, allow_redirects=False,
                )

    def test_403_logs_reason_without_credentials(self):
        response = Mock(status_code=403)
        response.json.return_value = {
            "reason": "accessDenied.invalidIp",
            "message": "IP denied\n" + bot.CR_API_KEY + " " + bot.TG_BOT_TOKEN,
            "token": "must-not-be-logged",
        }
        response.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
        with patch.object(bot.requests, "get", return_value=response):
            with self.assertLogs(bot.logger, level="ERROR") as logs:
                with self.assertRaises(requests.HTTPError):
                    bot.fetch_current_river_race()
        output = " ".join(logs.output)
        self.assertIn("accessDenied.invalidIp", output)
        self.assertNotIn(bot.CR_API_KEY, output)
        self.assertNotIn(bot.TG_BOT_TOKEN, output)
        self.assertNotIn("must-not-be-logged", output)
        self.assertNotIn("\n", output)

    def test_unsafe_or_unexpected_bodies(self):
        for body in ([], None, "raw secret", {"message": {"token": "secret"}}):
            response = Mock()
            response.json.return_value = body
            self.assertNotIn("secret", bot.safe_api_error_body(response))
        response.json.side_effect = ValueError()
        self.assertIn("JSON olmayan", bot.safe_api_error_body(response))

    def test_redaction_precedes_truncation(self):
        response = Mock()
        response.json.return_value = {"message": "x" * 995 + bot.CR_API_KEY}
        message = json.loads(bot.safe_api_error_body(response))["message"]
        self.assertLessEqual(len(message), 1000)
        self.assertNotIn("fake", message)

    def test_transport_error_does_not_expose_header(self):
        with patch.object(bot.requests, "get", side_effect=requests.exceptions.InvalidHeader(bot.CR_API_KEY)):
            with self.assertRaises(RuntimeError) as error:
                bot.fetch_current_river_race()
        self.assertNotIn(bot.CR_API_KEY, str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)

    def test_redirect_not_followed(self):
        with patch.object(bot.requests, "get", return_value=Mock(status_code=302)):
            with self.assertRaisesRegex(RuntimeError, "yönlendirme"):
                bot.fetch_current_river_race()


class ScheduleTests(unittest.TestCase):
    def tearDown(self):
        bot.schedule.clear()

    def test_reminder_times_and_days(self):
        with patch.object(bot.threading, "Thread"), \
             patch.object(bot, "health_check") as hc, \
             patch.object(bot.time, "sleep", side_effect=StopIteration):
            with self.assertRaises(StopIteration):
                bot.main()
        jobs = bot.schedule.get_jobs()
        reminders = [j for j in jobs if j.job_func.func is bot.reminder_job]
        got = sorted((j.start_day, j.at_time.strftime("%H:%M")) for j in reminders)
        want = sorted((d, t) for d in ("friday", "saturday", "sunday", "monday")
                      for t in ("10:00", "10:30", "11:00", "12:00", "12:30"))
        self.assertEqual(got, want)
        # Eski otomatik hak-bırakan listesi artık zamanlanmıyor.
        self.assertFalse([j for j in jobs if j.job_func.func is bot.job])
        medal = [j for j in jobs if j.job_func.func is bot.weekly_medal_job]
        self.assertEqual([(j.start_day, j.at_time.strftime("%H:%M")) for j in medal], [("monday", "12:40")])
        checks = [j for j in jobs if j.job_func.func is hc]
        self.assertEqual(sorted(j.start_day for j in checks), sorted(["friday", "saturday", "sunday", "monday"]))
        self.assertTrue(all(j.at_time.strftime("%H:%M") == "09:55" and j.job_func.args == (True,) for j in checks))
        hc.assert_called_once_with(notify=False)

    def test_reminder_sends_plain_text(self):
        with patch.object(bot, "send_telegram") as send, \
             patch.object(bot, "fetch_current_river_race") as fetch:
            bot.reminder_job()
        fetch.assert_not_called()
        send.assert_called_once_with(bot.REMINDER_TEXT)


class CommandTests(unittest.TestCase):
    def setUp(self):
        bot._last_command_at.clear()
        self.now = bot.time.time()

    def msg(self, text, chat_id="fake-chat", chat_type="supergroup", user_id=42, age=0):
        return {"update_id": 1, "message": {
            "text": text, "date": int(self.now - age),
            "chat": {"id": chat_id, "type": chat_type}, "from": {"id": user_id},
        }}

    def test_parse_command(self):
        cases = {
            "/hak": "hak", "/HAK": "hak", "/hak@CrBot": "hak", "/hak extra": "hak",
            "/hakbirakan": "hak", "/hakbırakan": "hak", "/HAKBIRAKAN": "hak",
            "/yapmayan": "yapmayan", "/yapmayanlar": "yapmayan",
            "/madalya": "madalya",
            "/komut": "komut", "/komutlar": "komut", "/yardım": "komut", "/start": "komut",
        }
        for text, want in cases.items():
            self.assertEqual(bot.parse_command(text, "crbot"), want, text)
        for text in ("", "hak", "/hak@otherbot", "/bilinmeyen", "selam /hak"):
            self.assertIsNone(bot.parse_command(text, "crbot"), text)

    def test_reports_use_existing_modes(self):
        for text, mode in (("/hak", "1000"), ("/yapmayan", "1230")):
            with self.subTest(text=text):
                bot._last_command_at.clear()
                job, _ = self.run_update(self.msg(text))
                job.assert_called_once_with(mode)

    def test_medal_command_uses_current_week(self):
        data = {"sectionIndex": 2, "clan": {"participants": [
            {"name": "Az", "fame": 1200}, {"name": "Cok", "fame": 3000}]}}
        with patch.object(bot, "fetch_current_river_race", return_value=data), \
             patch.object(bot, "fetch_member_tags", return_value=None), \
             patch.object(bot, "send_telegram") as send:
            self.run_update(self.msg("/madalya"))
        text = send.call_args.args[0]
        self.assertIn("3. Hafta 2400 Madalya Altında Kalanlar", text)
        self.assertIn("Az — 1200", text)
        self.assertNotIn("Cok", text)

    def test_help_lists_all_commands(self):
        with patch.object(bot, "send_telegram") as send:
            self.run_update(self.msg("/komut"))
        text = send.call_args.args[0]
        for name in ("/hak", "/yapmayan", "/madalya", "/hafta", "/komut"):
            self.assertIn(name, text)

    def test_cooldown_is_per_command(self):
        job, _ = self.run_update(self.msg("/hak"))
        job2, _ = self.run_update(self.msg("/yapmayan"))
        job.assert_called_once_with("1000")
        job2.assert_called_once_with("1230")

    def run_update(self, update, status="administrator"):
        with patch.object(bot, "telegram_api", return_value={"status": status}) as api, \
             patch.object(bot, "job") as job, patch.object(bot, "write_status"):
            bot.handle_update(update, "crbot", self.now)
        return job, api

    def test_admin_triggers_hak_report(self):
        job, api = self.run_update(self.msg("/hakbirakan"))
        job.assert_called_once_with("1000")
        api.assert_called_once_with("getChatMember", {"chat_id": "fake-chat", "user_id": 42})

    def test_non_admin_ignored(self):
        job, _ = self.run_update(self.msg("/hakbirakan"), status="member")
        job.assert_not_called()

    def test_other_chat_ignored(self):
        job, api = self.run_update(self.msg("/hakbirakan", chat_id="-999"))
        job.assert_not_called()
        api.assert_not_called()

    def test_private_configured_chat_allowed(self):
        job, api = self.run_update(self.msg("/hakbirakan", chat_type="private"))
        job.assert_called_once_with("1000")
        api.assert_not_called()

    def test_stale_command_ignored(self):
        job, _ = self.run_update(self.msg("/hakbirakan", age=bot.STALE_UPDATE_SECONDS + 60))
        job.assert_not_called()

    def test_cooldown(self):
        job, _ = self.run_update(self.msg("/hakbirakan"))
        job2, _ = self.run_update(self.msg("/hakbirakan"))
        job.assert_called_once()
        job2.assert_not_called()


RACE = {
    "periodType": "warDay", "periodIndex": 24, "sectionIndex": 0,
    "clan": {"fame": 9000, "participants": [
        {"tag": "#A", "name": "Aktif", "fame": 3000, "decksUsed": 12, "decksUsedToday": 4},
        {"tag": "#B", "name": "Eksik", "fame": 1500, "decksUsed": 6, "decksUsedToday": 1},
        {"tag": "#X", "name": "Ayrildi", "fame": 0, "decksUsed": 0, "decksUsedToday": 0},
    ]},
}
MEMBERS = {"#A", "#B"}


class DataTests(unittest.TestCase):
    def run_job(self, race, mode="1000"):
        with patch.object(bot, "fetch_current_river_race", return_value=race), \
             patch.object(bot, "fetch_member_tags", return_value=MEMBERS) as members, \
             patch.object(bot, "send_telegram") as send:
            bot.job(mode)
        return send.call_args.args[0], members

    def test_former_members_excluded(self):
        text, _ = self.run_job(RACE)
        self.assertIn("Eksik 3", text)
        self.assertNotIn("Ayrildi", text)
        self.assertNotIn("Aktif", text)

    def test_training_day_message(self):
        text, members = self.run_job(dict(RACE, periodType="training"))
        self.assertEqual(text, bot.NOT_WAR_DAY_TEXT)
        members.assert_not_called()

    def test_colosseum_and_missing_period_are_war_days(self):
        self.assertTrue(bot.is_war_day({"periodType": "colosseum"}))
        self.assertTrue(bot.is_war_day({}))
        self.assertFalse(bot.is_war_day({"periodType": "training"}))

    def test_medal_report_excludes_former_members(self):
        text = bot.build_weekly_medal_report(RACE, 1, MEMBERS)
        self.assertIn("Eksik — 1500", text)
        self.assertNotIn("Ayrildi", text)

    def test_members_endpoint(self):
        response = Mock(status_code=200)
        response.json.return_value = {"items": [{"tag": "#A"}, {"tag": "#B"}, {"name": "etiketsiz"}]}
        with patch.object(bot.requests, "get", return_value=response) as get:
            self.assertEqual(bot.fetch_member_tags(), {"#A", "#B"})
        self.assertTrue(get.call_args.args[0].endswith("/clans/%23TEST0CLAN/members"))

    def test_week_summary(self):
        text = bot.build_week_summary(RACE, MEMBERS)
        self.assertIn("1. Hafta Özeti", text)
        self.assertLess(text.index("Eksik — 1500 · 6 · 1/4"), text.index("Aktif — 3000 · 12 · 4/4"))
        self.assertNotIn("Ayrildi", text)
        self.assertIn("Klan toplamı: 9000", text)


class HealthCheckTests(unittest.TestCase):
    def run_check(self, notify, error=None):
        fetch = patch.object(bot, "fetch_current_river_race",
                             side_effect=error, return_value=RACE)
        with fetch, patch.object(bot, "fetch_member_tags", return_value=MEMBERS), \
             patch.object(bot, "send_telegram") as send, \
             patch.object(bot, "write_status") as status:
            ok = bot.health_check(notify)
        return ok, send, status

    def test_ok_is_silent_and_records_diagnostics(self):
        ok, send, status = self.run_check(True)
        self.assertTrue(ok)
        send.assert_not_called()
        fields = status.call_args.kwargs
        self.assertEqual((fields["former_members_in_race"], fields["members_missing_from_race"]), (1, 0))

    def test_failure_notifies_only_when_asked(self):
        err = requests.HTTPError("403 Client Error: Forbidden")
        ok, send, _ = self.run_check(True, err)
        self.assertFalse(ok)
        self.assertIn("IP adresi", send.call_args.args[0])
        ok, send, _ = self.run_check(False, err)
        self.assertFalse(ok)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
