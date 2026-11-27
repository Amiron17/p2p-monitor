import json
import os
import time
import requests

from datetime import datetime, timezone
from pathlib import Path


API_KEY_FILE = Path.home() / 'Desktop' / 'twelve_data_api_key.txt'
DATA_DIR = Path(__file__).resolve().parent / 'data'
DATA_DIR.mkdir(exist_ok=True)
CACHE_FILE = DATA_DIR / 'usd_rub_reference_cache.json'

UPDATE_INTERVAL_SECONDS = 120


def get_usd_rub_reference() -> dict:
    if not CACHE_FILE.exists():
        raise RuntimeError('USD/RUB reference cache does not exist. Run reference.py first.')

    with open(CACHE_FILE, 'r', encoding='utf-8') as file:
        cached = json.load(file)

    return {
        'rate': float(cached['rate']),
        'quote_timestamp': datetime.fromisoformat(
            cached['quote_timestamp']
        ),
        'fetched_at': datetime.fromisoformat(
            cached['fetched_at']
        ),
    }


def fetch_usd_rub_reference() -> dict:
    with open(API_KEY_FILE, 'r', encoding='utf-8') as file:
        api_key = file.read().strip()

    try:
        response = requests.get(
            'https://api.twelvedata.com/exchange_rate',
            params={
                'symbol': 'USD/RUB',
                'apikey': api_key,
            },
            timeout=15,
        )
    except requests.RequestException as error:
        raise RuntimeError(f'Twelve Data request failed: {type(error).__name__}') from None

    if not response.ok:
        raise RuntimeError(f'Twelve Data HTTP {response.status_code}')

    data = response.json()
    rate = float(data['rate'])
    quote_timestamp = datetime.fromtimestamp(int(data['timestamp']), tz=timezone.utc)
    fetched_at = datetime.now(timezone.utc)

    return {
        'rate': rate,
        'quote_timestamp': quote_timestamp,
        'fetched_at': fetched_at,
    }


def save_usd_rub_reference(reference: dict) -> None:
    cache_data = {
        'rate': reference['rate'],
        'quote_timestamp': reference['quote_timestamp'].isoformat(),
        'fetched_at': reference['fetched_at'].isoformat(),
    }

    temporary_cache_file = CACHE_FILE.with_name(f'{CACHE_FILE.name}.{os.getpid()}.tmp')

    with open(temporary_cache_file, 'w', encoding='utf-8') as file:
        json.dump(cache_data, file, indent=2)

    os.replace(temporary_cache_file, CACHE_FILE)


def update_reference_once() -> None:
    reference = fetch_usd_rub_reference()
    save_usd_rub_reference(reference)

    print(
        'REFERENCE UPDATED | '
        f'USD/RUB={reference["rate"]:.5f} | '
        f'quote_time={reference["quote_timestamp"].isoformat()} | '
        f'fetched_at={reference["fetched_at"].isoformat()}'
    )


def run_reference_updater() -> None:
    while True:
        try:
            update_reference_once()
        except Exception as error:
            print(f'REFERENCE UPDATE ERROR | {type(error).__name__}: {error}')

        time.sleep(UPDATE_INTERVAL_SECONDS)


if __name__ == '__main__':
    run_reference_updater()
