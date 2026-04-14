import json
import re


def normalize_tags(
    input_file="scryfall_gameplay_tags.json",
    output_file="scryfall_tags.json",
    min_frequency=2,
    max_tags=500,
):
    """
    Clean up tags by:
    1. Converting spaces to hyphens (e.g., "removes flying" -> "removes-flying")
    2. Filtering low-frequency tags
    3. Keeping only top N tags
    4. Outputting in minimal format (just tag names)
    """

    print(f"Loading {input_file}...\n")

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Error: {input_file} not found")
        return

    # Extract tags with frequency
    tags_with_freq = data.get("tags_with_frequency", [])
    print(f"Starting tags: {len(tags_with_freq)}\n")

    # Step 1: Normalize tag names (spaces -> hyphens)
    print("Step 1: Normalizing tag names (spaces -> hyphens)...\n")
    normalized_tags = []
    space_count = 0

    for tag_data in tags_with_freq:
        tag = tag_data["tag"]
        original_tag = tag

        # Replace spaces with hyphens
        if " " in tag:
            tag = tag.replace(" ", "-")
            space_count += 1
            print(f"  '{original_tag}' -> '{tag}'")

        normalized_tags.append({"tag": tag, "frequency": tag_data["frequency"]})

    print(f"\nNormalized {space_count} tags with spaces\n")

    # Step 2: Deduplicate (in case normalizing created duplicates)
    print("Step 2: Deduplicating tags...\n")

    tag_dict = {}
    for tag_data in normalized_tags:
        tag = tag_data["tag"]
        freq = tag_data["frequency"]

        if tag in tag_dict:
            # Combine frequencies if duplicate
            tag_dict[tag] += freq
        else:
            tag_dict[tag] = freq

    # Convert back to list and sort by frequency
    deduplicated = [{"tag": tag, "frequency": freq} for tag, freq in tag_dict.items()]
    deduplicated.sort(key=lambda x: x["frequency"], reverse=True)

    print(f"After deduplication: {len(deduplicated)} unique tags\n")

    # Step 3: Filter by minimum frequency
    print(f"Step 3: Filtering tags with frequency < {min_frequency}...\n")
    filtered = [t for t in deduplicated if t["frequency"] >= min_frequency]
    print(f"After filtering: {len(filtered)} tags\n")

    # Step 4: Keep only top N tags
    print(f"Step 4: Keeping only top {max_tags} tags...\n")
    filtered = filtered[:max_tags]
    print(f"Final count: {len(filtered)} tags\n")

    # Step 5: Create minimal output (just tag names)
    optimized_list = [t["tag"] for t in filtered]

    output_data = {
        "tags": optimized_list,
        "total": len(optimized_list),
        "description": "Gameplay-relevant tags from tagger.scryfall.com (cleaned and optimized)",
    }

    # Save
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2)

    output_size = len(json.dumps(output_data, indent=2))

    print("=" * 70)
    print(f"✓ Saved to {output_file}\n")
    print(f"File size: {output_size:,} bytes")
    print(f"Est. tokens: ~{output_size // 4:,}")
    print(f"Total tags: {len(optimized_list)}")
    print("=" * 70)

    # Show sample of cleaned tags
    print(f"\nSample of cleaned tags (first 30):\n")
    for i, tag in enumerate(optimized_list[:30], 1):
        freq = next((t["frequency"] for t in filtered if t["tag"] == tag), 0)
        print(f"  {i:2}. {tag:<40} (freq: {freq})")

    print(f"\n✓ All tags are now hyphenated and optimized!")


if __name__ == "__main__":
    normalize_tags(
        input_file="scryfall_gameplay_tags.json",
        output_file="tools/scryfall_tags.json",
        min_frequency=12,  # Remove low-frequency tags
        max_tags=700,  # Keep top max_tags tags
    )
