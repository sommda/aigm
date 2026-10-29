"""Generating a portrait image (docs/PORTRAITS.md 4 and 8.3).

`OpenAIImages` calls the image API directly with httpx, so it does not depend on an SDK that may not know the
configured model. `FakeImages` makes a small valid PNG offline, for tests and `--test` mode. Both raise `ImageError`
with a `kind` the pipeline acts on, and never put the key in a message."""

import base64
import hashlib
import struct
import zlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import httpx

if TYPE_CHECKING:  # config imports the world, which imports the portrait record, which imports this module
    from aigm.config import Settings

API_URL = "https://api.openai.com/v1/images/generations"
TIMEOUT = 240.0  # seconds; one image takes 15 to 60
OUTPUT_FORMAT = "webp"  # about a tenth of the size of a png (measured in docs/PORTRAITS.md 15)
OUTPUT_COMPRESSION = 80

# What went wrong, as the pipeline needs to tell it apart (docs/PORTRAITS.md 8.3).
MODERATION, QUOTA, UNAVAILABLE, BAD_REPLY = "moderation", "quota", "unavailable", "bad_reply"


class ImageError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass
class Image:
    data: bytes
    ext: str  # png, webp or jpg
    model: str
    usage: dict[str, Any] | None = None


class Images(Protocol):
    model: str

    async def generate(self, prompt: str) -> Image: ...


def sniff(data: bytes) -> str | None:
    """The file extension for image bytes, or None if they are not a picture we serve."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    return None


def _classify(status: int, body: Any) -> ImageError:
    err = body.get("error") if isinstance(body, dict) else None
    err = err if isinstance(err, dict) else {}
    code, kind, text = str(err.get("code") or ""), str(err.get("type") or ""), str(err.get("message") or "")[:300]
    blob = f"{code} {kind}".lower()
    if "moderation" in blob or "content_policy" in blob or "safety" in blob:
        return ImageError(MODERATION, f"the image model refused the prompt: {text}")
    if status in (401, 403) or "quota" in blob or "billing" in blob or "insufficient" in blob:
        return ImageError(QUOTA, f"the image API refused the request ({status}): {text}")
    return ImageError(UNAVAILABLE, f"the image API answered {status}: {text}")


class OpenAIImages:
    def __init__(self, settings: "Settings", client: httpx.AsyncClient | None = None) -> None:
        assert settings.openai_api_key and settings.image_model
        self.model = settings.image_model
        self._key = settings.openai_api_key
        self._size = settings.image_size
        self._quality = settings.image_quality
        self._client = client

    def body(self, prompt: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model, "prompt": prompt, "size": self._size, "n": 1,
            "output_format": OUTPUT_FORMAT, "output_compression": OUTPUT_COMPRESSION,
        }  # fmt: skip
        if self._quality:
            body["quality"] = self._quality
        return body

    async def generate(self, prompt: str) -> Image:
        client = self._client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            return await self._generate(client, prompt)
        finally:
            if self._client is None:
                await client.aclose()

    async def _generate(self, client: httpx.AsyncClient, prompt: str) -> Image:
        try:
            resp = await client.post(API_URL, json=self.body(prompt), headers={"Authorization": f"Bearer {self._key}"})
        except httpx.HTTPError as exc:  # no message: some carry the request, and with it the key
            raise ImageError(UNAVAILABLE, f"could not reach the image API ({type(exc).__name__})") from None
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if resp.status_code != 200:
            raise _classify(resp.status_code, payload)
        item = ((payload.get("data") or [None])[0]) if isinstance(payload, dict) else None
        if not isinstance(item, dict) or not (item.get("b64_json") or item.get("url")):
            raise ImageError(BAD_REPLY, "the image API's reply held no image")
        try:
            if item.get("b64_json"):
                data = base64.b64decode(item["b64_json"])
            else:
                data = (await client.get(item["url"])).content
        except (ValueError, httpx.HTTPError):
            raise ImageError(BAD_REPLY, "the image could not be read") from None
        ext = sniff(data)
        if ext is None:
            raise ImageError(BAD_REPLY, "the image API returned something that is not a picture")
        usage = payload.get("usage")
        return Image(data, ext, self.model, usage if isinstance(usage, dict) else None)


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """A solid-color png made with the standard library."""

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    row = b"\x00" + bytes(rgb) * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


class FakeImages:
    """Offline stand-in: a small solid png whose color comes from the prompt. `fail` makes the next calls raise."""

    model = "fake-image"

    def __init__(self, fail: list[ImageError] | None = None) -> None:
        self.prompts: list[str] = []
        self.fail = list(fail or [])

    async def generate(self, prompt: str) -> Image:
        self.prompts.append(prompt)
        if self.fail:
            raise self.fail.pop(0)
        digest = hashlib.sha256(prompt.encode()).digest()
        return Image(_png(16, 16, (digest[0], digest[1], digest[2])), "png", self.model)


def make_images(settings: "Settings") -> Images | None:
    """The generator for this server, or None when portraits are off."""
    if not settings.images:
        return None
    if settings.test_mode:
        return FakeImages()
    return OpenAIImages(settings) if settings.portraits_on else None
