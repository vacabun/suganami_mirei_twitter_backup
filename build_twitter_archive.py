#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import quote


DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".m4v", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
CHROME_CANDIDATES = [
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]


@dataclass
class MediaItem:
    path: Path
    rel_url: str
    kind: str


@dataclass
class TweetEntry:
    tweet_id: str
    date: datetime
    date_text: str
    date_original: str | None
    screen_name: str
    display_name: str
    content: str
    source: str
    lang: str
    retweet_id: int
    reply_id: int
    quote_id: int
    favorite_count: int
    reply_count: int
    retweet_count: int
    quote_count: int
    bookmark_count: int
    view_count: int
    media: list[MediaItem]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a static HTML timeline from a gallery-dl Twitter/X archive."
    )
    parser.add_argument(
        "archive_dir",
        nargs="?",
        default="gallery-dl/twitter/suganami_mirei",
        help="Archive directory containing tweet JSON/TXT/media files.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output HTML path. Defaults to <archive_dir>/timeline.html",
    )
    parser.add_argument(
        "--title",
        help="Custom page title. Defaults to '<display_name> バックアップ'.",
    )
    parser.add_argument(
        "--order",
        choices=("asc", "desc"),
        default="asc",
        help="Sort order by archive tweet date.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Render only the first N tweets after sorting. 0 means all.",
    )
    parser.add_argument(
        "--pdf",
        nargs="?",
        const="AUTO",
        help="Also export PDF with local Chrome/Chromium. Optional value sets PDF path.",
    )
    parser.add_argument(
        "--chrome-binary",
        help="Explicit Chrome/Chromium binary path for PDF export.",
    )
    return parser.parse_args()


def parse_datetime(value: str) -> datetime:
    return datetime.strptime(value, DATE_FORMAT)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace").strip()


def to_rel_url(path: Path, output_dir: Path) -> str:
    rel_path = os.path.relpath(path, output_dir)
    return quote(rel_path.replace(os.sep, "/"), safe="/._-")


def media_sort_key(path: Path) -> tuple[int, str]:
    match = re.search(r"_(\d+)(?:\.[^.]+)?$", path.name)
    if match:
        return (int(match.group(1)), path.name)
    return (sys.maxsize, path.name)


def load_profile(archive_dir: Path) -> dict[str, str]:
    info_path = archive_dir / "info.json"
    if info_path.exists():
        data = json.loads(read_text(info_path))
        user = data.get("user") or data.get("author") or {}
        return {
            "screen_name": user.get("name", archive_dir.name),
            "display_name": user.get("nick") or user.get("name", archive_dir.name),
            "description": user.get("description", ""),
            "profile_image": user.get("profile_image", ""),
            "profile_banner": user.get("profile_banner", ""),
            "homepage_url": user.get("url", ""),
            "location": user.get("location", ""),
        }
    return {
        "screen_name": archive_dir.name,
        "display_name": archive_dir.name,
        "description": "",
        "profile_image": "",
        "profile_banner": "",
        "homepage_url": "",
        "location": "",
    }


def build_media_index(archive_dir: Path, output_dir: Path) -> dict[str, list[MediaItem]]:
    media_index: dict[str, list[Path]] = {}
    for path in archive_dir.iterdir():
        if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
            continue
        stem_match = re.match(r"^(.*)_\d+$", path.stem)
        if not stem_match:
            continue
        tweet_stem = stem_match.group(1)
        media_index.setdefault(tweet_stem, []).append(path)

    indexed_items: dict[str, list[MediaItem]] = {}
    for tweet_stem, paths in media_index.items():
        items: list[MediaItem] = []
        for path in sorted(paths, key=media_sort_key):
            suffix = path.suffix.lower()
            if suffix in IMAGE_EXTENSIONS:
                kind = "image"
            elif suffix in VIDEO_EXTENSIONS:
                kind = "video"
            else:
                continue
            items.append(MediaItem(path=path, rel_url=to_rel_url(path, output_dir), kind=kind))
        indexed_items[tweet_stem] = items
    return indexed_items


def load_tweets(archive_dir: Path, output_dir: Path) -> list[TweetEntry]:
    tweets: list[TweetEntry] = []
    media_index = build_media_index(archive_dir, output_dir)
    for json_path in sorted(archive_dir.glob("*.json")):
        if json_path.name == "info.json":
            continue
        try:
            data = json.loads(read_text(json_path))
        except json.JSONDecodeError as exc:
            print(f"Skip invalid JSON: {json_path} ({exc})", file=sys.stderr)
            continue

        txt_path = archive_dir / f"{json_path.stem}.txt"
        content = read_text(txt_path) if txt_path.exists() else data.get("content", "")
        if not content:
            content = data.get("content", "")

        user = data.get("user") or data.get("author") or {}
        tweets.append(
            TweetEntry(
                tweet_id=str(data.get("tweet_id", json_path.stem)),
                date=parse_datetime(data["date"]),
                date_text=data["date"],
                date_original=data.get("date_original"),
                screen_name=user.get("name", archive_dir.name),
                display_name=user.get("nick") or user.get("name", archive_dir.name),
                content=content,
                source=data.get("source", ""),
                lang=data.get("lang", ""),
                retweet_id=int(data.get("retweet_id") or 0),
                reply_id=int(data.get("reply_id") or 0),
                quote_id=int(data.get("quote_id") or 0),
                favorite_count=int(data.get("favorite_count") or 0),
                reply_count=int(data.get("reply_count") or 0),
                retweet_count=int(data.get("retweet_count") or 0),
                quote_count=int(data.get("quote_count") or 0),
                bookmark_count=int(data.get("bookmark_count") or 0),
                view_count=int(data.get("view_count") or 0),
                media=media_index.get(json_path.stem, []),
            )
        )
    return tweets


def format_number(value: int) -> str:
    return f"{value:,}"


def type_badges(tweet: TweetEntry) -> list[str]:
    badges: list[str] = []
    if tweet.retweet_id:
        badges.append("リポスト")
    if tweet.reply_id:
        badges.append("返信")
    if tweet.quote_id:
        badges.append("引用")
    if not badges:
        badges.append("通常投稿")
    return badges


def render_badges(tweet: TweetEntry) -> str:
    return "".join(f'<span class="badge">{html.escape(label)}</span>' for label in type_badges(tweet))


def render_metrics(tweet: TweetEntry) -> str:
    items = [
        ("いいね", tweet.favorite_count),
        ("リポスト", tweet.retweet_count),
        ("返信", tweet.reply_count),
        ("引用", tweet.quote_count),
        ("ブックマーク", tweet.bookmark_count),
    ]
    if tweet.view_count:
        items.append(("表示", tweet.view_count))
    return "".join(
        f'<span class="metric"><strong>{html.escape(label)}</strong> {format_number(value)}</span>'
        for label, value in items
    )


def render_text_content(content: str) -> str:
    if not content.strip():
        return '<div class="tweet-text empty">[本文なし。メディアのみ、または反応系の投稿です]</div>'
    return f'<div class="tweet-text">{html.escape(content)}</div>'


def render_media(media: Iterable[MediaItem]) -> str:
    items = list(media)
    if not items:
        return ""

    parts = ['<div class="media-grid">']
    for item in items:
        filename = html.escape(item.path.name)
        if item.kind == "image":
            parts.append(
                "<figure class=\"media-card\">"
                f"<a href=\"{item.rel_url}\" target=\"_blank\" rel=\"noopener noreferrer\">"
                f"<img loading=\"lazy\" decoding=\"async\" src=\"{item.rel_url}\" alt=\"{filename}\">"
                "</a>"
                f"<figcaption>{filename}</figcaption>"
                "</figure>"
            )
        else:
            parts.append(
                "<figure class=\"media-card video-card\">"
                f"<video controls preload=\"none\" src=\"{item.rel_url}\"></video>"
                f"<div class=\"video-print-note\">動画ファイル: {filename}</div>"
                f"<figcaption><a href=\"{item.rel_url}\" target=\"_blank\" rel=\"noopener noreferrer\">{filename}</a></figcaption>"
                "</figure>"
            )
    parts.append("</div>")
    return "".join(parts)


def month_toc(tweets: list[TweetEntry]) -> str:
    tree: dict[int, list[int]] = {}
    seen_months: set[tuple[int, int]] = set()
    for tweet in tweets:
        key = (tweet.date.year, tweet.date.month)
        if key in seen_months:
            continue
        seen_months.add(key)
        tree.setdefault(tweet.date.year, []).append(tweet.date.month)

    if not tree:
        return ""

    parts = ['      <aside class="toc-panel" aria-label="月別目次">\n', '        <div class="toc-title">月別目次</div>\n']
    for year, months in tree.items():
        parts.append(f'        <details class="toc-year" open><summary>{year}</summary><div class="toc-months">')
        for month in months:
            month_key = f"{year:04d}-{month:02d}"
            parts.append(
                f'<button type="button" class="toc-month-button" data-month-key="{month_key}">{month:02d}月</button>'
            )
        parts.append("</div></details>\n")
    parts.append("      </aside>\n")
    return "".join(parts)


def render_tweet(tweet: TweetEntry) -> str:
    permalink = f"https://x.com/{tweet.screen_name}/status/{tweet.tweet_id}"
    original_date = ""
    if tweet.date_original and tweet.date_original != tweet.date_text:
        original_date = f'<span class="meta-item">元の日時 {html.escape(tweet.date_original)}</span>'

    source = f'<span class="meta-item">投稿元 {html.escape(tweet.source)}</span>' if tweet.source else ""
    lang = f'<span class="meta-item">言語 {html.escape(tweet.lang)}</span>' if tweet.lang else ""

    return (
        f'<article class="tweet" id="tweet-{tweet.tweet_id}">'
        "<header class=\"tweet-header\">"
        "<div>"
        f'<div class="tweet-author">{html.escape(tweet.display_name)} '
        f'<span class="screen-name">@{html.escape(tweet.screen_name)}</span></div>'
        f'<div class="tweet-meta"><span class="meta-item">{html.escape(tweet.date_text)}</span>{original_date}{source}{lang}</div>'
        "</div>"
        f'<div class="badge-row">{render_badges(tweet)}</div>'
        "</header>"
        f"{render_text_content(tweet.content)}"
        f"{render_media(tweet.media)}"
        f'<footer class="tweet-footer"><div class="metrics">{render_metrics(tweet)}</div>'
        f'<a class="permalink" href="{permalink}" target="_blank" rel="noopener noreferrer">元の投稿を見る</a></footer>'
        "</article>"
    )


def timeline_payload(tweets: list[TweetEntry]) -> str:
    payload = [
        {
            "year": tweet.date.year,
            "month": tweet.date.month,
            "month_key": f"{tweet.date.year:04d}-{tweet.date.month:02d}",
            "month_label": f"{tweet.date.year}年{tweet.date.month:02d}月",
            "html": render_tweet(tweet),
        }
        for tweet in tweets
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def page_javascript() -> str:
    return """
    (() => {
        const CHUNK_SIZE = 36;
        const PREFETCH_MARGIN = "1400px 0px";
        const dataNode = document.getElementById("tweet-data");
        const timeline = document.getElementById("timeline");
        const sentinel = document.getElementById("load-sentinel");
        const loadMoreButton = document.getElementById("load-more");
        const statusNode = document.getElementById("timeline-status");
        const monthButtons = Array.from(document.querySelectorAll(".toc-month-button"));

        if (!dataNode || !timeline || !sentinel || !loadMoreButton || !statusNode) {
            return;
        }

        const entries = JSON.parse(dataNode.textContent || "[]");
        const numberFormatter = new Intl.NumberFormat("ja-JP");
        let cursor = 0;
        let currentYear = null;
        let currentYearSection = null;
        let currentMonthKey = null;
        let currentList = null;
        let observer = null;
        let loadLock = false;

        function updateStatus() {
            const loaded = numberFormatter.format(cursor);
            const total = numberFormatter.format(entries.length);
            statusNode.textContent =
                cursor >= entries.length
                    ? `全 ${total} 件の投稿を読み込みました`
                    : `${loaded} / ${total} 件の投稿を読み込みました`;
            loadMoreButton.hidden = cursor >= entries.length;
            sentinel.hidden = cursor >= entries.length;
        }

        function ensureYearSection(year) {
            if (currentYear === year && currentYearSection) {
                return currentYearSection;
            }

            const existing = document.getElementById(`year-${year}`);
            if (existing) {
                currentYear = year;
                currentYearSection = existing;
                return existing;
            }

            const section = document.createElement("section");
            section.className = "year-section";
            section.id = `year-${year}`;

            const title = document.createElement("h2");
            title.className = "year-title";
            title.textContent = String(year);

            const monthStack = document.createElement("div");
            monthStack.className = "month-stack";

            section.append(title, monthStack);
            timeline.appendChild(section);
            currentYear = year;
            currentYearSection = section;
            return section;
        }

        function ensureMonthGroup(entry) {
            if (currentMonthKey === entry.month_key && currentList) {
                return currentList;
            }

            const yearSection = ensureYearSection(entry.year);
            const monthId = `month-${entry.month_key}`;
            const existing = document.getElementById(monthId);
            if (existing) {
                existing.open = true;
                currentMonthKey = entry.month_key;
                currentList = existing.querySelector(".tweet-list");
                return currentList;
            }

            const details = document.createElement("details");
            details.className = "month-group";
            details.id = monthId;
            details.open = true;

            const summary = document.createElement("summary");
            summary.className = "month-summary";
            summary.innerHTML = `<span class="month-label">${entry.month_label}</span>`;

            const list = document.createElement("div");
            list.className = "tweet-list";

            details.append(summary, list);
            yearSection.querySelector(".month-stack").appendChild(details);
            currentMonthKey = entry.month_key;
            currentList = list;
            return list;
        }

        function appendChunk(chunkSize = CHUNK_SIZE) {
            if (loadLock || cursor >= entries.length) {
                return false;
            }

            loadLock = true;
            let rendered = 0;

            while (cursor < entries.length && rendered < chunkSize) {
                const entry = entries[cursor];
                const list = ensureMonthGroup(entry);
                list.insertAdjacentHTML("beforeend", entry.html);
                cursor += 1;
                rendered += 1;
            }

            updateStatus();
            loadLock = false;
            return rendered > 0;
        }

        function loadUntilMonth(monthKey) {
            while (!document.getElementById(`month-${monthKey}`) && cursor < entries.length) {
                appendChunk(Math.max(CHUNK_SIZE, 72));
            }

            const target = document.getElementById(`month-${monthKey}`);
            if (target) {
                target.open = true;
                target.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        }

        monthButtons.forEach((button) => {
            button.addEventListener("click", () => {
                const monthKey = button.dataset.monthKey;
                if (monthKey) {
                    loadUntilMonth(monthKey);
                }
            });
        });

        loadMoreButton.addEventListener("click", () => {
            appendChunk();
        });

        if ("IntersectionObserver" in window) {
            observer = new IntersectionObserver(
                (observerEntries) => {
                    if (observerEntries.some((entry) => entry.isIntersecting)) {
                        appendChunk();
                    }
                },
                { rootMargin: PREFETCH_MARGIN }
            );
            observer.observe(sentinel);
        }

        appendChunk();
        updateStatus();
    })();
    """


def page_css() -> str:
    return """
    :root {
        color-scheme: light;
        --bg: #eef7ff;
        --panel: rgba(255, 255, 255, 0.88);
        --panel-border: rgba(93, 148, 191, 0.18);
        --text: #18324a;
        --muted: #5f7f98;
        --accent: #5aa9da;
        --accent-soft: #dff1ff;
        --shadow: 0 18px 50px rgba(73, 126, 170, 0.12);
    }

    * {
        box-sizing: border-box;
    }

    html {
        scroll-behavior: smooth;
    }

    body {
        margin: 0;
        font-family: "Hiragino Sans GB", "PingFang SC", "Noto Serif CJK SC", serif;
        color: var(--text);
        background:
            radial-gradient(circle at top left, rgba(150, 208, 244, 0.42), transparent 28%),
            radial-gradient(circle at top right, rgba(120, 186, 232, 0.28), transparent 30%),
            linear-gradient(180deg, #f7fcff 0%, var(--bg) 48%, #deefff 100%);
        line-height: 1.7;
    }

    a {
        color: var(--accent);
    }

    .page {
        width: min(1220px, calc(100vw - 32px));
        margin: 0 auto;
        padding: 18px 0 48px;
    }

    .page-shell {
        display: grid;
        grid-template-columns: 220px minmax(0, 1fr);
        gap: 18px;
        align-items: start;
    }

    .content-column {
        min-width: 0;
    }

    .hero {
        margin-bottom: 24px;
        padding: 14px;
        background: rgba(244, 250, 255, 0.96);
        border-bottom: 1px solid rgba(93, 148, 191, 0.14);
        border-radius: 20px;
        box-shadow: 0 10px 30px rgba(73, 126, 170, 0.08);
    }

    .hero-banner {
        width: 100%;
        aspect-ratio: 5 / 1;
        overflow: hidden;
        border-radius: 14px;
        background:
            linear-gradient(135deg, rgba(154, 214, 248, 0.48), rgba(90, 169, 218, 0.22)),
            #dcedfb;
    }

    .hero-banner img {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    .hero-card {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: 14px;
        align-items: start;
        margin-top: 14px;
    }

    .hero-avatar {
        width: 72px;
        height: 72px;
        border-radius: 50%;
        overflow: hidden;
        border: 3px solid rgba(255, 255, 255, 0.92);
        box-shadow: 0 8px 20px rgba(73, 126, 170, 0.14);
        background: #dcedfb;
    }

    .hero-avatar img {
        display: block;
        width: 100%;
        height: 100%;
        object-fit: cover;
    }

    .hero-copy {
        min-width: 0;
    }

    .hero-name-row {
        display: flex;
        flex-wrap: wrap;
        gap: 6px 10px;
        align-items: baseline;
    }

    .hero-handle {
        color: var(--muted);
        font-size: 0.92rem;
    }

    .hero-note {
        margin: 6px 0 0;
        color: var(--muted);
        font-size: 0.88rem;
    }

    .profile-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 10px;
    }

    .hero h1 {
        margin: 0;
        font-size: clamp(1.15rem, 2vw, 1.7rem);
        line-height: 1.25;
        letter-spacing: 0.02em;
    }

    .hero p {
        margin: 8px 0 0;
        color: var(--muted);
        max-width: 72ch;
        font-size: 0.92rem;
    }

    .timeline {
        display: grid;
        gap: 24px;
    }

    .toc-panel {
        position: sticky;
        top: 18px;
        padding: 12px;
        border-radius: 18px;
        background: rgba(244, 250, 255, 0.96);
        border: 1px solid rgba(93, 148, 191, 0.14);
        box-shadow: 0 10px 30px rgba(73, 126, 170, 0.08);
        max-height: calc(100vh - 36px);
        overflow: auto;
    }

    .toc-title {
        font-size: 0.92rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        margin-bottom: 10px;
    }

    .toc-year + .toc-year {
        margin-top: 8px;
    }

    .toc-year summary {
        cursor: pointer;
        list-style: none;
        font-weight: 700;
        font-size: 0.92rem;
        color: var(--text);
    }

    .toc-year summary::-webkit-details-marker {
        display: none;
    }

    .toc-year summary::before {
        content: "▸";
        color: var(--accent);
        margin-right: 6px;
        transition: transform 0.18s ease;
        display: inline-block;
    }

    .toc-year[open] summary::before {
        transform: rotate(90deg);
    }

    .toc-months {
        display: grid;
        gap: 6px;
        padding: 8px 0 2px 16px;
    }

    .profile-meta a,
    .profile-meta span,
    .summary span,
    .toc-month-button,
    .load-more {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        padding: 5px 10px;
        border-radius: 999px;
        background: var(--accent-soft);
        color: var(--text);
        text-decoration: none;
        font-size: 0.84rem;
        border: 0;
        cursor: pointer;
    }

    .toc-month-button {
        justify-content: flex-start;
        width: 100%;
        background: rgba(255, 255, 255, 0.7);
        border: 1px solid rgba(93, 148, 191, 0.12);
    }

    .summary {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 12px;
    }

    .timeline-controls {
        display: flex;
        align-items: center;
        justify-content: center;
        margin-top: 18px;
    }

    .timeline-status {
        margin-top: 12px;
        text-align: center;
        color: var(--muted);
        font-size: 0.88rem;
    }

    .load-sentinel {
        height: 1px;
    }

    .load-more {
        min-width: 144px;
        background: rgba(90, 169, 218, 0.16);
    }

    .year-section {
        margin-top: 0;
        display: grid;
        gap: 12px;
    }

    .year-title {
        margin: 0 0 14px;
        font-size: 1.25rem;
        letter-spacing: 0.06em;
    }

    .month-stack {
        display: grid;
        gap: 12px;
    }

    .month-group {
        border: 1px solid rgba(93, 148, 191, 0.14);
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.52);
        padding: 0 14px 12px;
    }

    .month-group[open] {
        box-shadow: 0 10px 24px rgba(73, 126, 170, 0.06);
    }

    .month-summary {
        cursor: pointer;
        list-style: none;
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 0;
        font-size: 0.96rem;
        font-weight: 700;
    }

    .month-summary::-webkit-details-marker {
        display: none;
    }

    .month-summary::before {
        content: "▸";
        color: var(--accent);
        transition: transform 0.18s ease;
        display: inline-block;
    }

    .month-group[open] .month-summary::before {
        transform: rotate(90deg);
    }

    .tweet-list {
        display: grid;
        gap: 14px;
    }

    .tweet {
        padding: 16px 18px;
        background: var(--panel);
        border: 1px solid var(--panel-border);
        border-radius: 18px;
        box-shadow: 0 10px 28px rgba(73, 126, 170, 0.08);
        content-visibility: auto;
        contain-intrinsic-size: 320px;
    }

    .tweet-header,
    .tweet-footer {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 16px;
    }

    .tweet-author {
        font-size: 0.98rem;
        font-weight: 700;
    }

    .screen-name,
    .tweet-meta,
    figcaption,
    .video-print-note {
        color: var(--muted);
    }

    .tweet-meta,
    .metrics {
        display: flex;
        flex-wrap: wrap;
        gap: 8px 14px;
        font-size: 0.86rem;
        margin-top: 6px;
    }

    .meta-item::before {
        content: "•";
        margin-right: 6px;
        color: rgba(122, 101, 80, 0.55);
    }

    .meta-item:first-child::before {
        content: "";
        margin-right: 0;
    }

    .badge-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
    }

    .badge {
        display: inline-flex;
        align-items: center;
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(161, 79, 42, 0.12);
        color: var(--accent);
        font-size: 0.76rem;
        font-weight: 700;
        white-space: nowrap;
    }

    .tweet-text {
        margin-top: 12px;
        white-space: pre-wrap;
        word-break: break-word;
        font-size: 0.95rem;
    }

    .tweet-text.empty {
        font-style: italic;
    }

    .media-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 12px;
        margin-top: 14px;
    }

    .media-card {
        margin: 0;
        padding: 8px;
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.75);
        border: 1px solid rgba(93, 148, 191, 0.1);
    }

    .media-card img,
    .media-card video {
        display: block;
        width: 100%;
        max-height: 520px;
        object-fit: contain;
        border-radius: 12px;
        background: #e6f4ff;
    }

    figcaption {
        margin-top: 6px;
        font-size: 0.8rem;
        word-break: break-all;
    }

    .video-print-note {
        display: none;
        margin-top: 8px;
        font-size: 0.8rem;
    }

    .tweet-footer {
        margin-top: 14px;
        padding-top: 12px;
        border-top: 1px solid rgba(93, 148, 191, 0.14);
    }

    .metric strong {
        font-weight: 700;
        color: var(--text);
    }

    .permalink {
        text-decoration: none;
        white-space: nowrap;
    }

    @media (max-width: 760px) {
        .page {
            width: min(100vw - 20px, 1220px);
            padding-top: 14px;
            padding-bottom: 92px;
        }

        .page-shell {
            grid-template-columns: 1fr;
        }

        .hero-card {
            grid-template-columns: 1fr;
        }

        .hero-avatar {
            width: 64px;
            height: 64px;
        }

        .hero-banner {
            aspect-ratio: 3.2 / 1;
        }

        .hero h1 {
            font-size: 1.08rem;
        }

        .year-title {
            font-size: 1.08rem;
        }

        .toc-panel {
            position: fixed;
            left: 12px;
            bottom: 12px;
            top: auto;
            width: min(220px, calc(100vw - 24px));
            max-height: 44vh;
            z-index: 30;
        }

        .tweet-header,
        .tweet-footer {
            flex-direction: column;
        }
    }

    @media print {
        @page {
            size: A4;
            margin: 12mm;
        }

        body {
            background: #ffffff;
            font-size: 10.5pt;
        }

        .page {
            width: 100%;
            padding: 0;
        }

        .hero {
            background: #ffffff;
            border-bottom: 1px solid #cccccc;
            margin-bottom: 18px;
            padding: 0 0 12px;
            box-shadow: none;
            border-radius: 0;
        }

        .hero-banner {
            break-inside: avoid;
        }

        .toc-panel,
        .timeline-controls,
        .timeline-status,
        .load-sentinel {
            display: none;
        }

        .tweet {
            box-shadow: none;
            border: 1px solid #d2d2d2;
            background: #ffffff;
            content-visibility: visible;
            break-inside: avoid;
            page-break-inside: avoid;
        }

        .media-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .media-card video {
            display: none;
        }

        .video-print-note {
            display: block;
        }

        a {
            color: inherit;
            text-decoration: none;
        }
    }
    """


def render_page(
    output_path: Path,
    title: str,
    profile: dict[str, str],
    tweets: list[TweetEntry],
    order: str,
) -> None:
    total_images = sum(1 for tweet in tweets for item in tweet.media if item.kind == "image")
    total_videos = sum(1 for tweet in tweets for item in tweet.media if item.kind == "video")
    first_date = tweets[0].date_text if tweets else "-"
    last_date = tweets[-1].date_text if tweets else "-"
    payload = timeline_payload(tweets)
    toc = month_toc(tweets)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("<!DOCTYPE html>\n<html lang=\"ja\">\n<head>\n")
        handle.write("  <meta charset=\"utf-8\">\n")
        handle.write("  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
        handle.write(f"  <title>{html.escape(title)}</title>\n")
        handle.write("  <style>\n")
        handle.write(page_css())
        handle.write("\n  </style>\n</head>\n<body>\n")
        handle.write("  <div class=\"page\">\n")
        handle.write("    <div class=\"page-shell\">\n")
        if toc:
            handle.write(toc)
        handle.write("      <main class=\"content-column\">\n")
        handle.write("    <section class=\"hero\">\n")
        if profile.get("profile_banner"):
            handle.write(
                "      <div class=\"hero-banner\">"
                f"<img src=\"{html.escape(profile['profile_banner'], quote=True)}\" "
                f"alt=\"{html.escape(profile['display_name'])} banner\"></div>\n"
            )
        handle.write("      <div class=\"hero-card\">\n")
        if profile.get("profile_image"):
            handle.write(
                "        <div class=\"hero-avatar\">"
                f"<img src=\"{html.escape(profile['profile_image'], quote=True)}\" "
                f"alt=\"{html.escape(profile['display_name'])} avatar\"></div>\n"
            )
        handle.write("        <div class=\"hero-copy\">\n")
        handle.write("          <div class=\"hero-name-row\">\n")
        handle.write(f"            <h1>{html.escape(profile['display_name'])}</h1>\n")
        handle.write(
            f"            <span class=\"hero-handle\">@{html.escape(profile['screen_name'])}</span>\n"
        )
        handle.write("          </div>\n")
        handle.write("          <p class=\"hero-note\">これはバックアップサイトです。</p>\n")
        if profile.get("description"):
            handle.write(f"          <p>{html.escape(profile['description'])}</p>\n")
        handle.write("          <div class=\"profile-meta\">\n")
        handle.write(
            f"            <a href=\"https://x.com/{quote(profile['screen_name'])}\" "
            "target=\"_blank\" rel=\"noopener noreferrer\">X プロフィール</a>\n"
        )
        if profile.get("homepage_url"):
            handle.write(
                f"            <a href=\"{html.escape(profile['homepage_url'], quote=True)}\" "
                "target=\"_blank\" rel=\"noopener noreferrer\">公式リンク</a>\n"
            )
        if profile.get("location"):
            handle.write(f"            <span>{html.escape(profile['location'])}</span>\n")
        handle.write("          </div>\n")
        handle.write("      <div class=\"summary\">\n")
        handle.write(f"        <span>投稿 {format_number(len(tweets))} 件</span>\n")
        handle.write(f"        <span>画像 {format_number(total_images)} 枚</span>\n")
        handle.write(f"        <span>動画 {format_number(total_videos)} 本</span>\n")
        handle.write(f"        <span>期間 {html.escape(first_date)} から {html.escape(last_date)}</span>\n")
        handle.write("      </div>\n")
        handle.write("        </div>\n")
        handle.write("      </div>\n")
        handle.write("    </section>\n")
        handle.write('    <div id="timeline" class="timeline"></div>\n')
        handle.write('    <div class="timeline-controls"><button id="load-more" class="load-more" type="button">さらに読み込む</button></div>\n')
        handle.write('    <div id="timeline-status" class="timeline-status" aria-live="polite"></div>\n')
        handle.write('    <div id="load-sentinel" class="load-sentinel" aria-hidden="true"></div>\n')
        handle.write("      </main>\n")
        handle.write("    </div>\n")
        handle.write("  </div>\n")
        handle.write(f'  <script id="tweet-data" type="application/json">{payload}</script>\n')
        handle.write("  <script>\n")
        handle.write(page_javascript())
        handle.write("\n  </script>\n</body>\n</html>\n")


def find_chrome_binary(explicit: str | None) -> str:
    if explicit:
        return explicit
    for candidate in CHROME_CANDIDATES:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
        if Path(candidate).exists():
            return candidate
    raise FileNotFoundError("No Chrome/Chromium binary found for PDF export.")


def resolve_pdf_path(pdf_arg: str, output_html: Path) -> Path:
    if pdf_arg == "AUTO":
        return output_html.with_suffix(".pdf")
    return Path(pdf_arg).expanduser().resolve()


def export_pdf(html_path: Path, pdf_path: Path, chrome_binary: str) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="twitter-archive-pdf-") as user_data_dir:
        cmd = [
            chrome_binary,
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--no-default-browser-check",
            "--allow-file-access-from-files",
            "--disable-crash-reporter",
            f"--user-data-dir={user_data_dir}",
            f"--print-to-pdf={pdf_path}",
            "--no-pdf-header-footer",
            html_path.resolve().as_uri(),
        ]
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )


def main() -> int:
    args = parse_args()
    archive_dir = Path(args.archive_dir).expanduser().resolve()
    if not archive_dir.exists():
        print(f"Archive directory does not exist: {archive_dir}", file=sys.stderr)
        return 1

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else archive_dir / "timeline.html"
    )

    profile = load_profile(archive_dir)
    tweets = load_tweets(archive_dir, output_path.parent)
    tweets.sort(key=lambda item: item.date, reverse=args.order == "desc")

    if args.limit > 0:
        tweets = tweets[: args.limit]

    title = args.title or f"{profile['display_name']} バックアップ"
    render_page(output_path=output_path, title=title, profile=profile, tweets=tweets, order=args.order)
    print(f"HTML written to: {output_path}")

    if args.pdf:
        pdf_path = resolve_pdf_path(args.pdf, output_path)
        try:
            chrome_binary = find_chrome_binary(args.chrome_binary)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        try:
            export_pdf(output_path, pdf_path, chrome_binary)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to export PDF with Chrome: {exc}", file=sys.stderr)
            return exc.returncode or 3
        print(f"PDF written to: {pdf_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
