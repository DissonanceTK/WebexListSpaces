#!/usr/bin/env python3
"""Export Webex group spaces to text and CSV files."""

import argparse
import base64
import contextlib
import csv
import json
import os
import sys
import time
from typing import Iterator, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

WEBEX_API_BASE = "https://webexapis.com/v1"
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_CONSECUTIVE_EMPTY_PAGES = 25
DEFAULT_MAX_PAGES = 1000
VALID_GROUP_FIELDS = ("team", "creator")
CREATOR_CREATED_BY_ME = "Created by me"
CREATOR_CREATED_BY_OTHERS = "Created by others"
TEAM_NONE_LABEL = "No team"
SPACE_COLUMNS = ("Space Name", "Space Link", "Space Web Link")
EURL_COLUMN = "Eurl"
EURL_BASE = "https://eurl.io/#"


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


def parse_group_by(value: Optional[str]) -> list[str]:
    if not value:
        return []

    fields = [part.strip().lower() for part in value.split(",") if part.strip()]
    invalid = [field for field in fields if field not in VALID_GROUP_FIELDS]
    if invalid:
        allowed = ", ".join(VALID_GROUP_FIELDS)
        invalid_values = ", ".join(invalid)
        print(
            f"Error: Unknown --group-by value(s): {invalid_values}. "
            f"Allowed values: {allowed}.",
            file=sys.stderr,
        )
        sys.exit(1)

    deduped: list[str] = []
    seen: set[str] = set()
    for field in fields:
        if field not in seen:
            seen.add(field)
            deduped.append(field)
    return deduped


def build_rooms_url(sort_by: str, page_size: int) -> str:
    return (
        f"{WEBEX_API_BASE}/rooms"
        f"?type=group&sortBy={sort_by}&max={page_size}"
    )


def fix_next_url(url: str) -> str:
    """Remove max=null from Webex next-page URLs (known API quirk)."""
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not (key == "max" and value == "null")
    ]
    return urlunparse(parsed._replace(query=urlencode(query)))


def get_next_url(response: requests.Response) -> Optional[str]:
    next_link = response.links.get("next")
    if not next_link:
        return None
    url = next_link.get("url")
    if not url:
        return None
    return fix_next_url(url)


def request_page(
    session: requests.Session, url: str, headers: dict
) -> requests.Response:
    while True:
        response = session.get(url, headers=headers, timeout=30)
        if response.status_code == 429 and response.headers.get("Retry-After"):
            retry_after = int(response.headers["Retry-After"])
            print(
                f"Rate limited; waiting {retry_after}s...",
                file=sys.stderr,
            )
            time.sleep(retry_after)
            continue
        if response.status_code != 200:
            print(
                f"Failed to retrieve items: {response.status_code} - {response.text}",
                file=sys.stderr,
            )
            sys.exit(1)
        return response


def iter_paginated_items(
    session: requests.Session,
    start_url: str,
    headers: dict,
    *,
    max_pages: int,
    max_consecutive_empty_pages: int,
    verbose: bool,
    item_label: str,
) -> Iterator[list]:
    url: Optional[str] = start_url
    seen_urls: set[str] = set()
    seen_item_ids: set[str] = set()
    page_number = 0
    consecutive_empty_pages = 0
    total_items = 0

    while url:
        page_number += 1
        if page_number > max_pages:
            print(
                f"Stopped after {max_pages} pages (safety limit). "
                f"Fetched {total_items} unique {item_label} so far.",
                file=sys.stderr,
            )
            break

        if url in seen_urls:
            print(
                "Stopped: pagination returned a repeated next URL.",
                file=sys.stderr,
            )
            break
        seen_urls.add(url)

        response = request_page(session, url, headers)
        items = response.json().get("items", [])
        new_items = []
        for item in items:
            item_id = item.get("id")
            if item_id and item_id in seen_item_ids:
                continue
            if item_id:
                seen_item_ids.add(item_id)
            new_items.append(item)

        if not items:
            consecutive_empty_pages += 1
            if verbose:
                print(
                    f"Page {page_number}: 0 {item_label} "
                    f"(empty page {consecutive_empty_pages})",
                    file=sys.stderr,
                )
            if consecutive_empty_pages >= max_consecutive_empty_pages:
                print(
                    f"Stopped after {max_consecutive_empty_pages} consecutive "
                    "empty pages.",
                    file=sys.stderr,
                )
                break
        else:
            consecutive_empty_pages = 0
            if not new_items:
                print(
                    f"Stopped: page contained only {item_label} already fetched.",
                    file=sys.stderr,
                )
                break
            total_items += len(new_items)
            if verbose:
                print(
                    f"Page {page_number}: {len(new_items)} new {item_label} "
                    f"({total_items} total)",
                    file=sys.stderr,
                )
            yield new_items

        url = get_next_url(response)


def iter_room_pages(
    session: requests.Session,
    start_url: str,
    headers: dict,
    *,
    max_pages: int,
    max_consecutive_empty_pages: int,
    verbose: bool,
) -> Iterator[list]:
    yield from iter_paginated_items(
        session,
        start_url,
        headers,
        max_pages=max_pages,
        max_consecutive_empty_pages=max_consecutive_empty_pages,
        verbose=verbose,
        item_label="rooms",
    )


def fetch_person_id(session: requests.Session, headers: dict) -> str:
    response = request_page(session, f"{WEBEX_API_BASE}/people/me", headers)
    person_id = response.json().get("id")
    if not person_id:
        print("Failed to retrieve the authenticated user's person ID.", file=sys.stderr)
        sys.exit(1)
    return person_id


def fetch_teams(session: requests.Session, headers: dict) -> dict[str, str]:
    teams: dict[str, str] = {}
    start_url = f"{WEBEX_API_BASE}/teams?max={DEFAULT_PAGE_SIZE}"

    for page in iter_paginated_items(
        session,
        start_url,
        headers,
        max_pages=DEFAULT_MAX_PAGES,
        max_consecutive_empty_pages=DEFAULT_MAX_CONSECUTIVE_EMPTY_PAGES,
        verbose=False,
        item_label="teams",
    ):
        for team in page:
            team_id = team.get("id")
            if team_id:
                teams[team_id] = team.get("name") or "Unknown team"

    return teams


def collect_rooms(
    session: requests.Session,
    rooms_url: str,
    headers: dict,
    *,
    max_pages: int,
    max_consecutive_empty_pages: int,
    verbose: bool,
) -> list[dict]:
    rooms: list[dict] = []
    try:
        for page in iter_room_pages(
            session,
            rooms_url,
            headers,
            max_pages=max_pages,
            max_consecutive_empty_pages=max_consecutive_empty_pages,
            verbose=verbose,
        ):
            rooms.extend(page)
    except KeyboardInterrupt:
        if rooms:
            print(
                f"\nInterrupted after fetching {len(rooms)} spaces. "
                "Writing partial export...",
                file=sys.stderr,
            )
        else:
            raise
    return rooms


def room_uuid(room_id: str) -> Optional[str]:
    try:
        decoded_uri = base64.b64decode(room_id).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    return decoded_uri.split("/")[-1] or None


def room_to_deep_link(room_id: str) -> Optional[str]:
    uuid = room_uuid(room_id)
    return f"webexteams://im?space={uuid}" if uuid else None


def room_to_web_link(room_id: str) -> Optional[str]:
    uuid = room_uuid(room_id)
    return f"https://web.webex.com/spaces/{uuid}" if uuid else None


def load_eurl_spaces(path: str) -> list[dict]:
    """Load spaces saved from https://eurl.io/api/spaces (signed in)."""
    try:
        with open(path, encoding="utf-8") as eurl_file:
            data = json.load(eurl_file)
    except (OSError, ValueError) as exc:
        print(f"Error: Could not read --eurl-file {path}: {exc}", file=sys.stderr)
        sys.exit(1)

    spaces = data.get("spaces") if isinstance(data, dict) else data
    if not isinstance(spaces, list):
        print(
            "Error: --eurl-file must be the JSON from https://eurl.io/api/spaces "
            '(an object with a "spaces" list, or a list of spaces).',
            file=sys.stderr,
        )
        sys.exit(1)
    return [space for space in spaces if isinstance(space, dict) and space.get("shortId")]


def build_eurl_links(rooms: list[dict], eurl_spaces: list[dict]) -> dict[str, str]:
    """Map Webex room ID -> Eurl join URL, matching by title."""
    by_title: dict[str, list[str]] = {}
    for space in eurl_spaces:
        title = (space.get("title") or "").strip().casefold()
        by_title.setdefault(title, []).append(space["shortId"])

    room_title_counts: dict[str, int] = {}
    for room in rooms:
        title = (room.get("title") or "").strip().casefold()
        room_title_counts[title] = room_title_counts.get(title, 0) + 1

    links: dict[str, str] = {}
    ambiguous: set[str] = set()
    for room in rooms:
        room_id = room.get("id")
        title = (room.get("title") or "").strip().casefold()
        short_ids = by_title.get(title)
        if not room_id or not short_ids:
            continue
        if len(short_ids) > 1 or room_title_counts[title] > 1:
            ambiguous.add(room.get("title") or "")
            continue
        links[room_id] = f"{EURL_BASE}{short_ids[0]}"

    if ambiguous:
        print(
            f"Skipped {len(ambiguous)} space title(s) shared by more than one "
            "space (Eurl match is by title): " + "; ".join(sorted(ambiguous)[:10]),
            file=sys.stderr,
        )
    return links


def room_creator_label(room: dict, person_id: str) -> str:
    creator_id = room.get("creatorId")
    if creator_id and creator_id == person_id:
        return CREATOR_CREATED_BY_ME
    return CREATOR_CREATED_BY_OTHERS


def room_team_label(room: dict, teams: dict[str, str]) -> str:
    team_id = room.get("teamId")
    if not team_id:
        return TEAM_NONE_LABEL
    team_name = teams.get(team_id)
    if team_name:
        return f"Team: {team_name}"
    return "Team: Unknown team"


def room_group_values(
    room: dict,
    group_fields: list[str],
    *,
    person_id: str,
    teams: dict[str, str],
) -> tuple[str, ...]:
    values: list[str] = []
    if "team" in group_fields:
        values.append(room_team_label(room, teams))
    if "creator" in group_fields:
        values.append(room_creator_label(room, person_id))
    return tuple(values)


def group_sort_key(group_values: tuple[str, ...]) -> tuple:
    key: list[tuple[int, str]] = []
    for value in group_values:
        if value in (TEAM_NONE_LABEL, CREATOR_CREATED_BY_OTHERS):
            key.append((1, value))
        else:
            key.append((0, value))
    return tuple(key)


class TextOutput:
    """Plain-text listing."""

    def __init__(self, file) -> None:
        self.file = file

    def start(self) -> None:
        pass

    def heading(self, level: int, text: str) -> None:
        marker = "===" if level == 0 else "---"
        self.file.write(f"{marker} {text} {marker}\n\n")

    def entry(self, name, deep_link, web_link, eurl, show_eurl) -> None:
        self.file.write(f"Space Name: {name}\n")
        self.file.write(f"Space Link: {deep_link}\n")
        self.file.write(f"Space Web Link: {web_link}\n")
        if show_eurl:
            self.file.write(f"Eurl: {eurl or '(not found)'}\n")
        self.file.write("\n")

    def missing(self, name) -> None:
        self.file.write(f"Space Name: {name} (No space link available)\n\n")

    def flush(self) -> None:
        self.file.flush()


class MarkdownOutput:
    """Markdown listing: headings per group, one bullet per space."""

    _ESCAPE = str.maketrans({c: "\\" + c for c in "\\`*_{}[]<>|#"})

    def __init__(self, file) -> None:
        self.file = file

    def start(self) -> None:
        self.file.write("# Webex Spaces\n\n")

    def heading(self, level: int, text: str) -> None:
        self.file.write(f"{'#' * (level + 2)} {self._esc(text)}\n\n")

    def entry(self, name, deep_link, web_link, eurl, show_eurl) -> None:
        links = [f"[App]({deep_link})", f"[Web]({web_link})"]
        if eurl:
            links.append(f"[Eurl]({eurl})")
        self.file.write(f"- **{self._esc(name)}** — {' · '.join(links)}\n")

    def missing(self, name) -> None:
        self.file.write(f"- **{self._esc(name)}** — _no space link available_\n")

    def flush(self) -> None:
        self.file.flush()

    @classmethod
    def _esc(cls, text: str) -> str:
        return " ".join(str(text).split()).translate(cls._ESCAPE)


class Outputs:
    """Fan out writes to every enabled text-style output."""

    def __init__(self, outputs: list) -> None:
        self.outputs = outputs
        self._last_was_entry = False

    def start(self) -> None:
        for output in self.outputs:
            output.start()

    def heading(self, level: int, text: str) -> None:
        self._separate()
        for output in self.outputs:
            output.heading(level, text)

    def entry(self, *args) -> None:
        for output in self.outputs:
            output.entry(*args)
        self._last_was_entry = True

    def missing(self, name) -> None:
        for output in self.outputs:
            output.missing(name)
        self._last_was_entry = True

    def _separate(self) -> None:
        # Markdown bullet lists need a blank line before the next heading.
        if self._last_was_entry:
            for output in self.outputs:
                if isinstance(output, MarkdownOutput):
                    output.file.write("\n")
        self._last_was_entry = False

    def flush(self) -> None:
        for output in self.outputs:
            output.flush()


def write_group_heading(
    out,
    group_values: tuple[str, ...],
    level: int,
) -> None:
    out.heading(level, group_values[level])


def build_csv_row(
    room: dict,
    csv_columns: list[str],
    group_fields: list[str],
    group_values: tuple[str, ...],
    eurl_links: Optional[dict[str, str]] = None,
) -> list[str]:
    room_name = room.get("title", "")
    room_id = room.get("id")
    deep_link = room_to_deep_link(room_id) if room_id else None
    web_link = room_to_web_link(room_id) if room_id else None

    value_map = {
        "Space Name": room_name,
        "Space Link": deep_link or "",
        "Space Web Link": web_link or "",
        EURL_COLUMN: (eurl_links or {}).get(room_id or "", ""),
    }
    group_index = 0
    if "team" in group_fields:
        value_map["Team"] = group_values[group_index]
        group_index += 1
    if "creator" in group_fields:
        value_map["Creator"] = group_values[group_index]

    return [value_map[column] for column in csv_columns]


def write_room_entry(
    room: dict,
    out,
    writer: csv.writer,
    csv_columns: list[str],
    group_fields: list[str],
    group_values: tuple[str, ...],
    eurl_links: Optional[dict[str, str]] = None,
) -> bool:
    room_name = room.get("title", "")
    room_id = room.get("id")
    deep_link = room_to_deep_link(room_id) if room_id else None
    web_link = room_to_web_link(room_id) if room_id else None

    writer.writerow(
        build_csv_row(room, csv_columns, group_fields, group_values, eurl_links)
    )
    eurl = (eurl_links or {}).get(room_id or "")

    if deep_link:
        out.entry(room_name, deep_link, web_link, eurl, eurl_links is not None)
        return True

    out.missing(room_name)
    return False


def space_columns(eurl_links: Optional[dict[str, str]]) -> list[str]:
    columns = list(SPACE_COLUMNS)
    if eurl_links is not None:
        columns.append(EURL_COLUMN)
    return columns


def csv_columns_for_group_fields(
    group_fields: list[str], eurl_links: Optional[dict[str, str]] = None
) -> list[str]:
    columns: list[str] = []
    if "team" in group_fields:
        columns.append("Team")
    if "creator" in group_fields:
        columns.append("Creator")
    columns.extend(space_columns(eurl_links))
    return columns


def write_flat_export(
    rooms: list[dict],
    out,
    writer: csv.writer,
    eurl_links: Optional[dict[str, str]] = None,
) -> int:
    count = 0
    csv_columns = space_columns(eurl_links)
    for room in sorted(rooms, key=lambda item: (item.get("title") or "").casefold()):
        if write_room_entry(
            room, out, writer, csv_columns, [], (), eurl_links
        ):
            count += 1
    return count


def write_grouped_export(
    rooms: list[dict],
    out,
    writer: csv.writer,
    group_fields: list[str],
    *,
    person_id: str,
    teams: dict[str, str],
    eurl_links: Optional[dict[str, str]] = None,
) -> int:
    csv_columns = csv_columns_for_group_fields(group_fields, eurl_links)
    grouped_rooms = sorted(
        rooms,
        key=lambda room: (
            group_sort_key(room_group_values(room, group_fields, person_id=person_id, teams=teams)),
            (room.get("title") or "").casefold(),
        ),
    )

    count = 0
    current_group: Optional[tuple[str, ...]] = None

    for room in grouped_rooms:
        group_values = room_group_values(
            room,
            group_fields,
            person_id=person_id,
            teams=teams,
        )

        if group_values != current_group:
            for level in range(len(group_values)):
                if (
                    current_group is None
                    or current_group[: level + 1] != group_values[: level + 1]
                ):
                    write_group_heading(out, group_values, level)
            current_group = group_values

        if write_room_entry(
            room, out, writer, csv_columns, group_fields, group_values, eurl_links
        ):
            count += 1

    return count


def export_spaces(
    txt_path: str,
    csv_path: str,
    rooms_url: str,
    headers: dict,
    *,
    group_fields: list[str],
    max_pages: int,
    max_consecutive_empty_pages: int,
    verbose: bool,
    eurl_spaces: Optional[list[dict]] = None,
    md_path: Optional[str] = None,
) -> int:
    session = requests.Session()

    if verbose:
        print("Fetching spaces...", file=sys.stderr)

    rooms = collect_rooms(
        session,
        rooms_url,
        headers,
        max_pages=max_pages,
        max_consecutive_empty_pages=max_consecutive_empty_pages,
        verbose=verbose,
    )

    eurl_links: Optional[dict[str, str]] = None
    if eurl_spaces is not None:
        eurl_links = build_eurl_links(rooms, eurl_spaces)
        if verbose:
            print(
                f"Matched {len(eurl_links)} of {len(rooms)} spaces to Eurl links.",
                file=sys.stderr,
            )

    person_id = ""
    teams: dict[str, str] = {}
    if group_fields:
        if "creator" in group_fields:
            if verbose:
                print("Fetching your person ID...", file=sys.stderr)
            person_id = fetch_person_id(session, headers)
        if "team" in group_fields:
            if verbose:
                print("Fetching teams...", file=sys.stderr)
            teams = fetch_teams(session, headers)

    with contextlib.ExitStack() as stack:
        txt_file = stack.enter_context(open(txt_path, "w", encoding="utf-8"))
        csv_file = stack.enter_context(
            open(csv_path, "w", encoding="utf-8", newline="")
        )
        outputs: list = [TextOutput(txt_file)]
        if md_path:
            md_file = stack.enter_context(open(md_path, "w", encoding="utf-8"))
            outputs.append(MarkdownOutput(md_file))
        out = Outputs(outputs)
        out.start()
        if group_fields:
            csv_columns = csv_columns_for_group_fields(group_fields, eurl_links)
        else:
            csv_columns = space_columns(eurl_links)

        writer = csv.writer(csv_file, delimiter="\t")
        writer.writerow(csv_columns)
        out.flush()
        csv_file.flush()

        if group_fields:
            count = write_grouped_export(
                rooms,
                out,
                writer,
                group_fields,
                person_id=person_id,
                teams=teams,
                eurl_links=eurl_links,
            )
        else:
            count = write_flat_export(rooms, out, writer, eurl_links)

        out.flush()
        csv_file.flush()

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
    parser.add_argument(
        "--md",
        nargs="?",
        const="WebexSpaces.md",
        default=None,
        metavar="PATH",
        help="Also write a Markdown file (default path if no value: WebexSpaces.md)",
    )
    parser.add_argument(
        "--group-by",
        default="",
        help="Comma-separated grouping fields: team, creator (example: team,creator)",
    )
    parser.add_argument(
        "--sort-by",
        choices=("id", "lastactivity", "created"),
        default="id",
        help="Room sort order for API pagination (default: id)",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help=f"Rooms per API page (default: {DEFAULT_PAGE_SIZE})",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help=f"Safety limit on API pages fetched (default: {DEFAULT_MAX_PAGES})",
    )
    parser.add_argument(
        "--max-empty-pages",
        type=int,
        default=DEFAULT_MAX_CONSECUTIVE_EMPTY_PAGES,
        help=(
            "Stop after this many consecutive empty API pages "
            f"(default: {DEFAULT_MAX_CONSECUTIVE_EMPTY_PAGES})"
        ),
    )
    parser.add_argument(
        "--eurl-file",
        default="",
        help=(
            "JSON saved from https://eurl.io/api/spaces (while signed in). "
            "Adds an Eurl join-link column, matched by space title"
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable progress output",
    )
    args = parser.parse_args()

    if args.page_size < 1:
        print("Error: --page-size must be at least 1.", file=sys.stderr)
        sys.exit(1)
    if args.max_pages < 1:
        print("Error: --max-pages must be at least 1.", file=sys.stderr)
        sys.exit(1)

    group_fields = parse_group_by(args.group_by)
    eurl_spaces = load_eurl_spaces(args.eurl_file) if args.eurl_file else None
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    rooms_url = build_rooms_url(args.sort_by, args.page_size)

    try:
        count = export_spaces(
            args.txt,
            args.csv,
            rooms_url,
            headers,
            group_fields=group_fields,
            max_pages=args.max_pages,
            max_consecutive_empty_pages=args.max_empty_pages,
            verbose=not args.quiet,
            eurl_spaces=eurl_spaces,
            md_path=args.md,
        )
    except KeyboardInterrupt:
        print(
            "\nInterrupted. Partial results were saved to "
            f"{args.txt} and {args.csv}" + (f" (and {args.md})" if args.md else "") + ".",
            file=sys.stderr,
        )
        sys.exit(130)

    outputs = f"{args.txt} and {args.csv}"
    if args.md:
        outputs = f"{args.txt}, {args.csv} and {args.md}"
    print(f"Exported {count} spaces to {outputs}")


if __name__ == "__main__":
    main()
