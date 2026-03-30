#!/usr/bin/env python3
import argparse
import requests
import sys

def main():
    parser = argparse.ArgumentParser(description="Copy Immich tags from 'Uploaded by: {name}' to 'SharedBy/{name}'")
    parser.add_argument("--server", required=True, help="Immich API Server URL (e.g., http://localhost:2283/api)")
    parser.add_argument("--api-key", required=True, help="Immich API Key")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without making any changes")

    args = parser.parse_args()

    base_url = args.server.rstrip("/")
    if not base_url.endswith("/api"):
        base_url += "/api"

    headers = {
        "Accept": "application/json",
        "x-api-key": args.api_key
    }

    print("Fetching existing tags...")
    resp = requests.get(f"{base_url}/tags", headers=headers)
    if resp.status_code != 200:
        print(f"Failed to fetch tags. Status: {resp.status_code}\n{resp.text}")
        sys.exit(1)

    tags = resp.json()

    prefix = "Uploaded by: "
    tags_to_migrate = [t for t in tags if t.get("value", t.get("name", "")).startswith(prefix)]

    if not tags_to_migrate:
        print(f"No tags found matching the format '{prefix}{{name}}'")
        return

    def find_tag(value_to_find, tag_list):
        target = value_to_find.strip().lower()
        for t in tag_list:
            if t.get("value", t.get("name", "")).strip().lower() == target:
                return t
        return None

    for old_tag in tags_to_migrate:
        old_value = old_tag.get("value", old_tag.get("name", ""))
        user_name = old_value[len(prefix):]
        new_path = f"SharedBy/{user_name}"

        print(f"\nProcessing tag: '{old_value}' -> Copying to '{new_path}'")

        existing_new_tag = find_tag(new_path, tags)

        if args.dry_run:
            if existing_new_tag:
                print(f"  [DRY RUN] Tag path '{existing_new_tag.get('value')}' already exists. Would reuse it.")
            else:
                print(f"  [DRY RUN] Would create new tag path '{new_path}'")
            print(f"  [DRY RUN] Would fetch all assets tagged with '{old_value}'")
            print(f"  [DRY RUN] Would tag the matched assets with the new tag")
            print(f"  [DRY RUN] Old tag '{old_value}' will NOT be deleted.")
            continue

        # 1. Create or Find the new tag
        new_tag_id = None
        if existing_new_tag:
            print(f"  New tag path '{existing_new_tag.get('value', new_path)}' already exists. Reusing it.")
            new_tag_id = existing_new_tag["id"]
        else:
            print(f"  Creating new tag path '{new_path}'...")
            clean_new_path = new_path.strip()

            create_resp = requests.put(f"{base_url}/tags", headers=headers, json={"tags": [clean_new_path]})

            if create_resp.status_code == 200:
                new_tags_data = create_resp.json()
                if not new_tags_data:
                    print(f"  [Error] API returned empty list when creating tag.")
                    continue

                new_tag_data = None
                for t in new_tags_data:
                    if t.get("value", "").lower() == clean_new_path.lower():
                        new_tag_data = t
                        break

                if not new_tag_data:
                    new_tag_data = new_tags_data[-1]

                new_tag_id = new_tag_data["id"]
                tags.extend(new_tags_data)
            else:
                print(f"  [Error] Failed to create tag path: {create_resp.text}")
                continue

        # 2. Fetch all assets associated with the old tag
        asset_ids = []
        page = 1
        size = 1000

        print(f"  Fetching assets for '{old_value}'...")
        while True:
            search_resp = requests.post(f"{base_url}/search/metadata", headers=headers, json={
                "tagIds": [old_tag["id"]],
                "page": page,
                "size": size
            })
            if search_resp.status_code != 200:
                print(f"  [Error] Failed to fetch assets: {search_resp.text}")
                break

            search_data = search_resp.json()
            items = search_data.get("assets", {}).get("items", [])
            asset_ids.extend([item["id"] for item in items])

            if len(items) < size:
                break
            page += 1

        # 3. Add the new tag to the assets
        if not asset_ids:
            print("  No assets found for old tag. Skipping asset tagging phase.")
        else:
            print(f"  Tagging {len(asset_ids)} assets with new tag...")
            tag_resp = requests.put(f"{base_url}/tags/assets", headers=headers, json={
                "assetIds": asset_ids,
                "tagIds": [new_tag_id]
            })
            if tag_resp.status_code != 200:
                print(f"  [Error] Failed to bulk-tag assets: {tag_resp.text}")
                continue

        print(f"  Copy successful for this tag. Old tag '{old_value}' remains intact.")

if __name__ == "__main__":
    main()
