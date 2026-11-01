from datetime import datetime, timezone
from typing import Dict, Any, List
from ..database import get_db, get_setting
import secrets

from ..config import APP_NAME, DEFAULT_XTREAM_USER, LOCAL_IP, PORT


async def authenticate_xtream(username: str, password: str) -> bool:
    """Validate Smart TV credentials against the local settings (constant-time comparison)."""
    stored_user = await get_setting("xtream_user", DEFAULT_XTREAM_USER) or ""
    stored_pass = await get_setting("xtream_pass", "") or ""
    if not stored_pass:
        return False
    return secrets.compare_digest(username, stored_user) and secrets.compare_digest(password, stored_pass)

async def get_server_info() -> Dict[str, Any]:
    return {
        "url": f"http://{LOCAL_IP}:{PORT}",
        "port": str(PORT),
        "https_port": "",
        "server_protocol": "http",
        "rtmp_port": "",
        "timezone": "UTC",
        "time_now": datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp_now": int(datetime.now(timezone.utc).replace(tzinfo=None).timestamp()),
        "process": True
    }

async def get_user_info(username: str) -> Dict[str, Any]:
    return {
        "username": username,
        "password": "valid",
        "message": f"Welcome to {APP_NAME}",
        "auth": 1,
        "status": "Active",
        "exp_date": "1999999999", # Never expires
        "is_trial": "0",
        "active_cons": "1",
        "created_at": "1700000000",
        "max_connections": "50",
        "allowed_output_formats": ["m3u8", "ts", "rtmp"]
    }

# Fixed category ID of the "Favourites" bouquet, so Smart TV apps keep it after a reload.
FAVOURITES_CATEGORY_ID = "999999"
FAVOURITES_CATEGORY_NAME = "Favourites"


async def get_live_categories() -> List[Dict[str, Any]]:
    """Return distinct categories formatted for Xtream Codes, with the Favourites bouquet first."""
    async with get_db() as db:
        query = "SELECT DISTINCT category FROM channels WHERE is_adult = 0 AND category IS NOT NULL ORDER BY category ASC"
        async with db.execute(query) as cur:
            rows = await cur.fetchall()

    categories = [{"category_id": FAVOURITES_CATEGORY_ID, "category_name": FAVOURITES_CATEGORY_NAME, "parent_id": 0}]
    for idx, r in enumerate(rows, start=1):
        cat_name = r["category"]
        categories.append({
            "category_id": str(idx),
            "category_name": cat_name,
            "parent_id": 0
        })
    return categories

async def get_live_streams(category_id: str | None = None) -> List[Dict[str, Any]]:
    """Return stream channels formatted for Xtream Codes."""
    cats = await get_live_categories()
    cat_map = {c["category_id"]: c["category_name"] for c in cats}
    name_to_id = {c["category_name"]: c["category_id"] for c in cats}

    favourites = category_id == FAVOURITES_CATEGORY_ID
    filter_cat_name = None if favourites else (cat_map.get(category_id) if category_id else None)

    async with get_db() as db:
        where_clauses = ["is_adult = 0"]
        params = []
        if favourites:
            where_clauses.append("is_favorite = 1")
        elif filter_cat_name:
            where_clauses.append("category = ?")
            params.append(filter_cat_name)

        where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        query = f"SELECT * FROM channels {where_sql} ORDER BY custom_order ASC, name ASC"

        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()

    streams = []
    for r in rows:
        cid = r["id"]
        cat_id = FAVOURITES_CATEGORY_ID if favourites else name_to_id.get(r["category"], "1")
        streams.append({
            "num": cid,
            "name": r["name"],
            "stream_type": "live",
            "stream_id": cid,
            "stream_icon": r["logo"] or "",
            "epg_channel_id": r["epg_id"] or "",
            "added": "1700000000",
            "category_id": cat_id,
            "custom_sid": "",
            "tv_archive": 0,
            "direct_source": r["stream_url"]
        })
    return streams

async def get_series_categories() -> List[Dict[str, Any]]:
    return [
        {"category_id": "1", "category_name": "TV Series 24/7", "parent_id": 0},
        {"category_id": "2", "category_name": "Sitcoms & Comedy", "parent_id": 0},
        {"category_id": "3", "category_name": "Drama & Sci-Fi", "parent_id": 0},
    ]

async def get_series_streams() -> List[Dict[str, Any]]:
    """Return series channels."""
    async with get_db() as db:
        query = "SELECT * FROM channels WHERE is_series = 1 AND is_adult = 0 ORDER BY name ASC"
        async with db.execute(query) as cur:
            rows = await cur.fetchall()

    series_list = []
    for r in rows:
        series_list.append({
            "num": r["id"],
            "name": r["name"],
            "series_id": r["id"],
            "cover": r["logo"] or "",
            "plot": r["description"] or f"24/7 TV Series Channel: {r['name']}",
            "genre": r["category"],
            "category_id": "1",
            "rating": "5.0"
        })
    return series_list

async def get_vod_categories() -> List[Dict[str, Any]]:
    cats = [
        {"category_id": "1", "category_name": "Offline Broadcast & Slates", "parent_id": 0},
        {"category_id": "2", "category_name": "Offline Cinema & Movies VOD", "parent_id": 0},
        {"category_id": "3", "category_name": "Offline Space & Nature Archives", "parent_id": 0},
        {"category_id": "5", "category_name": "Local Offline Media", "parent_id": 0}
    ]
    return cats

async def get_vod_streams() -> List[Dict[str, Any]]:
    async with get_db() as db:
        query = "SELECT * FROM channels WHERE (is_vod = 1 OR is_live = 0) AND is_adult = 0 ORDER BY name ASC"
        async with db.execute(query) as cur:
            rows = await cur.fetchall()

    vod_list = []
    for r in rows:
        vod_list.append({
            "num": r["id"],
            "name": r["name"],
            "stream_type": "movie",
            "stream_id": r["id"],
            "stream_icon": r["logo"] or "",
            "rating": "5.0",
            "rating_5based": 5,
            "added": "1700000000",
            "category_id": "2",
            "container_extension": "mp4",
            "direct_source": r["stream_url"]
        })
    return vod_list


async def get_short_epg(stream_id: str | None, limit: int = 4) -> Dict[str, Any]:
    """Now and next programmes of one channel, in the Xtream Codes format (titles and descriptions in base64)."""
    import base64

    if not stream_id or not str(stream_id).isdigit():
        return {"epg_listings": []}
    limit = max(1, min(int(limit or 4), 20))
    now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    async with get_db() as db:
        async with db.execute("SELECT epg_id FROM channels WHERE id = ? AND is_adult = 0", (int(stream_id),)) as cur:
            ch = await cur.fetchone()
        if not ch or not ch["epg_id"]:
            return {"epg_listings": []}
        async with db.execute(
            "SELECT * FROM epg_programs WHERE channel_epg_id = ? AND end_time > ? ORDER BY start_time ASC LIMIT ?",
            (ch["epg_id"], now_iso, limit),
        ) as cur:
            rows = await cur.fetchall()

    def b64(text: str | None) -> str:
        return base64.b64encode((text or "").encode()).decode()

    listings = []
    for r in rows:
        try:
            start = datetime.fromisoformat(r["start_time"]).replace(tzinfo=timezone.utc)
            end = datetime.fromisoformat(r["end_time"]).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        listings.append({
            "id": str(r["id"]),
            "epg_id": ch["epg_id"],
            "channel_id": ch["epg_id"],
            "title": b64(r["title"]),
            "description": b64(r["description"]),
            "lang": "",
            "start": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end.strftime("%Y-%m-%d %H:%M:%S"),
            "start_timestamp": str(int(start.timestamp())),
            "stop_timestamp": str(int(end.timestamp())),
        })
    return {"epg_listings": listings}


def _xmltv_time(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y%m%d%H%M%S +0000")


async def build_xmltv(hours: int = 48) -> str:
    """The TV guide as XMLTV: every channel with a guide ID, and its programmes from now for the next `hours`."""
    from datetime import timedelta
    from xml.sax.saxutils import escape, quoteattr

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    until = (now + timedelta(hours=hours)).isoformat()
    async with get_db() as db:
        async with db.execute(
            "SELECT DISTINCT epg_id, name, logo FROM channels WHERE is_adult = 0 AND epg_id IS NOT NULL AND epg_id != '' ORDER BY name"
        ) as cur:
            channels = await cur.fetchall()
        ids = [c["epg_id"] for c in channels]
        programmes = []
        if ids:
            marks = ",".join("?" for _ in ids)
            async with db.execute(
                f"SELECT * FROM epg_programs WHERE channel_epg_id IN ({marks}) AND end_time > ? AND start_time < ? "
                "ORDER BY channel_epg_id, start_time LIMIT 50000",
                (*ids, now.isoformat(), until),
            ) as cur:
                programmes = await cur.fetchall()

    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<!DOCTYPE tv SYSTEM "xmltv.dtd">', f"<tv generator-info-name={quoteattr(APP_NAME)}>"]
    seen = set()
    for c in channels:
        if c["epg_id"] in seen:
            continue
        seen.add(c["epg_id"])
        out.append(f"  <channel id={quoteattr(c['epg_id'])}>")
        out.append(f"    <display-name>{escape(c['name'])}</display-name>")
        if c["logo"]:
            out.append(f"    <icon src={quoteattr(c['logo'])} />")
        out.append("  </channel>")
    for p in programmes:
        try:
            start, stop = _xmltv_time(p["start_time"]), _xmltv_time(p["end_time"])
        except ValueError:
            continue
        out.append(f"  <programme start=\"{start}\" stop=\"{stop}\" channel={quoteattr(p['channel_epg_id'])}>")
        out.append(f"    <title>{escape(p['title'] or '')}</title>")
        if p["description"]:
            out.append(f"    <desc>{escape(p['description'])}</desc>")
        if p["category"]:
            out.append(f"    <category>{escape(p['category'])}</category>")
        out.append("  </programme>")
    out.append("</tv>")
    return "\n".join(out) + "\n"
