from io import BytesIO

from conftest import API, ORIGIN, sign_in
from PIL import Image

SITE = API + "/site"
PORTRAIT = SITE + "/images/portrait"


def test_admin_can_update_public_branding(panel):
    assert panel.client.get(SITE).json() == {
        "title": "Minecraft Panel",
        "portrait": None,
        "background": None,
    }
    assert panel.client.patch(SITE, json={"title": "Fixture"}).status_code in (401, 403)
    operator, _ = sign_in(panel, "operator")
    assert panel.client.patch(SITE, headers=operator, json={"title": "Fixture"}).status_code == 403
    admin, _ = sign_in(panel)
    assert (
        panel.client.patch(SITE, headers={"Origin": ORIGIN}, json={"title": "Fixture"}).status_code
        == 403
    )
    assert panel.client.patch(SITE, headers=admin, json={"title": "   "}).status_code == 422
    assert (
        panel.client.patch(SITE, headers=admin, json={"title": " 测试服 "}).json()["title"]
        == "测试服"
    )

    image_headers = admin | {"Content-Type": "image/png"}
    assert panel.client.put(PORTRAIT, headers=image_headers, content=b"<svg/>").status_code == 415
    data = BytesIO()
    Image.new("RGB", (900, 500), "#174e3d").save(data, "PNG")
    uploaded = panel.client.put(PORTRAIT, headers=image_headers, content=data.getvalue())
    assert uploaded.status_code == 200
    path = uploaded.json()["portrait"]
    response = panel.client.get(path)
    assert response.headers["content-type"] == "image/webp"
    with Image.open(BytesIO(response.content)) as image:
        assert image.width == 768 and image.height < 500
    assert panel.client.get(SITE).json()["title"] == "测试服"
    assert panel.client.delete(PORTRAIT, headers=admin).json()["portrait"] is None
    assert panel.client.get(path).status_code == 404
