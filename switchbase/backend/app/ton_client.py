import httpx

TONAPI_BASE_URL = "https://tonapi.io/v2"

KNOWN_GIFT_COLLECTIONS: dict[str, str] = {
    "EQD_PLUSH_PEPE_COLLECTION_PLACEHOLDER": "Plush Pepe",
    "EQD_DESK_CALENDAR_COLLECTION_PLACEHOLDER": "Desk Calendar",
    "EQD_JELLY_BUNNY_COLLECTION_PLACEHOLDER": "Jelly Bunny",
}


class TonApiError(Exception):
    pass


async def fetch_incoming_transactions(wallet_address: str, limit: int = 100) -> list[dict]:
    url = f"{TONAPI_BASE_URL}/blockchain/accounts/{wallet_address}/transactions"
    params = {"limit": limit}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TonApiError(f"Не удалось получить транзакции из TON API: {exc}") from exc

    payload = response.json()
    transactions = payload.get("transactions", [])

    incoming: list[dict] = []
    for tx in transactions:
        in_msg = tx.get("in_msg")
        if not in_msg or not in_msg.get("value"):
            continue

        comment = ""
        decoded_body = in_msg.get("decoded_body")
        if decoded_body and isinstance(decoded_body, dict):
            comment = decoded_body.get("text", "") or ""

        incoming.append(
            {
                "tx_hash": tx.get("hash"),
                "amount_nano": int(in_msg.get("value", 0)),
                "comment": comment.strip(),
                "utime": tx.get("utime"),
            }
        )

    return incoming


async def fetch_wallet_nfts(wallet_address: str) -> list[dict]:
    url = f"{TONAPI_BASE_URL}/accounts/{wallet_address}/nfts"
    params = {"limit": 200, "offset": 0, "indirect_ownership": "false"}

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TonApiError(f"Не удалось получить NFT из TON API: {exc}") from exc

    payload = response.json()
    items = payload.get("nft_items", [])

    gifts: list[dict] = []
    for item in items:
        collection = item.get("collection", {})
        collection_address = collection.get("address")
        if collection_address not in KNOWN_GIFT_COLLECTIONS:
            continue

        metadata = item.get("metadata", {})
        gifts.append(
            {
                "external_gift_id": item.get("address"),
                "title": metadata.get("name", KNOWN_GIFT_COLLECTIONS[collection_address]),
                "preview_url": metadata.get("image", ""),
                "rarity_number": str(item.get("index", "")),
                "attributes": metadata.get("attributes", []),
            }
        )

    return gifts
