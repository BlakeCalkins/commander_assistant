import requests
from bs4 import BeautifulSoup
import time
import json
from collections import defaultdict

SCRYFALL_SEARCH_URL = "https://api.scryfall.com/cards/search"
RATE_LIMIT_DELAY = 0.3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def get_random_cards(count=200):
    """Fetch random cards from Scryfall."""
    print(f"Fetching {count} random cards from Scryfall...\n")

    cards = []
    for i in range(count):
        if i % 50 == 0:
            print(f"  Fetched {i}/{count}...")

        try:
            response = requests.get(
                "https://api.scryfall.com/cards/random", headers=HEADERS, timeout=10
            )

            if response.status_code == 200:
                card = response.json()
                cards.append(
                    {
                        "name": card.get("name"),
                        "set": card.get("set"),
                        "collector_number": card.get("collector_number"),
                    }
                )

            time.sleep(0.05)
        except Exception as e:
            pass

    print(f"  ✓ Fetched {len(cards)} cards\n")
    return cards


def extract_card_tags_from_meta(html):
    """
    Extract card tags from the meta description.
    Format: "Card Tags:\n• tag1\n• tag2\n• and X more"
    """
    soup = BeautifulSoup(html, "html.parser")
    meta_desc = soup.find("meta", {"name": "description"})

    if not meta_desc:
        return []

    desc_content = meta_desc.get("content", "")

    if "Card Tags:" not in desc_content:
        return []

    # Extract the Card Tags section
    card_tags_section = desc_content.split("Card Tags:")[1]

    # Parse bullet points
    tags = []
    for line in card_tags_section.split("\n"):
        line = line.strip()
        if line.startswith("•"):
            tag = line.replace("•", "").strip()
            # Skip "and X more" entries
            if tag and not tag.startswith("and"):
                tags.append(tag)

    return tags


def scrape_tags_from_cards(cards):
    """
    Scrape tags from tagger.scryfall.com for each card.
    Aggregate all unique tags.
    """
    print(f"Scraping tags from tagger.scryfall.com for {len(cards)} cards...\n")

    tag_counts = defaultdict(int)
    successful = 0
    failed = 0

    for i, card in enumerate(cards):
        card_name = card.get("name", "Unknown")
        set_code = card.get("set")
        collector_num = card.get("collector_number")

        print(f"[{i + 1}/{len(cards)}] {card_name:<40}", end=" ... ")

        if not set_code or not collector_num:
            print("❌ missing set/number")
            failed += 1
            continue

        try:
            tagger_url = f"https://tagger.scryfall.com/card/{set_code}/{collector_num}"
            response = requests.get(tagger_url, headers=HEADERS, timeout=10)

            if response.status_code == 200:
                tags = extract_card_tags_from_meta(response.text)

                if tags:
                    for tag in tags:
                        tag_counts[tag] += 1
                    print(f"✓ {len(tags)} tags")
                    successful += 1
                else:
                    print(f"⚠ no card tags")
                    failed += 1
            else:
                print(f"❌ HTTP {response.status_code}")
                failed += 1

        except Exception as e:
            print(f"❌ error: {str(e)[:30]}")
            failed += 1

        time.sleep(RATE_LIMIT_DELAY)

    print(f"\n{'=' * 70}")
    print(f"Results: {successful} cards scraped, {failed} failed")
    print(f"Unique tags found: {len(tag_counts)}")
    print(f"{'=' * 70}\n")

    return tag_counts


def filter_gameplay_tags(tag_counts):
    """
    Filter to keep only gameplay-relevant tags.
    Remove art/aesthetic tags.
    """
    print("Filtering tags...\n")

    # These patterns indicate art/non-gameplay tags
    exclude_patterns = [
        "art",
        "artist",
        "illustration",
        "pose",
        "background",
        "landscape",
        "sky",
        "color",
        "beautiful",
        "aesthetic",
        "female",
        "male",
        "woman",
        "man",
        "hair",
        "clothing",
        "face",
        "person",
        "people",
        "signature",
        "promo",
        "topless",
        "nude",
        "body",
        "figure",
        "torso",
        "hand",
        "arm",
        "leg",
        "face",
        "eye",
        "expression",
        "smile",
        "stance",
        "posture",
        "weapon",
        "armor",
        "dress",
        "cloak",
        "robe",
    ]

    filtered = {}
    excluded = 0

    for tag, count in tag_counts.items():
        tag_lower = tag.lower()

        # Check if matches exclude patterns
        if any(pattern in tag_lower for pattern in exclude_patterns):
            excluded += 1
            continue

        # Exclude very short tags (likely metadata)
        if len(tag) < 3:
            excluded += 1
            continue

        # Exclude very long tags
        if len(tag) > 50:
            excluded += 1
            continue

        filtered[tag] = count

    print(f"Excluded {excluded} art/non-gameplay tags")
    print(f"Kept {len(filtered)} gameplay-relevant tags\n")

    return filtered


def load_existing_tags(filename="scryfall_gameplay_tags.json"):
    """Load existing tags from JSON if it exists."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Convert back to dict format
            existing_tags = {}
            if "tags_with_frequency" in data:
                for item in data["tags_with_frequency"]:
                    existing_tags[item["tag"]] = item["frequency"]
            return existing_tags
    except FileNotFoundError:
        return {}


def save_tags(tags_dict, filename="scryfall_gameplay_tags.json", merge_existing=True):
    """Save discovered tags to JSON, optionally merging with existing tags."""

    # Load and merge with existing tags
    if merge_existing:
        existing_tags = load_existing_tags(filename)
        print(f"Merging with {len(existing_tags)} existing tags...\n")
        for tag, count in existing_tags.items():
            tags_dict[tag] = tags_dict.get(tag, 0) + count

    # Sort by frequency
    sorted_tags = sorted(tags_dict.items(), key=lambda x: x[1], reverse=True)

    output = {
        "description": "Real gameplay-relevant tags from tagger.scryfall.com",
        "total_unique_tags": len(sorted_tags),
        "tags": [tag for tag, _ in sorted_tags],
        "tags_with_frequency": [
            {"tag": tag, "frequency": count} for tag, count in sorted_tags
        ],
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"✓ Saved to {filename}")
    print(f"  Total unique tags: {len(sorted_tags)}\n")
    return sorted_tags


# --- RUN ---
if __name__ == "__main__":
    try:
        print("=" * 70)
        print("DISCOVERING REAL GAMEPLAY TAGS FROM TAGGER.SCRYFALL.COM")
        print("=" * 70 + "\n")

        # Step 1: Get random cards
        cards = get_random_cards(count=1000)

        if not cards:
            print("Failed to fetch cards!")
            exit(1)

        # Step 2: Scrape tags from tagger
        tag_counts = scrape_tags_from_cards(cards)

        if not tag_counts:
            print("No tags found!")
            exit(1)

        # Step 3: Filter out art tags
        gameplay_tags = filter_gameplay_tags(tag_counts)

        if not gameplay_tags:
            print("No gameplay tags after filtering!")
            exit(1)

        # Step 4: Save results (merge with existing tags if any)
        sorted_tags = save_tags(gameplay_tags, merge_existing=True)

        # Step 5: Display results
        print("=" * 70)
        print(f"TOP 50 GAMEPLAY TAGS FOR AI AGENT\n")
        print(f"{'Tag':<45} {'Frequency':>10}")
        print("-" * 70)

        for tag, count in sorted_tags[:50]:
            print(f"{tag:<45} {count:>10}")

        print("=" * 70)
        print(f"\nTotal gameplay-relevant tags: {len(gameplay_tags)}")

    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        import traceback

        traceback.print_exc()
