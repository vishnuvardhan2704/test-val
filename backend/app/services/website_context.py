"""Helpers for turning a company website into concise reference context.

The goal is not full site crawling. We only fetch the provided homepage, extract a
few high-signal visible text fragments, and hand that back to the LLM as reference
context so it can better understand the company.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>'\"]+|www\.[^\s<>'\"]+", re.IGNORECASE)


def extract_website_url(text: str) -> str | None:
    match = _URL_RE.search(text or "")
    if not match:
        return None
    return normalize_website_url(match.group(0))


def normalize_website_url(raw_url: str | None) -> str | None:
    if not raw_url:
        return None

    candidate = raw_url.strip().rstrip(".,;:)")
    if not candidate:
        return None

    if not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    if not parsed.netloc:
        return None

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, ""))


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        normalized = " ".join(item.split()).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique


def fetch_website_context(raw_url: str | None, timeout_seconds: int = 10) -> str | None:
    url = normalize_website_url(raw_url)
    if not url:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
    }
    try:
        response = requests.get(url, headers=headers, timeout=timeout_seconds)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to fetch company website %s (%s)", url, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    chunks: list[str] = []

    if soup.title and soup.title.string:
        chunks.append(soup.title.string)

    for selector in (
        ("meta", {"name": "description"}),
        ("meta", {"property": "og:description"}),
        ("meta", {"name": "twitter:description"}),
    ):
        tag = soup.find(*selector)
        if tag and tag.get("content"):
            chunks.append(tag["content"])

    for tag_name in ("h1", "h2", "h3", "p", "li"):
        for tag in soup.find_all(tag_name):
            text = tag.get_text(" ", strip=True)
            if len(text) >= 20:
                chunks.append(text)

    chunks = _dedupe(chunks)
    if not chunks:
        return None

    context = "\n".join(chunks)
    if len(context) > 6000:
        context = context[:6000] + "\n[truncated]"

    return f"Source URL: {url}\n{context}"