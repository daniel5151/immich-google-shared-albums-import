#!/usr/bin/env python3
import argparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import sys

def get_robust_session(api_key):
    """Creates a requests session that automatically retries failed connections."""
    session = requests.Session()

    # Configure retry logic: 5 retries, with a 0.25s backoff factor
    retry_kwargs = {
        "total": 5,
        "backoff_factor": 0.25,
        "status_forcelist": [429, 500, 502, 503, 504],
    }

    methods = ["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE", "POST"]

    try:
        retry_strategy = Retry(**retry_kwargs, allowed_methods=methods)
    except TypeError:
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
    parser = argparse.ArgumentParser(description="Audit albums for photos missing a 'SharedBy/' tag.")
    parser.add_argument("--server", required=True, help="Immich API Server URL (e.g., http://localhost:2283/api)")
    parser.add_argument("--api-key", required=True, help="Immich API Key")

    args = parser.parse_args()

    base_url = args.server.rstrip("/")
    if not base_url.endswith("/api"):
        base_url += "/api"

    session = get_robust_session(args.api_key)

    # ---------------------------------------------------------
    # Phase 1: Map all assets that currently have a SharedBy tag
    # ---------------------------------------------------------
    print("1. Identifying photos with 'SharedBy/' tags...")
    try:
        tags_resp = session.get(f"{base_url}/tags")
        if tags_resp.status_code != 200:
            print(f"[Fatal Error] Failed to fetch tags. Status {tags_resp.status_code}: {tags_resp.text}")
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"[Fatal Error] Network error while fetching tags: {e}")
        sys.exit(1)

    tags = tags_resp.json()

    # Find all tags that start with the target prefix
    prefix = "SharedBy/"
    shared_tags = [t for t in tags if t.get("value", t.get("name", "")).startswith(prefix)]

    tagged_asset_ids = set()

    if not shared_tags:
        print(f"   [Warning] No tags starting with '{prefix}' exist in the library. All album photos will be flagged as missing.")
    else:
        # For each SharedBy tag, fetch the assets associated with it
        for t in shared_tags:
            page = 1
            size = 1000
            while True:
                try:
                    search_resp = session.post(f"{base_url}/search/metadata", json={
                        "tagIds": [t['id']],
                        "withStacked": True,
                        "page": page,
                        "size": size
                    })
                    if search_resp.status_code != 200:
                        print(f"[Fatal Error] Failed to search assets for tag {t['name']}. Status {search_resp.status_code}")
                        sys.exit(1)
                except requests.exceptions.RequestException as e:
                    print(f"[Fatal Error] Network error searching assets: {e}")
                    sys.exit(1)

                items = search_resp.json().get("assets", {}).get("items", [])
                for item in items:
                    tagged_asset_ids.add(item['id'])

                if len(items) < size:
                    break
                page += 1

    print(f"   Done. Found {len(tagged_asset_ids)} total photos that have a SharedBy tag.\n")

    # ---------------------------------------------------------
    # Phase 2: Audit Albums
    # ---------------------------------------------------------
    print("2. Scanning albums for missing tags...")
    try:
        albums_resp = session.get(f"{base_url}/albums")
        if albums_resp.status_code != 200:
            print(f"[Fatal Error] Failed to fetch albums. Status {albums_resp.status_code}: {albums_resp.text}")
            sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"[Fatal Error] Network error while fetching albums: {e}")
        sys.exit(1)

    albums = albums_resp.json()
    print(f"   Found {len(albums)} albums to audit.\n")

    total_missing_flags = 0

    for album in albums:
        album_id = album['id']
        album_name = album.get('albumName', 'Unknown Album')

        try:
            detail_resp = session.get(f"{base_url}/albums/{album_id}")
            if detail_resp.status_code != 200:
                print(f"  [Fatal Error] Could not fetch assets for album '{album_name}'. Status: {detail_resp.status_code}")
                sys.exit(1)
        except requests.exceptions.RequestException as e:
             print(f"  [Fatal Error] Network error while fetching album '{album_name}': {e}")
             sys.exit(1)

        album_data = detail_resp.json()
        assets = album_data.get('assets', [])

        missing_in_album = []
        for asset in assets:
            if asset['id'] not in tagged_asset_ids:
                missing_in_album.append(asset)

        if missing_in_album:
            print(f"Album: '{album_name}'")
            for asset in missing_in_album:
                file_name = asset.get('originalFileName', 'Unknown_Filename')
                print(f"  - Missing Tag: {file_name}  (Photo ID: {asset['id']})")
            print("")
            total_missing_flags += len(missing_in_album)

    print(f"Audit Complete! Flagged {total_missing_flags} photos inside albums that are missing a '{prefix}' tag.")

if __name__ == "__main__":
    main()
