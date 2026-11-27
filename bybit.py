import threading
import time
import requests


_thread_local = threading.local()


PAYMENT_METHODS = {
    'mobile_top_up': '40',
    'cash_in_person': '90',
    'bank_transfer': '14',
    'cash_deposit_to_bank': '18',
    'pay_api': '784',
    'neopass_qr_payments_api': '824',
    'qr_pay_api': '825',
}


def get_orders(amount: str = '', payment_method: str = '', user_profile: dict | None = None, min_orders: int = 0, min_completion_rate: float = 0, return_diagnostics: bool = False):
    total_started_at = time.perf_counter()
    url = 'https://www.bybit.com/x-api/fiat/otc/item/online'

    if user_profile is None:
        user_profile = {}

    if payment_method:
        payment = [PAYMENT_METHODS[payment_method]]
    else:
        payment = []

    payload = {
        'amount': amount,
        'authMaker': True,
        'bulkMaker': False,
        'canTrade': True,
        'countryCode': '',
        'currencyId': 'RUB',
        'itemRegion': 1,
        'page': '1',
        'payment': payment,
        'paymentPeriod': [],
        'side': '1',
        'size': '100',
        'sortStrategyCode': 'DEFAULT_SELL',
        'sortType': 'OVERALL_RANKING',
        'tokenId': 'USDT',
        'tradeWith': False,
        'userId': '',
        'vaMaker': False,
        'verificationFilter': 0,
    }

    items, fetch_diagnostics = fetch_orders(url, payload, return_diagnostics=True)

    normalize_started_at = time.perf_counter()
    orders = normalize_orders(items)
    normalize_time = time.perf_counter() - normalize_started_at

    filter_started_at = time.perf_counter()
    qualified_orders = filter_orders(orders, min_orders=min_orders, min_completion_rate=min_completion_rate)
    filter_time = time.perf_counter() - filter_started_at

    compatibility_started_at = time.perf_counter()
    compatible_orders = filter_user_compatible_orders(qualified_orders, user_profile)
    compatibility_time = time.perf_counter() - compatibility_started_at

    sort_started_at = time.perf_counter()
    compatible_orders = sorted(compatible_orders, key=lambda order: order['price'])
    sort_time = time.perf_counter() - sort_started_at

    diagnostics = {
        'total_time': time.perf_counter() - total_started_at,
        'fetch': fetch_diagnostics,
        'normalize_time': normalize_time,
        'filter_time': filter_time,
        'compatibility_time': compatibility_time,
        'sort_time': sort_time,
        'raw_orders': len(items),
        'normalized_orders': len(orders),
        'qualified_orders': len(qualified_orders),
        'compatible_orders': len(compatible_orders),
    }

    if not compatible_orders:
        error = ValueError(
            'No compatible orders found | '
            f'raw={len(items)} | qualified={len(qualified_orders)} | compatible=0'
        )
        error.diagnostics = diagnostics
        raise error

    if return_diagnostics:
        return compatible_orders, diagnostics

    return compatible_orders


def normalize_orders(items: list[dict]) -> list[dict]:
    orders = []

    for item in items:
        order = {
            'order_id': item['id'],
            'merchant_id': item['userMaskId'],
            'merchant': item['nickName'],
            'price': float(item['price']),
            'min_amount': float(item['minAmount']),
            'max_amount': float(item['maxAmount']),
            'recent_order_num': int(item['recentOrderNum']),
            'recent_execute_rate': float(item['recentExecuteRate']),
            'created_at': int(item['createDate']),
            'payment_period': int(item['paymentPeriod']),
            'payments': item['payments'],
            'last_quantity': float(item['lastQuantity']),
            'quantity': float(item['quantity']),
            'frozen_quantity': float(item['frozenQuantity']),
            'executed_quantity': float(item['executedQuantity']),
            'latest_release_time': int(item['latestReleaseTime']),
            'latest_pay_time': int(item['latestPayTime']),
            'remark': item['remark'],
            'verification_required': bool(item['verificationOrderSwitch']),
            'verification_amount': float(item['verificationOrderAmount']),
            'verification_labels': item['verificationOrderLabels'],
            'trading_preferences': item['tradingPreferenceSet'],
        }

        orders.append(order)

    return orders


def filter_orders(orders: list[dict], min_orders: int = 0, min_completion_rate: float = 0) -> list[dict]:
    suitable_orders = []

    for order in orders:
        if order['recent_order_num'] >= min_orders and order['recent_execute_rate'] >= min_completion_rate:
            suitable_orders.append(order)

    return suitable_orders


def filter_user_compatible_orders(orders: list[dict], user_profile: dict | None = None) -> list[dict]:
    if user_profile is None:
        user_profile = {}

    compatible_orders = []

    kyc_country = user_profile.get('kyc_country')
    if kyc_country:
        kyc_country = kyc_country.strip().upper()
    else:
        kyc_country = None

    orders_30d = user_profile.get('orders_30d')
    account_age_days = user_profile.get('account_age_days')
    completion_rate_30d = user_profile.get('completion_rate_30d')

    for order in orders:
        preferences = order['trading_preferences']

        if preferences.get('hasNationalLimit') == 1 and kyc_country is not None:
            allowed_countries = {
                country.strip().upper()
                for country in preferences.get('nationalLimit', '').split(',')
                if country.strip()
            }

            if kyc_country not in allowed_countries:
                continue

        if preferences.get('hasOrderFinishNumberDay30') == 1 and orders_30d is not None:
            required_orders_30d = int(preferences.get('orderFinishNumberDay30', 0))

            if orders_30d < required_orders_30d:
                continue

        if preferences.get('hasRegisterTime') == 1 and account_age_days is not None:
            required_account_age = int(preferences.get('registerTimeThreshold', 0))

            if account_age_days < required_account_age:
                continue

        if preferences.get('hasCompleteRateDay30') == 1 and completion_rate_30d is not None:
            required_completion_rate = float(preferences.get('completeRateDay30', 0))

            if completion_rate_30d < required_completion_rate:
                continue

        compatible_orders.append(order)

    return compatible_orders


def get_session():
    if not hasattr(_thread_local, 'session'):
        _thread_local.session = requests.Session()

    return _thread_local.session


def fetch_orders(url: str, payload: dict, return_diagnostics: bool = False):
    max_attempts = 3
    total_started_at = time.perf_counter()
    attempt_times = []
    retry_errors = []
    retry_sleep_seconds = 0
    response = None

    for attempt in range(1, max_attempts + 1):
        attempt_started_at = time.perf_counter()

        try:
            response = get_session().post(url, json=payload, timeout=15)
            attempt_times.append(time.perf_counter() - attempt_started_at)
            break

        except (requests.Timeout, requests.ConnectionError) as error:
            attempt_time = time.perf_counter() - attempt_started_at
            attempt_times.append(attempt_time)
            retry_errors.append(f'{type(error).__name__}: {error}')

            print(f'Bybit request failed, attempt {attempt}/{max_attempts}: {error}')

            if attempt == max_attempts:
                raise

            time.sleep(attempt)
            retry_sleep_seconds += attempt

    response.raise_for_status()

    json_started_at = time.perf_counter()
    data = response.json()
    json_time = time.perf_counter() - json_started_at

    if data['result'] is None:
        raise RuntimeError(f'Bybit returned an error: {data}')

    items = data['result']['items']

    diagnostics = {
        'total_time': time.perf_counter() - total_started_at,
        'attempts': len(attempt_times),
        'attempt_times': attempt_times,
        'retry_errors': retry_errors,
        'retry_sleep_seconds': retry_sleep_seconds,
        'status_code': response.status_code,
        'response_elapsed': response.elapsed.total_seconds(),
        'json_time': json_time,
        'item_count': len(items),
        'page': payload.get('page'),
        'amount': payload.get('amount'),
        'size': payload.get('size'),
    }

    if return_diagnostics:
        return items, diagnostics

    return items
