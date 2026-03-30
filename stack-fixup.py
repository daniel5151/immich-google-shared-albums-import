#!/usr/bin/env python3
import argparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import sys
import time

def get_robust_session(api_key):
    """Creates a requests session that automatically retries failed connections."""
    session = requests.Session()

    # Configure retry logic: 5 retries, with a 0.25s backoff factor
    retry_kwargs = {
        "total": 5,
        "backoff_factor": 0.25, # 0.25s, 0.5s, 1s, 2s, 4s...
        "status_forcelist": [429, 500, 502, 503, 504],
    }

    methods = ["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"]

    try:
        # Try newer urllib3 syntax first
        retry_strategy = Retry(**retry_kwargs, allowed_methods=methods)
    except TypeError:
        # Fallback for older urllib3 versions
        retry_strategy = Retry(**retry_kwargs, method_whitelist=methods)

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    session.headers.update({
        "Accept": "application/json",
        "x-api-key": api_key
    })

    return session

def main():
    parser = argparse.ArgumentParser(description="Merge tags/albums to the largest file in an Immich stack, then delete the smaller duplicates.")
    parser.add_argument("--server", required=True, help="Immich API Server URL (e.g., http://localhost:2283/api)")
    parser.add_argument("--api-key", required=True, help="Immich API Key")
    parser.add_argument("--dry-run", action="store_true", help="Perform a dry run without making any changes")
    parser.add_argument("--date", help="Testing flag: Only process stacks matching this date (Format: YYYY-MM-DD)")

    args = parser.parse_args()

    base_url = args.server.rstrip("/")
    if not base_url.endswith("/api"):
        base_url += "/api"

    # Initialize our robust session
    session = get_robust_session(args.api_key)

    # ---------------------------------------------------------
    # Phase 1: Map out all Album Memberships
    # ---------------------------------------------------------
    print("1. Analyzing albums...")
    try:
        albums_resp = session.get(f"{base_url}/albums")
        if albums_resp.status_code != 200:
            print(f"Failed to fetch albums. Status {albums_resp.status_code}: {albums_resp.text}")
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Network error while fetching albums: {e}")
        sys.exit(1)

    albums = albums_resp.json()
    asset_to_albums = {}

    for album in albums:
        album_id = album['id']
        album_name = album.get('albumName', 'Unknown Album')

        try:
            detail_resp = session.get(f"{base_url}/albums/{album_id}")
            if detail_resp.status_code == 200:
                album_data = detail_resp.json()
                for asset in album_data.get('assets', []):
                    asset_id = asset['id']
                    if asset_id not in asset_to_albums:
                        asset_to_albums[asset_id] = set()
                    asset_to_albums[asset_id].add(album_id)
            else:
                print(f"  [Fatal Error] Could not fetch assets for album '{album_name}'. Status: {detail_resp.status_code}")
                sys.exit(1)
        except requests.exceptions.RequestException as e:
             print(f"  [Fatal Error] Network error while fetching album '{album_name}': {e}")
             sys.exit(1)

    print(f"   Done. Found {len(albums)} albums.\n")

    # ---------------------------------------------------------
    # Phase 2: Fetch and Process Stacks
    # ---------------------------------------------------------
    print("2. Fetching stacks...")
    try:
        stacks_resp = session.get(f"{base_url}/stacks")
        if stacks_resp.status_code != 200:
            print(f"Failed to fetch stacks. Status {stacks_resp.status_code}: {stacks_resp.text}")
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"Network error while fetching stacks: {e}")
        sys.exit(1)

    stacks_list = stacks_resp.json()
    print(f"   Found {len(stacks_list)} stacks to evaluate.\n")

    def get_file_size(asset):
        exif = asset.get('exifInfo')
        if exif and isinstance(exif, dict) and exif.get('fileSizeInByte') is not None:
            return int(exif['fileSizeInByte'])
        return 0

    processed_count = 0
    skipped_by_date = 0

    print("3. Consolidating metadata and cleaning up stacks...")
    for stack_info in stacks_list:
        stack_id = stack_info['id']

        try:
            stack_detail_resp = session.get(f"{base_url}/stacks/{stack_id}")
            if stack_detail_resp.status_code != 200:
                print(f"  [Fatal Error] Failed to fetch details for stack {stack_id}. Status: {stack_detail_resp.status_code}")
                sys.exit(1)
        except requests.exceptions.RequestException as e:
            print(f"  [Fatal Error] Unrecoverable network error fetching stack {stack_id}: {e}")
            sys.exit(1)

        stack_data = stack_detail_resp.json()
        stack_assets = stack_data.get('assets', [])

        if len(stack_assets) <= 1:
            continue

        # Optional Date Filter check
        if args.date:
            date_match = False
            for asset in stack_assets:
                local_dt = asset.get('localDateTime', '')
                file_dt = asset.get('fileCreatedAt', '')

                if args.date in local_dt or args.date in file_dt:
                    date_match = True
                    break

            if not date_match:
                skipped_by_date += 1
                continue

        # Sort by file size descending so [0] is the largest
        stack_assets.sort(key=get_file_size, reverse=True)
        largest_asset = stack_assets[0]
        largest_id = largest_asset['id']

        all_tags = set()
        all_albums = set()
        child_ids = []

        for asset in stack_assets:
            if asset['id'] != largest_id:
                child_ids.append(asset['id'])

            for tag in asset.get('tags', []):
                all_tags.add(tag['id'])
            if asset['id'] in asset_to_albums:
                all_albums.update(asset_to_albums[asset['id']])

        largest_current_tags = set(t['id'] for t in largest_asset.get('tags', []))
        largest_current_albums = asset_to_albums.get(largest_id, set())

        tags_to_add = all_tags - largest_current_tags
        albums_to_add = all_albums - largest_current_albums

        if not tags_to_add and not albums_to_add and not child_ids:
            continue

        processed_count += 1
        print(f"\nStack {stack_id}:")
        print(f"  -> Target Photo ID:  {largest_id} ({get_file_size(largest_asset) / 1024 / 1024:.2f} MB)")
        print(f"  -> Source Photo IDs: {', '.join(child_ids)}")
        print(f"     Missing {len(tags_to_add)} tags, {len(albums_to_add)} albums. Will delete {len(child_ids)} duplicates.")

        if args.dry_run:
            if tags_to_add:
                print(f"  [DRY RUN] Would assign {len(tags_to_add)} tags.")
            if albums_to_add:
                print(f"  [DRY RUN] Would add to {len(albums_to_add)} albums.")
            if child_ids:
                print(f"  [DRY RUN] Would permanently delete {len(child_ids)} smaller stacked assets.")
            continue

        # 3.1 Apply missing Tags
        if tags_to_add:
            print(f"  -> Applying tags...")
            try:
                tag_resp = session.put(f"{base_url}/tags/assets", json={
                    "assetIds": [largest_id],
                    "tagIds": list(tags_to_add)
                })
                if tag_resp.status_code != 200:
                    print(f"     [Fatal Error] Failed to apply tags: {tag_resp.text}")
                    sys.exit(1)
            except requests.exceptions.RequestException as e:
                print(f"     [Fatal Error] Network error applying tags: {e}")
                sys.exit(1)

        # 3.2 Apply missing Albums
        if albums_to_add:
            print(f"  -> Applying album memberships...")
            for album_id in albums_to_add:
                try:
                    album_resp = session.put(f"{base_url}/albums/{album_id}/assets", json={
                        "ids": [largest_id]
                    })
                    if album_resp.status_code not in (200, 201):
                        print(f"     [Fatal Error] Failed to add to album {album_id}: {album_resp.text}")
                        sys.exit(1)
                except requests.exceptions.RequestException as e:
                    print(f"     [Fatal Error] Network error adding to album {album_id}: {e}")
                    sys.exit(1)

        # 3.3 Delete the smaller duplicate assets
        if child_ids:
            print(f"  -> Deleting {len(child_ids)} smaller duplicate assets...")
            try:
                del_resp = session.delete(f"{base_url}/assets", json={
                    "ids": child_ids
                })
                if del_resp.status_code >= 400:
                    print(f"     [Fatal Error] Failed to delete child assets: {del_resp.text}")
                    sys.exit(1)
            except requests.exceptions.RequestException as e:
                print(f"     [Fatal Error] Network error deleting assets: {e}")
                sys.exit(1)

    print(f"\nFinished! Updated (and cleaned up) {processed_count} stacks.")
    if args.date:
        print(f"Skipped {skipped_by_date} stacks that did not match the date '{args.date}'.")

if __name__ == "__main__":
    main()
