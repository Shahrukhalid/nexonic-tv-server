"""Smart TV (Xtream Codes) API, the Favourites bouquet and playlist parsing."""
import sqlite3

from fastapi.testclient import TestClient

from backend.app.config import DATABASE_PATH
from backend.app.main import app
from backend.app.services.playlist_importer import detect_is_adult, normalize_category, parse_m3u_content
from backend.app.services.xtream_service import FAVOURITES_CATEGORY_ID

PLAYLIST = """#EXTM3U
#EXTINF:-1 tvg-id="news.one" tvg-logo="https://example.com/n.png" group-title="News",News One
https://example.com/news/index.m3u8
#EXTINF:-1 group-title="Sports",Sport Live
https://example.com/sport/index.m3u8
"""


def _login(client):
    info = client.get("/api/settings/connect-info").json()
    return {"username": info["xtream_username"], "password": info["xtream_password"]}


def _add_channels():
    con = sqlite3.connect(DATABASE_PATH)
    con.execute("DELETE FROM channels")
    con.execute("INSERT INTO channels (name, category, stream_url, is_favorite) VALUES ('Fav News', 'News', 'https://example.com/a.m3u8', 1)")
    con.execute("INSERT INTO channels (name, category, stream_url, is_favorite) VALUES ('Other Sport', 'Sports', 'https://example.com/b.m3u8', 0)")
    con.commit()
    con.close()


def test_parse_m3u_reads_names_groups_and_urls():
    channels = parse_m3u_content(PLAYLIST)
    assert [c["name"] for c in channels] == ["News One", "Sport Live"]
    assert channels[0]["stream_url"] == "https://example.com/news/index.m3u8"
    assert channels[0]["epg_id"] == "news.one"


def test_adult_entries_are_skipped():
    assert detect_is_adult("XXX Channel", "Adult")
    assert not detect_is_adult("Kids TV", "Kids")
    adult = "#EXTM3U\n#EXTINF:-1 group-title=\"Adult\",XXX Night\nhttps://example.com/x.m3u8\n"
    assert parse_m3u_content(adult) == []


def test_series_channels_get_their_own_category():
    assert normalize_category("Entertainment", "Sitcom 24/7", True) == "TV Series"


def test_xtream_rejects_wrong_password():
    with TestClient(app) as client:
        r = client.get("/player_api.php", params={"username": "nexonic", "password": "wrong-password"})
        assert r.json()["user_info"]["auth"] == 0


def test_xtream_login_and_favourites_bouquet():
    with TestClient(app) as client:
        login = _login(client)
        _add_channels()
        assert client.get("/player_api.php", params=login).json()["user_info"]["auth"] == 1

        cats = client.get("/player_api.php", params={**login, "action": "get_live_categories"}).json()
        assert cats[0] == {"category_id": FAVOURITES_CATEGORY_ID, "category_name": "Favourites", "parent_id": 0}
        assert {c["category_name"] for c in cats} >= {"News", "Sports"}

        favs = client.get("/player_api.php", params={**login, "action": "get_live_streams", "category_id": FAVOURITES_CATEGORY_ID}).json()
        assert [s["name"] for s in favs] == ["Fav News"]
        assert favs[0]["category_id"] == FAVOURITES_CATEGORY_ID

        everything = client.get("/player_api.php", params={**login, "action": "get_live_streams"}).json()
        assert {s["name"] for s in everything} == {"Fav News", "Other Sport"}


def test_m3u_playlist_needs_login():
    with TestClient(app) as client:
        login = _login(client)
        _add_channels()
        assert "Fav News" not in client.get("/get.php", params={"username": "nexonic", "password": "nope"}).text
        ok = client.get("/get.php", params={**login, "type": "m3u_plus"})
        assert ok.status_code == 200 and ok.text.startswith("#EXTM3U url-tvg=") and "Fav News" in ok.text
        favs = client.get("/get.php", params={**login, "favourites": 1}).text
        assert "Fav News" in favs and "Other Sport" not in favs


def test_server_time_is_utc_without_warnings():
    import warnings
    with TestClient(app) as client, warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        login = _login(client)
        info = client.get("/player_api.php", params=login).json()["server_info"]
        assert info["timezone"] == "UTC" and int(info["timestamp_now"]) > 1700000000


def test_short_epg_lists_now_and_next_for_smart_tv_apps():
    import base64
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    con = sqlite3.connect(DATABASE_PATH)
    con.execute("DELETE FROM channels")
    con.execute("DELETE FROM epg_programs")
    cid = con.execute("INSERT INTO channels (name, category, stream_url, epg_id) VALUES ('Guide TV', 'News', 'https://example.com/g.m3u8', 'guide.tv')").lastrowid
    rows = [("Morning News", now - timedelta(minutes=10), now + timedelta(minutes=20)),
            ("Weather", now + timedelta(minutes=20), now + timedelta(minutes=30)),
            ("Old Show", now - timedelta(hours=2), now - timedelta(hours=1))]
    for title, start, end in rows:
        con.execute("INSERT INTO epg_programs (channel_epg_id, title, start_time, end_time) VALUES ('guide.tv', ?, ?, ?)",
                    (title, start.isoformat(), end.isoformat()))
    con.commit()
    con.close()
    with TestClient(app) as client:
        login = _login(client)
        r = client.get("/player_api.php", params={**login, "action": "get_short_epg", "stream_id": cid, "limit": 5}).json()
        titles = [base64.b64decode(x["title"]).decode() for x in r["epg_listings"]]
        assert titles == ["Morning News", "Weather"]
        assert int(r["epg_listings"][0]["stop_timestamp"]) > int(r["epg_listings"][0]["start_timestamp"])
        assert client.get("/player_api.php", params={**login, "action": "get_short_epg", "stream_id": "abc"}).json() == {"epg_listings": []}


def _guide_fixture():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    con = sqlite3.connect(DATABASE_PATH)
    con.execute("DELETE FROM channels")
    con.execute("DELETE FROM epg_programs")
    con.execute("INSERT INTO channels (name, category, stream_url, epg_id, is_favorite, custom_order) VALUES ('B & Co TV', 'News', 'https://example.com/b.m3u8', 'b.tv', 1, 1)")
    con.execute("INSERT INTO channels (name, category, stream_url, custom_order) VALUES ('A Movies', 'Movies', 'https://example.com/a.m3u8', 2)")
    con.execute("INSERT INTO epg_programs (channel_epg_id, title, start_time, end_time, description) VALUES ('b.tv', 'Tom <Live>', ?, ?, 'News & more')",
                ((now - timedelta(minutes=5)).isoformat(), (now + timedelta(minutes=55)).isoformat()))
    con.commit()
    con.close()


def test_xmltv_guide_for_smart_tv_apps():
    import xml.etree.ElementTree as ET

    with TestClient(app) as client:
        login = _login(client)
        _guide_fixture()
        assert client.get("/xmltv.php", params={"username": "nexonic", "password": "nope"}).status_code == 401
        root = ET.fromstring(client.get("/xmltv.php", params=login).content)
        assert [c.findtext("display-name") for c in root.findall("channel")] == ["B & Co TV"]
        prog = root.find("programme")
        assert prog.get("channel") == "b.tv" and prog.findtext("title") == "Tom <Live>"
        assert prog.get("start").endswith("+0000")


def test_network_tuner_is_off_by_default_and_works_when_on(monkeypatch):
    with TestClient(app) as client:
        _guide_fixture()
        assert client.get("/discover.json").status_code == 404
        monkeypatch.setenv("NEXONIC_TUNER", "1")
        d = client.get("/discover.json").json()
        assert d["LineupURL"].endswith("/lineup.json") and d["TunerCount"] == 4
        lineup = client.get("/lineup.json").json()
        assert [c["GuideName"] for c in lineup] == ["B & Co TV", "A Movies"]
        assert lineup[0]["GuideNumber"] == "1" and lineup[0]["URL"] == "https://example.com/b.m3u8"
        assert [c["GuideName"] for c in client.get("/lineup.json", params={"favourites": 1}).json()] == ["B & Co TV"]
        assert client.get("/lineup_status.json").json()["ScanInProgress"] == 0
        assert b"<friendlyName>" in client.get("/device.xml").content
        assert b"<programme" in client.get("/guide.xml").content
