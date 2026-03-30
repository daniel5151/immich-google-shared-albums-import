#!/usr/bin/env python3
import argparse
import requests
import sys

def main():
    parser = argparse.ArgumentParser(description="Delete Immich tags starting with 'Uploaded by:'")
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
    # We check 'value' first for hierarchical tags, falling back to 'name'
    tags_to_delete = [t for t in tags if t.get("value", t.get("name", "")).startswith(prefix)]

    if not tags_to_delete:
        print(f"No tags found starting with '{prefix}'")
        return

    print(f"Found {len(tags_to_delete)} tags to delete.\n")

    for tag in tags_to_delete:
        tag_value = tag.get("value", tag.get("name", ""))
        tag_id = tag["id"]

        if args.dry_run:
            print(f"[DRY RUN] Would delete tag: '{tag_value}'")
            continue

        print(f"Deleting tag: '{tag_value}'...")
        del_resp = requests.delete(f"{base_url}/tags/{tag_id}", headers=headers)

        # 204 No Content is Immich's standard success response for deletions
        if del_resp.status_code == 204 or del_resp.status_code == 200:
            print(f"  Successfully deleted.")
        else:
            print(f"  [Error] Failed to delete tag: Status {del_resp.status_code} - {del_resp.text}")

if __name__ == "__main__":
    main()
