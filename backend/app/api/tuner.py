"""
Network TV tuner emulation (HDHomeRun-compatible), so media servers on your network can add Nexonic TV Server as a
live TV source and use its channel list and guide. Off unless NEXONIC_TUNER=1, because these endpoints have no login
(that is how media servers expect a tuner to behave); they only list your channels and their public stream links.
"""
import hashlib
import os

from fastapi import APIRouter, HTTPException, Request, Response

from ..config import APP_NAME, APP_VERSION, LOCAL_IP, PORT
from ..database import get_db

router = APIRouter(tags=["Network TV tuner"])


def _enabled() -> None:
    if os.environ.get("NEXONIC_TUNER") != "1":
        raise HTTPException(status_code=404, detail="Network TV tuner is off (set NEXONIC_TUNER=1)")


def _base(request: Request) -> str:
    host = request.headers.get("host") or f"{LOCAL_IP}:{PORT}"
    return f"http://{host}"


def _device_id() -> str:
    return hashlib.sha1(f"{APP_NAME}-{LOCAL_IP}-{PORT}".encode()).hexdigest()[:8].upper()


@router.get("/discover.json")
async def discover(request: Request):
    _enabled()
    base = _base(request)
    return {
        "FriendlyName": APP_NAME,
        "Manufacturer": "Nexonic",
        "ModelNumber": "HDTC-2US",
        "FirmwareName": "hdhomeruntc_atsc",
        "FirmwareVersion": APP_VERSION,
        "DeviceID": _device_id(),
        "DeviceAuth": "nexonic",
        "TunerCount": int(os.environ.get("NEXONIC_TUNER_COUNT", "4")),
        "BaseURL": base,
        "LineupURL": f"{base}/lineup.json",
    }


@router.get("/lineup_status.json")
async def lineup_status():
    _enabled()
    return {"ScanInProgress": 0, "ScanPossible": 0, "Source": "Cable", "SourceList": ["Cable"]}


@router.get("/lineup.json")
async def lineup(favourites: int = 0):
    """Channels numbered in your order; `?favourites=1` lists only your favourites."""
    _enabled()
    where = "is_adult = 0" + (" AND is_favorite = 1" if favourites else "")
    async with get_db() as db:
        async with db.execute(
            f"SELECT id, name, stream_url FROM channels WHERE {where} ORDER BY custom_order ASC, name ASC LIMIT 5000"
        ) as cur:
            rows = await cur.fetchall()
    return [{"GuideNumber": str(i), "GuideName": r["name"], "URL": r["stream_url"]} for i, r in enumerate(rows, start=1)]


@router.post("/lineup.post")
async def lineup_post():
    _enabled()
    return Response(status_code=200)


@router.get("/device.xml")
async def device_xml(request: Request):
    _enabled()
    base = _base(request)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
  <specVersion><major>1</major><minor>0</minor></specVersion>
  <URLBase>{base}</URLBase>
  <device>
    <deviceType>urn:schemas-upnp-org:device:MediaServer:1</deviceType>
    <friendlyName>{APP_NAME}</friendlyName>
    <manufacturer>Nexonic</manufacturer>
    <modelName>HDTC-2US</modelName>
    <modelNumber>HDTC-2US</modelNumber>
    <serialNumber>{_device_id()}</serialNumber>
    <UDN>uuid:{_device_id()}</UDN>
  </device>
</root>
"""
    return Response(content=xml, media_type="application/xml")


@router.get("/guide.xml")
async def guide():
    """The TV guide for media servers (XMLTV), next to the tuner's channel list."""
    _enabled()
    from ..services.xtream_service import build_xmltv

    return Response(content=await build_xmltv(), media_type="application/xml")
