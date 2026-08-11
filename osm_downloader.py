
import os
import time
import requests

from dotenv import load_dotenv
from map_profile import BoundingBox


load_dotenv()


ENDPOINTS = [
    "https://overpass-api.de/api/map",
    "https://overpass.kumi.systems/api/map",
    "https://overpass.private.coffee/api/map",
]

REQUEST_TIMEOUT_S: int = 180
RETRYABLE_HTTP_STATUS_CODES = frozenset({502, 503, 504})
RETRY_DELAY_SECONDS = 1


def _require_contact_email() -> str:
    contact_email = os.getenv("OSM_DOWNLOADER_CONTACT_EMAIL", "")
    if not contact_email:
        raise ValueError(
            "OSM_DOWNLOADER_CONTACT_EMAIL is empty. "
            "Add OSM_DOWNLOADER_CONTACT_EMAIL=your_email@example.com to the .env file and restart the script. "
        )
    return contact_email


def _build_request_headers(contact_email: str) -> dict[str, str]:
    return {
        "Accept": "application/xml",
        "User-Agent": f"OSM-Downloader-Script/1.0 (contact: {contact_email})",
    }


class OsmDownloadError(Exception):
    """Raised when every configured Overpass mirror fails to respond."""


def _fetch_from_mirror(url: str, params: dict[str, str], headers: dict[str, str]) -> bytes:
    response = requests.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT_S)
    response.raise_for_status()
    return response.content


def _save_extract(destination_path: str, osm_xml_content: bytes) -> None:
    os.makedirs(os.path.dirname(destination_path) or ".", exist_ok=True)
    with open(destination_path, "wb") as osm_file:
        osm_file.write(osm_xml_content)


def download_osm_extract(bbox: BoundingBox, destination_path: str, overwrite: bool = False) -> str:
    if os.path.exists(destination_path) and not overwrite:
        print(f"[osm_downloader] Reusing existing extract: {destination_path}")
        return destination_path

    headers = _build_request_headers(_require_contact_email())
    params = {"bbox": bbox.to_overpass_bbox()}
    last_error: requests.exceptions.RequestException | None = None

    for mirror_url in ENDPOINTS:
        print(f"[osm_downloader] Trying endpoint: {mirror_url}...")
        try:
            osm_xml_content = _fetch_from_mirror(mirror_url, params, headers)
            _save_extract(destination_path, osm_xml_content)
            print(f"[osm_downloader] Success! Saved: {destination_path}")
            return destination_path

        except requests.exceptions.HTTPError as http_error:
            status_code = http_error.response.status_code
            if status_code in RETRYABLE_HTTP_STATUS_CODES:
                print(f"[osm_downloader] Server error ({status_code}): Gateway overloaded. Trying next mirror...")
                last_error = http_error
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            print(f"[osm_downloader] HTTP Error {status_code}: {http_error}")
            print(f"[osm_downloader] Response: {http_error.response.text[:200]}")
            raise

        except requests.exceptions.RequestException as connection_error:
            print(f"[osm_downloader] Connection failed: {connection_error}. Trying next mirror...")
            last_error = connection_error
            time.sleep(RETRY_DELAY_SECONDS)
            continue

    print("[osm_downloader] All endpoints failed.")
    if last_error is not None:
        raise OsmDownloadError("Failed to download from all available Overpass mirrors.") from last_error
    raise OsmDownloadError("No Overpass endpoints are configured in ENDPOINTS.")


def build_manual_query(bbox: BoundingBox) -> str:
    bbox_string = f"{bbox.south_west_lat},{bbox.south_west_lon},{bbox.north_east_lat},{bbox.north_east_lon}"
    return (
        f"[out:xml][timeout:{REQUEST_TIMEOUT_S}];\n"
        f"(\n"
        f"  node({bbox_string});\n"
        f"  way({bbox_string});\n"
        f"  relation({bbox_string});\n"
        f");\n"
        f"out body;\n"
        f">;\n"
        f"out skel qt;"
    )


def print_manual_instructions(bbox: BoundingBox, destination_path: str) -> None:
    print("\n" + "=" * 70)
    print(f"No local file at: {destination_path}")
    print("Get it manually (about 2 minutes, one time for this map):")
    print("=" * 70)
    print("1. Open https://overpass-turbo.eu")
    print("2. Paste this query and click Run:\n")
    print(build_manual_query(bbox))
    print("\n3. Click Export (top right) -> download/save as raw OSM data")
    print(f"4. Save the file as exactly: {destination_path}")
    print("5. Re-run this script.")
    print("=" * 70 + "\n")