"""Classify cached Google Maps business locations by actual detail-page category.

Read-only toward Google's map. Evidence is checkpointed after each observation.
If Google blocks or challenges, stop and preserve unresolved places explicitly.
No guessed categories, absent-result inference, or replacement of original URLs.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from finder.common import HumanVerificationRequired
from research.finalize_full_google_498 import clinical_title_classification

CHALLENGE_MARKERS = (
    'unusual traffic', 'verify you are human', 'verify that you are a human',
    'are you a robot', 'recaptcha', 'too many requests', 'access denied',
    'request blocked',
)


def category_from_google_page(page):
    """Google Maps displays a primary category in the business-detail header."""
    details = page.locator('button.DkEaL')
    if details.count() > 0:
        text = details.first.inner_text(timeout=5000).strip()
        if text and len(text) <= 150:
            return text
    return None


def enrich(document_path: Path, max_seconds: int = 2900) -> dict:
    document = json.loads(document_path.read_text())
    if not isinstance(document.get('local_places'), list):
        raise RuntimeError('Missing actual Google Maps location evidence')
    places = document['local_places']
    if len(places) != int(document.get('unique_observed_local_places') or 0):
        raise RuntimeError('Location list does not agree with checkpoint count')
    if len({p['key'] for p in places}) != len(places):
        raise RuntimeError('Duplicate place IDs in source checkpoint')

    started = time.monotonic()
    checked = 0
    restricted = False
    failures = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1400, 'height': 960}, locale='en-CA')
        try:
            for place in places:
                if clinical_title_classification(place) != 'ambiguous':
                    continue
                if place.get('google_category_checked_at'):
                    continue
                if time.monotonic() - started > max_seconds:
                    break
                url = place.get('source_url')
                if not isinstance(url, str) or 'google.com/maps/place/' not in url:
                    failures.append(place.get('key'))
                    continue
                page = ctx.new_page()
                try:
                    response = page.goto(url, wait_until='domcontentloaded', timeout=35000)
                    if response and response.status in (403, 429):
                        restricted = True
                        place['google_category_error'] = 'Google HTTP ' + str(response.status)
                        break
                    page.wait_for_timeout(750)
                    body = page.locator('body').inner_text(timeout=10000).lower()
                    if any(marker in body for marker in CHALLENGE_MARKERS):
                        restricted = True
                        place['google_category_error'] = 'Google verification required'
                        break
                    category = category_from_google_page(page)
                    verified_page = ('google.com/maps/place/' in page.url
                                     and page.url.startswith('https://'))
                    if category and verified_page:
                        place['google_category_checked_at'] = datetime.now(timezone.utc).isoformat()
                        place['google_business_category'] = category
                        place['google_category_evidence_url'] = page.url
                        place.pop('google_category_error', None)
                    else:
                        place['google_category_error'] = (
                            'Google detail page missing primary category or redirected to another page')
                        # Leave checked_at unset, so a later healthy Google
                        # session can retry the same uncertain business.
                    checked += 1
                except Exception as exc:
                    failures.append(place.get('key'))
                    place['google_category_error'] = type(exc).__name__ + ': ' + str(exc)[:220]
                finally:
                    page.close()
                    document_path.write_text(json.dumps(document, indent=2))
                if restricted:
                    break
        finally:
            ctx.close()
            browser.close()

    unresolved = [p for p in places if clinical_title_classification(p) == 'ambiguous']
    report = {
        'fsa': document['fsa'],
        'source_status': document['status'],
        'new_category_pages_checked': checked,
        'total_source_locations': len(places),
        'clinical_places_verified_by_title_or_category':
            sum(clinical_title_classification(p) == 'clinical' for p in places),
        'nonclinical_places_verified_by_title_or_category':
            sum(clinical_title_classification(p) == 'nonclinical' for p in places),
        'ambiguous_places_remaining': len(unresolved),
        'google_access_restricted': restricted,
        'failed_category_pages': len(failures),
    }
    document['category_enrichment_report'] = report
    document_path.write_text(json.dumps(document, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('--seconds', type=int, default=2900)
    args = parser.parse_args()
    if not args.checkpoint.is_file():
        parser.error('Original Google Maps source checkpoint is missing')
    if not 1 <= args.seconds <= 3000:
        parser.error('Invalid bounded category recovery timeout')
    report = enrich(args.checkpoint, args.seconds)
    print('GOOGLE_DETAILS_CATEGORY_AUDIT', json.dumps(report), flush=True)
    if report['google_access_restricted']:
        raise SystemExit('Google challenge or access restriction; categorization checkpoint preserved')
    if report['ambiguous_places_remaining']:
        raise SystemExit('Unknown Google business categories remain; original evidence preserved')


if __name__ == '__main__':
    main()
