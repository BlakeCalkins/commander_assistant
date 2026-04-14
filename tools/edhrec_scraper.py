import requests
import json
import re
from bs4 import BeautifulSoup


def commander_name_to_slug(name: str) -> str:
    """Convert a commander name to EDHREC URL slug format."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "-", name.strip())
    return name


def parse_cardview(card: dict) -> dict:
    """Extract relevant fields from a raw cardview entry."""
    result = {
        "name": card.get("name"),
        "num_decks": card.get("num_decks"),
    }
    if (synergy := card.get("synergy")) is not None:
        result["synergy"] = synergy
    return result


def pull_commander_card_recommendations(commander_name: str) -> dict:
    """
    Given a commander name, fetches its EDHREC page and returns the
    'High Synergy Cards' and 'Top Cards' sections as structured data.
    """
    slug = commander_name_to_slug(commander_name)
    url = f"https://edhrec.com/commanders/{slug}"

    html = requests.get(url).text
    soup = BeautifulSoup(html, "html.parser")

    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if not next_data_tag:
        raise ValueError(
            f"Could not find EDHREC data for '{commander_name}'. Check that the name is spelled correctly."
        )

    data = json.loads(next_data_tag.string)

    try:
        cardlists = data["props"]["pageProps"]["data"]["container"]["json_dict"][
            "cardlists"
        ]
    except KeyError:
        raise ValueError(f"Unexpected page structure for '{commander_name}'.")

    result = {
        "commander": commander_name,
        "url": url,
        "high_synergy_cards": [],
        "top_cards": [],
    }

    section_map = {
        "high synergy cards": "high_synergy_cards",
        "top cards": "top_cards",
    }

    for cardlist in cardlists:
        header = (cardlist.get("header", "") or cardlist.get("tag", "")).lower()
        for label, key in section_map.items():
            if label in header:
                result[key] = [parse_cardview(c) for c in cardlist.get("cardviews", [])]
                break

    return result
