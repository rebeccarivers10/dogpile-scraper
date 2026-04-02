"""
Dogpile.com Sponsored Ad Scraper

Uses patchright (undetected browser) to bypass Cloudflare automatically.
Ads are scraped from Google AFS iframes embedded in Dogpile search results.

Usage:
    py scraper.py "search term"
    py scraper.py "search term" --output results.json
    py scraper.py "search term" --output results.csv
    py scraper.py "search term" --sc YOUR_SC_CODE
    py scraper.py "search term" --show-browser    # run with visible Chrome window
"""

import argparse
import json
import csv
import os
import sys
import time
import re
from bs4 import BeautifulSoup
from patchright.sync_api import sync_playwright

HOMEPAGE = "https://www.dogpile.com/"
DEFAULT_SC = "UjKPOpvbJJPb10"  # kept for CLI --sc flag but no longer used for navigation
AFS_DISPLAY_URL = "syndicatedsearch.goog/afs/ads/i/iframe.html"


def fetch_ad_html(query: str, headless: bool = True, cf_timeout: int = 30) -> list[str]:
    """
    Launch Chrome via patchright, navigate to Dogpile homepage,
    bypass Cloudflare, submit the search, then return HTML from each AFS ad iframe.
    """
    ad_htmls = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Step 1: load homepage and bypass Cloudflare
        print("Loading Dogpile homepage...", file=sys.stderr)
        try:
            page.goto(HOMEPAGE, wait_until="load", timeout=45000)
        except Exception as e:
            print(f"Warning: goto failed: {e}", file=sys.stderr)

        print("Bypassing Cloudflare...", file=sys.stderr)
        deadline = time.time() + cf_timeout
        loaded = False
        while time.time() < deadline:
            try:
                title = page.title()
            except Exception:
                time.sleep(0.5)
                continue
            if "dogpile" in title.lower() and "moment" not in title.lower() and "attention" not in title.lower():
                loaded = True
                print(f"Homepage loaded: {title}", file=sys.stderr)
                break
            time.sleep(0.5)

        if not loaded:
            try:
                current_title = page.title()
            except Exception:
                current_title = "unavailable"
            print(f"Warning: Cloudflare did not pass within {cf_timeout}s. Title: {current_title}", file=sys.stderr)
            browser.close()
            return []

        # Step 2: submit search via the search box
        print(f"Searching for: {query}", file=sys.stderr)
        try:
            page.fill('input[name="q"]', query)
            page.press('input[name="q"]', "Enter")
            page.wait_for_load_state("load", timeout=30000)
        except Exception as e:
            print(f"Warning: search submission failed: {e}", file=sys.stderr)
            browser.close()
            return []

        # Step 3: wait for AFS ad iframes to load and render content
        print("Waiting for ads to render...", file=sys.stderr)
        deadline = time.time() + 20
        while time.time() < deadline:
            afs_frames = [f for f in page.frames if AFS_DISPLAY_URL in f.url]
            if afs_frames:
                for frame in afs_frames:
                    try:
                        html = frame.content()
                        if re.search(r'clicktrackedAd', html):
                            break
                    except Exception:
                        pass
                else:
                    time.sleep(0.5)
                    continue
                break
            time.sleep(0.5)

        # Step 4: collect HTML from all AFS display iframes
        afs_frames = [f for f in page.frames if AFS_DISPLAY_URL in f.url]
        print(f"Found {len(afs_frames)} AFS ad iframe(s)", file=sys.stderr)
        for frame in afs_frames:
            try:
                html = frame.content()
                ad_htmls.append(html)
            except Exception as e:
                print(f"Warning: could not read iframe: {e}", file=sys.stderr)

        browser.close()

    return ad_htmls


def parse_text(element) -> str:
    """Extract clean text from a BeautifulSoup element."""
    if element is None:
        return ""
    return " ".join(element.get_text(" ", strip=True).split())


def _find_class(element, *class_names: str):
    """Find first child element whose class list contains any of the given class names."""
    for cls in class_names:
        found = element.find(lambda tag: cls in (tag.get("class") or []))
        if found:
            return found
    return None


def parse_ads_from_html(html: str) -> list[dict]:
    """Parse sponsored ad data from a single AFS iframe HTML.

    Handles two ad formats served by Google AFS:
      - Text ads  (Frame 0): si27=headline, si42=advertiser, si44=display_url, si29=description
      - Product ads (Frame 1): si65=title, si60=advertiser, si61=price
    """
    soup = BeautifulSoup(html, "html.parser")
    ad_containers = soup.find_all(lambda tag: any("clicktrackedAd" in c for c in (tag.get("class") or [])))
    ads = []

    for container in ad_containers:
        ad: dict = {
            "ad_type": "",
            "advertiser": "",
            "display_url": "",
            "headline": "",
            "click_url": "",
            "description": "",
            "price": "",
            "sitelinks": [],
        }

        # --- Text ad format (si27 headline present) ---
        headline_el = _find_class(container, "si27")
        if headline_el:
            ad["ad_type"] = "text"
            ad["headline"] = parse_text(headline_el)
            ad["click_url"] = headline_el.get("href", "")

            advertiser_el = _find_class(container, "si42")
            if advertiser_el:
                ad["advertiser"] = parse_text(advertiser_el)

            display_url_el = _find_class(container, "si44")
            if display_url_el:
                # Remove spaces inserted by keyword-highlight <span> tags
                raw = parse_text(display_url_el)
                ad["display_url"] = re.sub(r"\s+", "", raw) if raw.startswith("http") else raw

            desc_el = _find_class(container, "si29")
            if desc_el:
                ad["description"] = parse_text(desc_el)

            # Sitelinks — si71 (expanded) or si15 (text style)
            seen_texts: set[str] = set()
            for sl in container.find_all(lambda tag: tag.name == "a" and
                                         any(c in (tag.get("class") or []) for c in ("si71", "si15"))):
                text = parse_text(sl)
                href = sl.get("href", "")
                if text and text not in seen_texts:
                    seen_texts.add(text)
                    ad["sitelinks"].append({"text": text, "url": href})

        # --- Product/shopping ad format (si65 title present, no si27) ---
        elif _find_class(container, "si65"):
            ad["ad_type"] = "product"
            title_el = _find_class(container, "si65")
            ad["headline"] = parse_text(title_el)
            ad["click_url"] = title_el.get("href", "") if title_el else ""

            advertiser_el = _find_class(container, "si60")
            if advertiser_el:
                ad["advertiser"] = parse_text(advertiser_el)

            price_el = _find_class(container, "si61", "si136")
            if price_el:
                ad["price"] = parse_text(price_el)

        else:
            # Unknown format — skip
            continue

        # Require at least a headline to include the ad
        if not ad["headline"]:
            continue

        # Drop any ad with no display URL
        if not ad["display_url"]:
            continue

        # Drop product ads with no click URL
        if ad["ad_type"] == "product" and not ad["click_url"]:
            continue

        ads.append(ad)

    return ads


def parse_all_ads(ad_htmls: list[str]) -> list[dict]:
    """Parse ads from multiple iframe HTML chunks, de-duplicate, add positions."""
    all_ads: list[dict] = []
    seen_keys: set[str] = set()

    for html in ad_htmls:
        for ad in parse_ads_from_html(html):
            key = ad["advertiser"] + "|" + ad["headline"]
            if key and key not in seen_keys:
                seen_keys.add(key)
                ad["position"] = len(all_ads) + 1
                all_ads.append(ad)

    return all_ads


def print_ads(ads: list[dict], query: str) -> None:
    print(f"\n{'='*60}")
    print(f'Dogpile Sponsored Ads — Query: "{query}"')
    print(f"Found {len(ads)} sponsored ad(s)")
    print(f"{'='*60}\n")

    for ad in ads:
        ad_type = ad.get("ad_type", "text")
        print(f"[Ad #{ad['position']}] ({ad_type})")
        print(f"  Advertiser : {ad['advertiser']}")
        if ad.get("display_url"):
            print(f"  Display URL: {ad['display_url']}")
        print(f"  Headline   : {ad['headline']}")
        if ad.get("price"):
            print(f"  Price      : {ad['price']}")
        if ad.get("description"):
            print(f"  Description: {ad['description']}")
        if ad.get("sitelinks"):
            print(f"  Sitelinks  :")
            for sl in ad["sitelinks"]:
                print(f"    - {sl['text']}")
        print()


def save_json(ads: list[dict], query: str, filepath: str) -> None:
    output = {"query": query, "ad_count": len(ads), "ads": ads}
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"Saved JSON to: {filepath}")


def save_csv(ads: list[dict], filepath: str) -> None:
    fieldnames = ["advertiser", "display_url"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for ad in ads:
            row = dict(ad)
            row["sitelinks"] = " | ".join(sl["text"] for sl in ad.get("sitelinks", []))
            writer.writerow(row)
    print(f"Saved CSV to: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Scrape sponsored ads from Dogpile.com")
    parser.add_argument("query", help="Search term to look up")
    parser.add_argument("--sc", default=DEFAULT_SC, help=f"Dogpile sc parameter (default: {DEFAULT_SC})")
    parser.add_argument("--output", help="Output file path (.json or .csv)")
    parser.add_argument("--show-browser", action="store_true", help="Run with a visible browser window")
    parser.add_argument("--cf-timeout", type=int, default=30, help="Seconds to wait for Cloudflare bypass (default: 30)")
    args = parser.parse_args()

    ad_htmls = fetch_ad_html(args.query, headless=not args.show_browser, cf_timeout=args.cf_timeout)

    if not ad_htmls:
        print("No ad content found.")
        sys.exit(1)

    ads = parse_all_ads(ad_htmls)
    print_ads(ads, args.query)

    if args.output:
        if args.output.endswith(".csv"):
            save_csv(ads, args.output)
        else:
            save_json(ads, args.query, args.output)


if __name__ == "__main__":
    main()
