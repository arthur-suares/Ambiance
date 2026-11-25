"""MapBiomas raster tiles and same-extent Sentinel-2 comparison for DETER alerts."""

from datetime import date, timedelta
from functools import lru_cache
from io import BytesIO
import json
import math
import os
import ssl
from time import monotonic
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import certifi


MAPBIOMAS_API = "https://prd.plataforma.mapbiomas.org/api/v1/brazil/maps/map"
MAPBIOMAS_PIXELS = (3, 6, 4, 7, 5, 49, 12, 77, 11, 84, 50, 32, 29, 15, 39, 20,
                    40, 62, 41, 46, 47, 35, 48, 9, 21, 23, 24, 30, 75, 91, 25, 33, 31)
EARTH_SEARCH = "https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a/items"
COPERNICUS_CATALOG = "https://stac.dataspace.copernicus.eu/v1/collections"
TIF_HOST = "sentinel-cogs.s3.us-west-2.amazonaws.com"
WINDOW_DAYS = 60
FRAME_RADIUS = 0.022
HTTPS_CONTEXT = ssl.create_default_context()
HTTPS_CONTEXT.load_verify_locations(cafile=certifi.where())


def _get_json(url, params, headers=None):
    request = Request(f"{url}?{urlencode(params, doseq=True)}", headers=headers or {})
    with urlopen(request, timeout=10, context=HTTPS_CONTEXT) as response:
        return json.load(response)


@lru_cache(maxsize=96)
def _tile_template(year, pixels, interval):
    data = _get_json(MAPBIOMAS_API, {
        "subthemeKey": "coverage_coverage-30m-droufo",
        "legendKey": "coverage-bypu14",
        "year": year,
        "pixelValue": pixels,
        "propertyCode": "",
        "view3D": "false",
        "territoryCategoryId": 213,
    }, {"tenant-id": "mapbiomas"})
    url = data["url"]
    if not url.startswith("https://earthengine.googleapis.com/") or not url.endswith("/tiles/{z}/{x}/{y}"):
        raise OSError("O MapBiomas não retornou uma camada de cobertura válida.")
    return url


def mapbiomas_tiles(year: int, classes: list[int]) -> dict:
    if not 1985 <= year <= 2025:
        raise ValueError("Escolha um ano entre 1985 e 2025.")
    pixels = tuple(value for value in MAPBIOMAS_PIXELS if not classes or value in classes)
    omitted = sorted(set(classes).difference(pixels))
    return {
        "url": _tile_template(year, pixels, int(monotonic() // 900)) if pixels else None,
        "omitted": omitted,
    }


def alert_frame(lon: float, lat: float, observed: str) -> tuple:
    if not math.isfinite(lon) or not math.isfinite(lat) or not (-75 <= lon <= -32 and -35 <= lat <= 7):
        raise ValueError("Informe uma localização válida no Brasil.")
    when = date.fromisoformat(observed)
    # Keep the display centered on the alert in both captures.
    bounds = tuple(round(value, 5) for value in (
        lon - FRAME_RADIUS, lat - FRAME_RADIUS, lon + FRAME_RADIUS, lat + FRAME_RADIUS,
    ))
    return bounds, when


def _scenes(url, bounds, start, end):
    return _get_json(url, {
        "bbox": ",".join(map(str, bounds)),
        "datetime": f"{start}T00:00:00Z/{end}T23:59:59Z",
        "limit": 40,
    }).get("features", [])


def _choose_optical(items, bounds, when):
    candidates = []
    for item in items:
        url = item.get("assets", {}).get("visual", {}).get("href", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != TIF_HOST or not parsed.path.endswith("/TCI.tif"):
            continue
        extent = item.get("bbox")
        if not extent or not (extent[0] <= bounds[0] and extent[1] <= bounds[1]
                              and extent[2] >= bounds[2] and extent[3] >= bounds[3]):
            continue
        props = item["properties"]
        day = date.fromisoformat(props["datetime"][:10])
        cloud = props.get("eo:cloud_cover")
        # A one-point increase in scene cloudiness is worth approximately one day of proximity.
        score = abs((day - when).days) + (cloud if cloud is not None else 100)
        candidates.append((score, item["id"], {
            "id": item["id"], "date": day.isoformat(), "cloud": cloud,
            "visual": url, "source": f"{EARTH_SEARCH}/{item['id']}",
        }))
    return min(candidates, default=(None, "", None))[-1]


@lru_cache(maxsize=128)
def _comparison(bounds, when, interval):
    day = timedelta(days=1)
    window = timedelta(days=WINDOW_DAYS)
    before = _scenes(EARTH_SEARCH, bounds, when - window, when - day)
    after = _scenes(EARTH_SEARCH, bounds, when + day, when + window)
    return {
        "before": _choose_optical(before, bounds, when),
        "after": _choose_optical(after, bounds, when),
    }


def get_comparison(lon: float, lat: float, observed: str) -> dict:
    bounds, when = alert_frame(lon, lat, observed)
    scenes = _comparison(bounds, when, int(monotonic() // 3600))
    radar_params = urlencode({
        "bbox": ",".join(map(str, bounds)),
        "datetime": f"{when - timedelta(days=WINDOW_DAYS)}T00:00:00Z/{when + timedelta(days=WINDOW_DAYS)}T23:59:59Z",
    })
    return {
        "date": when.isoformat(),
        "window_days": WINDOW_DAYS,
        "scenes": {side: {k: v for k, v in scene.items() if k != "visual"} if scene else None
                   for side, scene in scenes.items()},
        "radar_catalog": f"{COPERNICUS_CATALOG}/sentinel-1-grd/items?{radar_params}",
    }


@lru_cache(maxsize=48)
def _render_rgb(url, bounds):
    import rasterio
    from rasterio.transform import from_bounds
    from rasterio.vrt import WarpedVRT

    side = 512
    transform = from_bounds(*bounds, side, side)
    ca_bundle = os.environ.get("CURL_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE") or certifi.where()
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_TIMEOUT=15,
                      GDAL_HTTP_CAINFO=ca_bundle,
                      GDAL_HTTP_MAX_RETRY=0, CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif"):
        with rasterio.open(url) as dataset, WarpedVRT(
            dataset, crs="EPSG:4326", transform=transform, width=side, height=side, add_alpha=True,
        ) as frame:
            pixels = frame.read()
            if not pixels[-1].any():
                raise OSError("Este trecho da imagem não contém observações.")
    from PIL import Image

    png = BytesIO()
    Image.fromarray(pixels.transpose(1, 2, 0)).save(png, format="PNG")
    return png.getvalue()


def comparison_image(lon: float, lat: float, observed: str, side: str, scene_id: str = "") -> bytes:
    if side not in ("before", "after"):
        raise ValueError("Escolha antes ou depois.")
    bounds, when = alert_frame(lon, lat, observed)
    scene = _comparison(bounds, when, int(monotonic() // 3600))[side]
    if scene is None or (scene_id and scene["id"] != scene_id):
        raise KeyError("Não há imagem para o período.")
    return _render_rgb(scene["visual"], bounds)
