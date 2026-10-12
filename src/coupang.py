"""쿠팡 파트너스 API로 상품 후보를 검색한다."""

import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import requests

DOMAIN = "https://api-gateway.coupang.com"
SEARCH_PATH = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search"


def _authorization(method, path, query):
    access_key = os.environ["COUPANG_ACCESS_KEY"]
    secret_key = os.environ["COUPANG_SECRET_KEY"]
    signed_date = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    message = signed_date + method + path + query
    signature = hmac.new(secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
    return (f"CEA algorithm=HmacSHA256, access-key={access_key}, "
            f"signed-date={signed_date}, signature={signature}")


def search_products(keyword, limit=3):
    """[{name, price, url, image}, ...] 최대 limit개."""
    query = urlencode({"keyword": keyword, "limit": limit})
    resp = requests.get(
        f"{DOMAIN}{SEARCH_PATH}?{query}",
        headers={"Authorization": _authorization("GET", SEARCH_PATH, query),
                 "Content-Type": "application/json;charset=UTF-8"},
        timeout=20,
    )
    resp.raise_for_status()
    body = resp.json()
    if str(body.get("rCode")) != "0":
        raise RuntimeError(f"쿠팡 API 오류: {body.get('rMessage')}")
    products = body.get("data", {}).get("productData", [])[:limit]
    return [
        {"name": p["productName"], "price": p.get("productPrice"),
         "url": p["productUrl"], "image": p.get("productImage")}
        for p in products
    ]
