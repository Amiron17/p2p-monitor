import time
from datetime import datetime, timezone

from bybit import fetch_orders, normalize_orders


def collect_market_snapshot(return_diagnostics: bool = False):
    total_started_at = time.perf_counter()
    url = 'https://www.bybit.com/x-api/fiat/otc/item/online'

    page = 1
    page_size = 100

    items_by_id = {}
    source_by_id = {}
    raw_order_count = 0
    page_diagnostics = []

    collection_started_at = datetime.now(timezone.utc)

    while True:
        payload = {
            'amount': '',
            'authMaker': True,
            'bulkMaker': False,
            'canTrade': True,
            'countryCode': '',
            'currencyId': 'RUB',
            'itemRegion': 1,
            'page': str(page),
            'payment': [],
            'paymentPeriod': [],
            'side': '1',
            'size': str(page_size),
            'sortStrategyCode': 'DEFAULT_SELL',
            'sortType': 'OVERALL_RANKING',
            'tokenId': 'USDT',
            'tradeWith': False,
            'userId': '',
            'vaMaker': False,
            'verificationFilter': 0,
        }

        items, fetch_diagnostics = fetch_orders(url, payload, return_diagnostics=True)
        raw_order_count += len(items)
        page_diagnostics.append(fetch_diagnostics)

        print(f'Page {page}: {len(items)} orders')

        if not items:
            break

        for position, item in enumerate(items, start=1):
            order_id = item['id']

            if order_id in items_by_id:
                continue

            items_by_id[order_id] = item
            source_by_id[order_id] = {
                'source_page': page,
                'source_position': position,
            }

        if len(items) < page_size:
            break

        page += 1

    collection_finished_at = datetime.now(timezone.utc)

    unique_order_count = len(items_by_id)
    duplicate_count = raw_order_count - unique_order_count
    all_items = list(items_by_id.values())

    normalize_started_at = time.perf_counter()
    orders = normalize_orders(all_items)
    normalize_time = time.perf_counter() - normalize_started_at

    for order in orders:
        source = source_by_id[order['order_id']]
        order['source_page'] = source['source_page']
        order['source_position'] = source['source_position']

    diagnostics = {
        'total_time': time.perf_counter() - total_started_at,
        'collection_duration_seconds': (collection_finished_at - collection_started_at).total_seconds(),
        'pages': len(page_diagnostics),
        'page_diagnostics': page_diagnostics,
        'raw_orders': raw_order_count,
        'unique_orders': unique_order_count,
        'duplicates': duplicate_count,
        'normalize_time': normalize_time,
    }

    if return_diagnostics:
        return orders, collection_started_at, collection_finished_at, diagnostics

    return orders, collection_started_at, collection_finished_at
