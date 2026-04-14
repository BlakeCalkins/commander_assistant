import requests


def search_scryfall_json(query: str, limit: int = 20) -> list[dict]:
    """
    Returns card data sorted by EDHREC ranking (best first).
    Handles pagination to get all results.

    Args:
        query: Scryfall search query
        limit: Max cards to return (default 20)

    Returns:
        List of cards sorted by EDHREC rank
    """
    url = "https://api.scryfall.com/cards/search"
    all_cards = []
    has_more = True
    page = 1

    # Fetch all pages
    while has_more:
        response = requests.get(url, params={"q": query, "page": page})
        response.raise_for_status()

        data = response.json()
        cards = data.get("data", [])

        all_cards.extend(
            [
                {
                    "name": card.get("name"),
                    "mana_cost": card.get("mana_cost"),
                    "type": card.get("type_line"),
                    "oracle_text": card.get("oracle_text", ""),
                    "usd": card.get("prices", {}).get("usd"),
                    "set": card.get("set").upper(),
                    "edhrec_rank": card.get("edhrec_rank"),
                }
                for card in cards
            ]
        )

        has_more = data.get("has_more", False)
        page += 1

    # Sort: cards with EDHREC rank first (sorted by rank), then unranked
    all_cards.sort(
        key=lambda x: (x["edhrec_rank"] is None, x["edhrec_rank"] or float("inf"))
    )

    return all_cards[:limit]


# print(search_scryfall_json("otag:sacrifice-outlet-creature id:rb"))
