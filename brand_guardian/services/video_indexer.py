"""Azure Video Indexer (ARM-based account): upload, poll, and extract speech-to-text + OCR."""

import logging
import time
from typing import Any

import requests
from azure.identity import DefaultAzureCredential

from brand_guardian.config import Settings

log = logging.getLogger(__name__)

VI_API = "https://api.videoindexer.ai"
ARM_API = "https://management.azure.com"
ARM_API_VERSION = "2024-01-01"


class VideoIndexerError(RuntimeError):
    pass


class VideoIndexerService:
    def __init__(self, settings: Settings):
        self.s = settings
        self._credential = DefaultAzureCredential()

    def _access_token(self) -> str:
        """Exchange an ARM token for a Video Indexer account access token."""
        arm_token = self._credential.get_token(f"{ARM_API}/.default").token
        url = (
            f"{ARM_API}/subscriptions/{self.s.subscription_id}/resourceGroups/{self.s.resource_group}"
            f"/providers/Microsoft.VideoIndexer/accounts/{self.s.vi_account_name}"
            f"/generateAccessToken?api-version={ARM_API_VERSION}"
        )
        resp = requests.post(
            url,
            json={"permissionType": "Contributor", "scope": "Account"},
            headers={"Authorization": f"Bearer {arm_token}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["accessToken"]

    @property
    def _account_url(self) -> str:
        return f"{VI_API}/{self.s.vi_location}/Accounts/{self.s.vi_account_id}"

    def upload(self, video_url: str, name: str) -> str:
        resp = requests.post(
            f"{self._account_url}/Videos",
            params={
                "accessToken": self._access_token(),
                "name": name[:80],
                "videoUrl": video_url,
                "privacy": "Private",
                "indexingPreset": "Default",
            },
            timeout=60,
        )
        if not resp.ok:
            raise VideoIndexerError(f"Upload failed ({resp.status_code}): {resp.text}")
        video_id = resp.json()["id"]
        log.info("Video Indexer upload accepted, video_id=%s", video_id)
        return video_id

    def wait_for_index(self, video_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.s.vi_timeout
        token = self._access_token()
        token_issued = time.monotonic()
        while time.monotonic() < deadline:
            if time.monotonic() - token_issued > 45 * 60:  # tokens last ~1h
                token, token_issued = self._access_token(), time.monotonic()
            resp = requests.get(
                f"{self._account_url}/Videos/{video_id}/Index",
                params={"accessToken": token},
                timeout=60,
            )
            resp.raise_for_status()
            index = resp.json()
            state = index.get("state")
            log.info("Video Indexer state=%s", state)
            if state == "Processed":
                return index
            if state == "Failed":
                video = (index.get("videos") or [{}])[0]
                code, msg = video.get("failureCode"), video.get("failureMessage")
                hint = (
                    " (Video Indexer's managed identity needs the 'Storage Blob Data Owner' role "
                    "on its linked storage account)" if code == "StorageAccessDenied" else ""
                )
                raise VideoIndexerError(f"Indexing failed for video {video_id}: {code} - {msg}{hint}")
            time.sleep(self.s.vi_poll_interval)
        raise VideoIndexerError(f"Timed out after {self.s.vi_timeout}s waiting for video {video_id}")


def _short_ts(ts: str | None) -> str:
    """'0:01:23.45' -> '01:23' (or '1:01:23' for videos over an hour)."""
    if not ts:
        return "??:??"
    h, m, s = ts.split(":")
    s = s.split(".")[0]
    return f"{int(h)}:{m}:{s}" if int(h) else f"{m}:{s}"


def extract_insights(index: dict[str, Any]) -> dict[str, Any]:
    """Pull a timestamped transcript, OCR text, and basic metadata from a Video Indexer index."""
    videos = index.get("videos") or [{}]
    insights = videos[0].get("insights", {})

    transcript_lines = []
    for item in insights.get("transcript", []):
        text = (item.get("text") or "").strip()
        if not text:
            continue
        start = (item.get("instances") or [{}])[0].get("start")
        transcript_lines.append(f"[{_short_ts(start)}] {text}")

    ocr_lines, seen = [], set()
    for item in insights.get("ocr", []):
        text = (item.get("text") or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        start = (item.get("instances") or [{}])[0].get("start")
        ocr_lines.append(f"[{_short_ts(start)}] {text}")

    return {
        "transcript": "\n".join(transcript_lines),
        "ocr_text": "\n".join(ocr_lines),
        "video_metadata": {
            "name": index.get("name"),
            "duration_seconds": (index.get("summarizedInsights") or {}).get("duration", {}).get("seconds"),
            "language": insights.get("sourceLanguage"),
        },
    }
