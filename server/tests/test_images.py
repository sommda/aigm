"""The image generator (docs/PORTRAITS.md 4 and 8.3), against a fake HTTP server."""

import base64
import json

import httpx
import pytest

from aigm import images
from aigm.config import Settings
from aigm.images import FakeImages, ImageError, OpenAIImages, make_images, sniff

PNG = images._png(2, 2, (1, 2, 3))
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "


def settings(**kw) -> Settings:
    return Settings(_env_file=None, **{**{"openai_api_key": "sk-secret-key", "image_model": "img-1"}, **kw})


def client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def reply(data: bytes, **extra):
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(data).decode()}], "usage": {"n": 1}, **extra})


def test_portraits_need_a_key_a_model_and_the_switch():
    assert settings().portraits_on
    assert not settings(openai_api_key=None).portraits_on
    assert not settings(image_model=" ").portraits_on
    assert not settings(images=False).portraits_on


def test_make_images_picks_the_real_the_fake_or_nothing():
    assert isinstance(make_images(settings()), OpenAIImages)
    assert make_images(settings(openai_api_key=None)) is None
    assert isinstance(make_images(settings(test_mode=True, openai_api_key=None)), FakeImages)
    assert make_images(settings(test_mode=True, images=False)) is None


def test_sniff_knows_the_formats_it_serves():
    assert sniff(PNG) == "png" and sniff(WEBP) == "webp" and sniff(b"\xff\xd8\xffxx") == "jpg" and sniff(b"GIF89a") is None


async def test_a_request_carries_the_model_size_format_and_key_and_the_image_comes_back():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"], seen["body"] = request.headers["authorization"], json.loads(request.content)
        return reply(WEBP)

    img = await OpenAIImages(settings(image_quality="low"), client(handler)).generate("a prompt")
    assert seen["auth"] == "Bearer sk-secret-key"
    assert seen["body"] == {"model": "img-1", "prompt": "a prompt", "size": "1024x1024", "n": 1,
                            "output_format": "webp", "output_compression": 80, "quality": "low"}
    assert (img.ext, img.model, img.usage) == ("webp", "img-1", {"n": 1})


async def test_quality_is_left_out_unless_set():
    assert "quality" not in OpenAIImages(settings()).body("x")


async def test_an_image_given_as_a_url_is_fetched():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "files.test":
            return httpx.Response(200, content=PNG)
        return httpx.Response(200, json={"data": [{"url": "https://files.test/a.png"}]})

    assert (await OpenAIImages(settings(), client(handler)).generate("x")).ext == "png"


@pytest.mark.parametrize(
    ("status", "body", "kind"),
    [
        (400, {"error": {"code": "moderation_blocked", "message": "no"}}, images.MODERATION),
        (400, {"error": {"type": "content_policy_violation", "message": "no"}}, images.MODERATION),
        (401, {"error": {"message": "bad key"}}, images.QUOTA),
        (429, {"error": {"code": "insufficient_quota", "message": "pay"}}, images.QUOTA),
        (429, {"error": {"code": "rate_limit_exceeded", "message": "slow"}}, images.UNAVAILABLE),
        (500, {"error": {"message": "oops"}}, images.UNAVAILABLE),
        (502, None, images.UNAVAILABLE),
    ],
)
async def test_errors_are_sorted_into_the_kinds_the_pipeline_acts_on(status, body, kind):
    handler = lambda request: httpx.Response(status, json=body) if body else httpx.Response(status, text="<html>")  # noqa: E731
    with pytest.raises(ImageError) as caught:
        await OpenAIImages(settings(), client(handler)).generate("x")
    assert caught.value.kind == kind


@pytest.mark.parametrize("response", [
    httpx.Response(200, json={"data": []}),
    httpx.Response(200, json={"data": [{"b64_json": "!!not base64!!"}]}),
    httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(b"not a picture").decode()}]}),
    httpx.Response(200, text="nope"),
])
async def test_a_reply_without_a_usable_picture_is_a_bad_reply(response):
    with pytest.raises(ImageError) as caught:
        await OpenAIImages(settings(), client(lambda request: response)).generate("x")
    assert caught.value.kind == images.BAD_REPLY


async def test_a_network_failure_is_unavailable_and_never_shows_the_key():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(ImageError) as caught:
        await OpenAIImages(settings(), client(handler)).generate("x")
    assert caught.value.kind == images.UNAVAILABLE and "sk-secret-key" not in str(caught.value)


async def test_the_fake_makes_a_valid_png_that_depends_on_the_prompt_and_can_fail_on_cue():
    fake = FakeImages(fail=[ImageError(images.UNAVAILABLE, "down")])
    with pytest.raises(ImageError):
        await fake.generate("a")
    one, two = await fake.generate("a"), await fake.generate("b")
    assert sniff(one.data) == "png" and one.data != two.data
    assert fake.prompts == ["a", "a", "b"]
