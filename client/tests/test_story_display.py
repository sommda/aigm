"""How the client shows a story game (docs/STORY.md 11): status line, chapter banner, saves, /story."""

from aigm_client import events as ev
from aigm_client.session import story_note
from tests.fake_server import FakeServer
from tests.test_app_pilot import make_app, screen_text, send, settle, start
from tests.test_thinking_switch import status_text

CH1 = {"length": "short", "chapter": 1, "chapter_title": "Ashby", "ended": False}
CH2 = {"length": "short", "chapter": 2, "chapter_title": "The road", "ended": False}
END = {"length": "short", "chapter": 4, "chapter_title": "The end", "ended": True, "ending": "Freed"}


def reply(*extra, story=None):
    end = {"message_id": "m1", "stop_reason": "end_turn", "usage": {}}
    if story is not None:
        end["story"] = story
    return [("message_start", {"message_id": "m1", "session_id": "default"}), ("text", {"delta": "You press on. "}),
            *extra, ("message_end", end)]  # fmt: skip


def test_events_are_parsed():
    assert ev.parse_event("chapter", '{"previous": 1, "chapter": 2, "title": "The road"}') == ev.ChapterChange(1, 2, "The road")
    end = ev.parse_event("message_end", '{"story": {"chapter": 2}}')
    assert end.story == {"chapter": 2} and ev.parse_event("message_end", "{}").story is None
    assert ev.parse_event("message_end", '{"story": "x"}').story is None


def test_the_story_note_is_short_and_empty_for_endless_games():
    assert story_note(None) == "" and story_note({}) == ""
    assert story_note(CH2) == "short story, chapter 2: The road"
    assert story_note(END) == "short story, finished"


async def test_the_status_line_shows_the_chapter_of_a_loaded_game():
    fake = FakeServer()
    fake.story = CH1
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        assert "story: Ch 1/3: Ashby" in status_text(app)


async def test_an_endless_game_shows_no_story():
    app = make_app(FakeServer())
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        assert "story:" not in status_text(app)


async def test_a_chapter_event_prints_one_banner_and_updates_the_line():
    fake = FakeServer(reply(("chapter", {"previous": 1, "chapter": 2, "title": "The road"}), story=CH2))
    fake.story = CH1
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "I go north")
        await settle(pilot, lambda: not app.session.busy and app.session.dirty)
        text = screen_text(app)
        assert text.count("Chapter 2: The road") == 1
        assert "story: Ch 2/3: The road" in status_text(app)


async def test_a_chapter_that_changed_between_turns_is_announced_by_the_next_message_end():
    fake = FakeServer(reply(story=CH2))
    fake.story = CH1
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "I wait")
        await settle(pilot, lambda: not app.session.busy and app.session.dirty)
        assert screen_text(app).count("Chapter 2: The road") == 1


async def test_the_ending_is_announced_and_the_line_says_so():
    fake = FakeServer(reply(("chapter", {"previous": 3, "chapter": 4, "title": "The end"}), story=END))
    fake.story = {**CH2, "chapter": 3, "chapter_title": "The vault"}
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "I strike")
        await settle(pilot, lambda: not app.session.busy and app.session.dirty)
        assert "The story has ended" in screen_text(app) and "story: Story over" in status_text(app)


async def test_servers_that_do_not_report_a_story_change_nothing():
    app = make_app(FakeServer(reply()))
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "hello")
        await settle(pilot, lambda: not app.session.busy and app.session.dirty)
        assert app.session.story is None and "Chapter" not in screen_text(app)


async def test_saves_and_info_mention_the_story():
    fake = FakeServer()
    fake.saves["a"] = []
    original = fake.handle

    def handle(req):
        res = original(req)
        if req.url.path in ("/history", "/history/a") and res.status_code == 200:
            import json

            body = json.loads(res.content)
            for h in body.get("histories", [body]):
                h["story"] = CH2
            import httpx

            return httpx.Response(200, json=body)
        return res

    fake.handle = handle
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "/saves")
        await settle(pilot, lambda: "short story, chapter 2: The road" in screen_text(app))
        await send(app, pilot, "/info a")
        await settle(pilot, lambda: screen_text(app).count("short story, chapter 2") == 2)


async def test_the_story_command_needs_a_debug_server_and_prints_the_plan():
    fake = FakeServer()
    fake.debug = False
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "/story")
        await settle(pilot, lambda: "not in debug mode" in screen_text(app))
    fake = FakeServer()
    fake.debug = True
    fake.story_text = "Goal: The Crown. It binds the river."
    app = make_app(fake)
    async with app.run_test(size=(120, 30)) as pilot:
        await start(app, pilot)
        await send(app, pilot, "/story")
        await settle(pilot, lambda: "Goal: The Crown" in screen_text(app))
