import asyncio
from io import BytesIO
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from app.auth import Payload, audit, cookie_token, lookup, require_csrf, require_scope
from app.db import SiteBranding, User, write
from app.errors import Problem

router = APIRouter(prefix="/site")
Admin = Annotated[User, Depends(require_scope("site.admin"))]
Slot = Literal["portrait", "background"]
IMAGE_LIMIT = 5 * 1024**2
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "application/octet-stream"}
IMAGE_FORMATS = ["JPEG", "PNG", "WEBP"]


class SiteTitle(Payload):
    title: Annotated[str, Field(min_length=1, max_length=64)]

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not value.strip() or not value.isprintable():
            raise ValueError("expected a printable title")
        return value.strip()


def optimize_image(data: bytes, slot: Slot) -> bytes:
    try:
        with Image.open(BytesIO(data), formats=IMAGE_FORMATS) as image:
            if (
                image.width * image.height > 16_000_000
                or image.width > 6000
                or image.height > 6000
                or getattr(image, "is_animated", False)
            ):
                raise Problem(422, "INVALID_SITE_IMAGE")
            prepared = ImageOps.exif_transpose(image)
            size = 768 if slot == "portrait" else 1920
            prepared.thumbnail((size, size))
            mode = (
                "RGBA" if "A" in prepared.getbands() or "transparency" in prepared.info else "RGB"
            )
            # Save pixels only, dropping EXIF and source metadata.
            result = BytesIO()
            prepared.convert(mode).save(result, format="WEBP", quality=88)
            return result.getvalue()
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        ValueError,
        SyntaxError,
        OverflowError,
    ):
        raise Problem(415, "INVALID_SITE_IMAGE") from None


def site_snapshot(db: Session) -> dict:
    title, revision, portrait, background = db.execute(
        select(
            SiteBranding.title,
            SiteBranding.revision,
            SiteBranding.portrait.is_not(None),
            SiteBranding.background.is_not(None),
        ).where(SiteBranding.id == 1)
    ).one()
    return {
        "title": title,
        "portrait": f"/api/v1/site/images/portrait?v={revision}" if portrait else None,
        "background": f"/api/v1/site/images/background?v={revision}" if background else None,
    }


def update_site(request: Request, key: Literal["title", "portrait", "background"], value) -> dict:
    state = request.app.state
    with write(state.engine) as db:
        actor, _ = lookup(db, state.settings, cookie_token(request))
        if actor.role != "admin":
            raise Problem(403, "FORBIDDEN")
        settings = db.get_one(SiteBranding, 1)
        setattr(settings, key, value)
        if key != "title":
            settings.revision += 1
        audit(db, "site.update", actor.id, key)
        db.flush()
        return site_snapshot(db)


@router.get("")
def get_site(request: Request) -> dict:
    with Session(request.app.state.engine) as db:
        return site_snapshot(db)


@router.get("/images/{slot}")
def get_image(slot: Slot, request: Request) -> Response:
    with Session(request.app.state.engine) as db:
        data = db.scalar(select(getattr(SiteBranding, slot)).where(SiteBranding.id == 1))
    if data is None:
        raise Problem(404, "SITE_IMAGE_MISSING")
    return Response(data, media_type="image/webp")


@router.patch("", dependencies=[Depends(require_csrf)])
def set_title(payload: SiteTitle, request: Request, user: Admin) -> dict:
    return update_site(request, "title", payload.title)


@router.put("/images/{slot}", dependencies=[Depends(require_csrf)])
async def upload_image(slot: Slot, request: Request, user: Admin) -> dict:
    if request.headers.get("content-type") not in IMAGE_TYPES:
        raise Problem(415, "INVALID_SITE_IMAGE")
    state = request.app.state
    if state.site_upload.locked():
        raise Problem(409, "SITE_UPLOAD_BUSY")
    async with state.site_upload:
        data = bytearray()
        try:
            async with asyncio.timeout(20):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > IMAGE_LIMIT:
                        raise Problem(413, "SITE_IMAGE_TOO_LARGE")
                    data.extend(chunk)
        except ClientDisconnect:
            raise Problem(400, "UPLOAD_INTERRUPTED") from None
        except TimeoutError:
            raise Problem(408, "UPLOAD_TIMEOUT") from None
        image = await run_in_threadpool(optimize_image, bytes(data), slot)
        return await run_in_threadpool(update_site, request, slot, image)


@router.delete("/images/{slot}", dependencies=[Depends(require_csrf)])
def remove_image(slot: Slot, request: Request, user: Admin) -> dict:
    return update_site(request, slot, None)
