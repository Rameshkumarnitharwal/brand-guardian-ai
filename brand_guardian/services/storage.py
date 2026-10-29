"""Ingestion: download a YouTube video (or use a local file) and stage it in Azure Blob Storage."""

import logging
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.core.exceptions import ResourceExistsError
from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas

from brand_guardian.config import Settings

log = logging.getLogger(__name__)


class VideoTooLongError(ValueError):
    pass


def download_youtube(url: str, out_dir: Path, max_minutes: float, cookies_browser: str = "") -> Path:
    """Download the best single-file MP4 for a YouTube URL using yt-dlp.

    Checks duration first: Video Indexer bills per minute, so long videos are refused.
    """
    import imageio_ffmpeg
    import yt_dlp

    opts = {
        # YouTube often serves only separate video/audio streams; ffmpeg merges them into one MP4.
        # Prefer H.264 (avc1): Video Indexer rejects AV1 with InvalidFileFormat.
        # 720p is plenty for OCR and keeps the upload small.
        "format": "bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b[height<=720][vcodec^=avc1]/bv*[height<=720][vcodec^=avc1]+ba",
        "merge_output_format": "mp4",
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "noprogress": True,
        "noplaylist": True,
        # YouTube's player JS must be solved by a JS runtime; Node is the common one on dev machines.
        "js_runtimes": {"node": {}, "deno": {}},
    }
    if cookies_browser:
        # Signed-in cookies avoid YouTube's "confirm you're not a bot" block.
        opts["cookiesfrombrowser"] = (cookies_browser, None, None, None)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        minutes = (info.get("duration") or 0) / 60
        if not info.get("duration") or minutes > max_minutes:
            raise VideoTooLongError(
                f"Video is {minutes:.1f} min (unknown if 0); limit is {max_minutes} min. "
                "Raise MAX_VIDEO_MINUTES in .env to allow it."
            )
        info = ydl.process_ie_result(info, download=True)
        return Path(ydl.prepare_filename(info))


def safe_video_name(source: str) -> str:
    stem = Path(source).stem if Path(source).exists() else source
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-")[-60:] or "video"
    return f"{slug}-{uuid.uuid4().hex[:8]}"


class StorageService:
    def __init__(self, settings: Settings):
        self.client = BlobServiceClient.from_connection_string(settings.storage_connection_string)
        self.container = settings.storage_container
        self.max_video_minutes = settings.max_video_minutes
        self.cookies_browser = settings.ytdlp_cookies_browser
        try:
            self.client.create_container(self.container)
        except ResourceExistsError:
            pass

    def upload(self, local_path: Path, blob_name: str) -> str:
        blob = self.client.get_blob_client(self.container, blob_name)
        with open(local_path, "rb") as f:
            blob.upload_blob(f, overwrite=True)
        log.info("Uploaded %s to blob %s/%s", local_path.name, self.container, blob_name)
        return self._sas_url(blob_name)

    def _sas_url(self, blob_name: str, hours: int = 6) -> str:
        """Read-only SAS URL so Video Indexer can fetch the blob."""
        token = generate_blob_sas(
            account_name=self.client.account_name,
            container_name=self.container,
            blob_name=blob_name,
            account_key=self.client.credential.account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=hours),
        )
        return f"{self.client.url.rstrip('/')}/{self.container}/{blob_name}?{token}"

    def ingest(self, source: str, video_name: str) -> str:
        """Stage a YouTube URL or local video file in Blob Storage; returns a SAS URL."""
        local = Path(source)
        if local.is_file():
            return self.upload(local, f"{video_name}{local.suffix}")
        with tempfile.TemporaryDirectory() as tmp:
            path = download_youtube(source, Path(tmp), self.max_video_minutes, self.cookies_browser)
            return self.upload(path, f"{video_name}{path.suffix}")
