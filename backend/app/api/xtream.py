from typing import Optional
from urllib.parse import quote
from fastapi import APIRouter, Query, HTTPException, Response
from fastapi.responses import RedirectResponse, PlainTextResponse
from ..database import get_db
from ..services.xtream_service import (
    authenticate_xtream,
    get_server_info,
    get_user_info,
    get_live_categories,
    get_live_streams,
    get_series_categories,
    get_series_streams,
    get_vod_categories,
    get_vod_streams,
    get_short_epg,
    build_xmltv,
)
from ..config import APP_NAME, LOCAL_IP, PORT

router = APIRouter(tags=["Xtream Codes / Smart TV API"])

@router.get("/player_api.php")
async def player_api(
    username: str = Query(...),
    password: str = Query(...),
    action: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    stream_id: Optional[str] = Query(None),
    series_id: Optional[str] = Query(None),
    limit: Optional[int] = Query(None)
):
    """
    Standard Xtream Codes API endpoint used by Smart TV IPTV apps
    (e.g., IPTV Smarters, TiviMate, Nanomid, Smart IPTV, IBO Player).
    """
    valid = await authenticate_xtream(username, password)
    if not valid:
        return {"user_info": {"auth": 0, "status": "Disabled", "message": "Invalid credentials"}}

    if not action:
        # Base login check
        user_info = await get_user_info(username)
        server_info = await get_server_info()
        return {"user_info": user_info, "server_info": server_info}

    if action == "get_live_categories":
        return await get_live_categories()

    if action == "get_live_streams":
        return await get_live_streams(category_id=category_id)

    if action == "get_series_categories":
        return await get_series_categories()

    if action == "get_series":
        return await get_series_streams()

    if action == "get_series_info":
        # Return single episode matching series stream
        if not series_id:
            return {}
        async with get_db() as db:
            async with db.execute("SELECT * FROM channels WHERE id = ? AND is_adult = 0", (series_id,)) as cur:
                r = await cur.fetchone()
        if not r:
            return {}
        return {
            "seasons": [{"season_number": 1, "name": "Season 1", "episode_count": 1}],
            "info": {
                "name": r["name"],
                "cover": r["logo"] or "",
                "plot": r["description"] or f"24/7 Series Channel: {r['name']}",
                "genre": r["category"],
                "releaseDate": "2026"
            },
            "episodes": {
                "1": [{
                    "id": r["id"],
                    "episode_num": 1,
                    "title": f"{r['name']} (Live Marathon Stream)",
                    "container_extension": "m3u8",
                    "info": {"plot": r["description"] or "24/7 continuous broadcast"}
                }]
            }
        }

    if action == "get_vod_categories":
        return await get_vod_categories()

    if action == "get_vod_streams":
        return await get_vod_streams()

    if action in ("get_short_epg", "get_simple_data_table"):
        return await get_short_epg(stream_id, limit or 4)

    return {"error": f"Unknown action {action}"}

@router.get("/get.php")
async def get_m3u_playlist(
    username: str = Query(...),
    password: str = Query(...),
    type: Optional[str] = Query("m3u_plus"),
    output: Optional[str] = Query("m3u8"),
    favourites: int = Query(0, description="1 = only your favourite channels"),
):
    """
    Generates tailored M3U playlist for Smart TV or any external IPTV client.
    """
    valid = await authenticate_xtream(username, password)
    if not valid:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with get_db() as db:
        where = "is_adult = 0" + (" AND is_favorite = 1" if favourites else "")
        query = f"SELECT * FROM channels WHERE {where} ORDER BY category ASC, name ASC"
        async with db.execute(query) as cur:
            rows = await cur.fetchall()

    def attr(value) -> str:  # a quote inside a name would break the line for players
        return str(value or "").replace('"', "'")

    guide_url = f"http://{LOCAL_IP}:{PORT}/xmltv.php?username={quote(username)}&password={quote(password)}"
    lines = [f'#EXTM3U url-tvg="{guide_url}" x-tvg-url="{guide_url}"']  # players load the TV guide by themselves
    for r in rows:
        tvg_id = attr(r["epg_id"])
        tvg_name = attr(r["name"])
        tvg_logo = attr(r["logo"])
        group_title = attr(r["category"] or "General")
        stream_url = f"http://{LOCAL_IP}:{PORT}/live/{username}/{password}/{r['id']}.m3u8"
        lines.append(f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-name="{tvg_name}" tvg-logo="{tvg_logo}" group-title="{group_title}",{r["name"]}')
        lines.append(stream_url)

    m3u_content = "\n".join(lines)
    return Response(
        content=m3u_content,
        media_type="application/x-mpegurl",
        headers={"Content-Disposition": 'inline; filename="nexonic_tv_server.m3u"'}
    )

@router.get("/live/{username}/{password}/{stream_id}.m3u8")
@router.get("/live/{username}/{password}/{stream_id}.ts")
async def stream_live_channel(username: str, password: str, stream_id: int):
    """
    Handles streaming for Smart TV clients.
    Validates user credentials and redirects directly to channel stream.
    """
    valid = await authenticate_xtream(username, password)
    if not valid:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with get_db() as db:
        async with db.execute("SELECT stream_url, fallback_urls FROM channels WHERE id = ? AND is_adult = 0", (stream_id,)) as cur:
            row = await cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Channel not found")

    target_url = row["stream_url"]
    return RedirectResponse(url=target_url, status_code=302)

@router.get("/series/{username}/{password}/{stream_id}.m3u8")
async def stream_series_channel(username: str, password: str, stream_id: int):
    return await stream_live_channel(username, password, stream_id)

@router.get("/xmltv.php")
async def get_xmltv_epg(username: str = Query(...), password: str = Query(...)):
    """Outputs XMLTV for Smart TV guide."""
    valid = await authenticate_xtream(username, password)
    if not valid:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return Response(content=await build_xmltv(), media_type="application/xml")
