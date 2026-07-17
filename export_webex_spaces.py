#!/usr/bin/env python3
"""Export Webex group spaces to text and CSV files."""

import argparse
import base64
import csv
import os
import sys
from typing import Optional

import requests

WEBEX_API_BASE = "https://webexapis.com/v1"
DEFAULT_ROOMS_URL = (
    f"{WEBEX_API_BASE}/rooms?type=group&sortBy=lastactivity&max=100"
)


def get_access_token() -> str:
    token = os.environ.get("WEBEX_ACCESS_TOKEN", "").strip()
    if not token:
        print(
            "Error: Set the WEBEX_ACCESS_TOKEN environment variable.\n"
            "Get a token at https://developer.webex.com/docs/getting-started",
            file=sys.stderr,
        )
        sys.exit(1)
    return token


def get_all_items(url: str, headers: dict) -> list:
    """Fetch all paginated items from a Webex API list endpoint."""
    items = []
    while url:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            print(
                f"Failed to retrieve items: {response.status_code} - {response.text}",
                file=sys.stderr,
            )
            sys.exit(1)

        data = response.json()
        items.extend(data.get("items", []))
        url = response.links.get("next", {}).get("url")

    return items


def room_to_deep_link(room_id: str) -> Optional[str]:
    try:
        decoded_uri = base64.b64decode(room_id).decode("utf-8")
        uuid = decoded_uri.split("/")[-1]
        return f"webexteams://im?space={uuid}"
    except (ValueError, UnicodeDecodeError):
        return None


def export_spaces(txt_path: str, csv_path: str, rooms_url: str, headers: dict) -> int:
    rooms = get_all_items(rooms_url, headers)
    count = 0

    with open(txt_path, "w", encoding="utf-8") as txt_file, open(
        csv_path, "w", encoding="utf-8", newline=""
    ) as csv_file:
        writer = csv.writer(csv_file, delimiter="\t")
        writer.writerow(["Space Name", "Space Link"])

        for room in rooms:
            room_name = room.get("title", "")
            room_id = room.get("id")
            deep_link = room_to_deep_link(room_id) if room_id else None

            if deep_link:
                txt_file.write(f"Space Name: {room_name}\n")
                txt_file.write(f"Space Link: {deep_link}\n\n")
                writer.writerow([room_name, deep_link])
                count += 1
            else:
                txt_file.write(
                    f"Space Name: {room_name} (No space link available)\n\n"
                )
                writer.writerow([room_name, ""])

    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export Webex group spaces to text and CSV files."
    )
    parser.add_argument(
        "--txt",
        default="WebexSpaces.txt",
        help="Output text file path (default: WebexSpaces.txt)",
    )
    parser.add_argument(
        "--csv",
        default="WebexSpaces.csv",
        help="Output CSV file path (default: WebexSpaces.csv)",
    )
    args = parser.parse_args()

    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    count = export_spaces(args.txt, args.csv, DEFAULT_ROOMS_URL, headers)
    print(f"Exported {count} spaces to {args.txt} and {args.csv}")


if __name__ == "__main__":
    main()
