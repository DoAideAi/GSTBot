"""Crawler files and OG image generation.

The site's sitemap and robots.txt are the frontend's: ``public/robots.txt``,
and the sitemap the prerender build writes from the same list of pages it
prerenders, so the two cannot drift. This module used to keep a second copy
of both by hand, and it had drifted — 91 of the 1,134 indexable pages missing,
every HSN page dated "changed today" on every request, and a robots.txt that
pointed crawlers at that sitemap while disallowing /api/, the path it lives
under. Its two routes now redirect to the site's own files, for anything that
was ever given their address.

The OG image endpoint renders a branded 1200x630 PNG with Pillow so every
page can carry a unique social preview without shipping pre-built images.
"""
from __future__ import annotations

import io
import logging
import textwrap
from functools import lru_cache

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import RedirectResponse
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.core.rate_limit import RateLimit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

_seo_limit = RateLimit("seo_sitemap", "30/minute", by="ip")

SITE = settings.public_site_url


def _to_the_site(path: str) -> RedirectResponse:
    # Permanent: a crawler that was given this address should replace it with
    # the site's own, not keep asking here.
    return RedirectResponse(f"{SITE}{path}", status_code=301)


@router.get(
    "/seo/sitemap.xml",
    summary="Moved: the sitemap is the site's /sitemap.xml",
    description=(
        "A permanent redirect to `/sitemap.xml`, which the frontend build writes "
        "from the same list of pages it prerenders."
    ),
    status_code=301,
    response_class=RedirectResponse,
    dependencies=[Depends(_seo_limit)],
)
def sitemap() -> RedirectResponse:
    return _to_the_site("/sitemap.xml")


@router.get(
    "/seo/robots.txt",
    summary="Moved: robots.txt is the site's /robots.txt",
    description="A permanent redirect to `/robots.txt`, the frontend's own file.",
    status_code=301,
    response_class=RedirectResponse,
    dependencies=[Depends(_seo_limit)],
)
def robots() -> RedirectResponse:
    return _to_the_site("/robots.txt")


_og_limit = RateLimit("seo_og_image", "60/minute", by="ip")

_OG_WIDTH = 1200
_OG_HEIGHT = 630
_BG_COLOR = (37, 99, 235)  # #2563EB
_TEXT_COLOR = (255, 255, 255)
_WATERMARK_COLOR = (255, 255, 255, 153)  # 60% opacity white


def _wrap_text(text: str, max_chars: int = 35) -> list[str]:
    return textwrap.wrap(text, width=max_chars) or [""]


# Rendered once per title, not per request. A render is ~300 ms of PIL on the
# API worker, and the titles are the site's own page names: every crawler and
# chat app that unfurls a link asks for the same few dozen images, each a fresh
# render behind a Cache-Control the server itself never honoured. ~30 KB a PNG,
# so the bound is a few MB per worker even under a flood of made-up titles.
@lru_cache(maxsize=128)
def _render_og_image(title: str, subtitle: str | None = None) -> bytes:
    img = Image.new("RGB", (_OG_WIDTH, _OG_HEIGHT), _BG_COLOR)
    draw = ImageDraw.Draw(img)

    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 52)
        subtitle_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        watermark_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
    except OSError:  # IOError is an alias of OSError
        logger.warning("DejaVu fonts not found, falling back to default bitmap font")
        title_font = ImageFont.load_default()
        subtitle_font = ImageFont.load_default()
        watermark_font = ImageFont.load_default()

    title_lines = _wrap_text(title, max_chars=30)
    line_height = 64
    total_height = len(title_lines) * line_height
    if subtitle:
        total_height += 60

    y = (_OG_HEIGHT - total_height) // 2 - 30

    for line in title_lines:
        bbox = draw.textbbox((0, 0), line, font=title_font)
        w = bbox[2] - bbox[0]
        draw.text(((_OG_WIDTH - w) // 2, y), line, fill=_TEXT_COLOR, font=title_font)
        y += line_height

    if subtitle:
        sub_lines = _wrap_text(subtitle, max_chars=50)
        y += 20
        for line in sub_lines[:2]:
            bbox = draw.textbbox((0, 0), line, font=subtitle_font)
            w = bbox[2] - bbox[0]
            draw.text(
                ((_OG_WIDTH - w) // 2, y),
                line, fill=_WATERMARK_COLOR, font=subtitle_font,
            )
            y += 38

    watermark = "doaide.com"
    bbox = draw.textbbox((0, 0), watermark, font=watermark_font)
    w = bbox[2] - bbox[0]
    draw.text(
        ((_OG_WIDTH - w) // 2, _OG_HEIGHT - 60),
        watermark, fill=_WATERMARK_COLOR, font=watermark_font,
    )

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@router.get(
    "/seo/og-image",
    summary="Dynamic Open Graph image",
    description=(
        "Renders a branded 1200x630 PNG for social sharing previews. "
        "Pass title and optional subtitle as query params."
    ),
    response_class=Response,
    responses={200: {"description": "The image.", "content": {"image/png": {}}}},
    dependencies=[Depends(_og_limit)],
)
def og_image(
    title: str = Query(..., min_length=1, max_length=200),
    subtitle: str | None = Query(None, max_length=300),
) -> Response:
    png = _render_og_image(title, subtitle)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )
