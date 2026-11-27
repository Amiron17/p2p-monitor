import os
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from bybit import get_orders
from reference import get_usd_rub_reference
from telegram_bot import send_telegram_message


MIN_ORDERS = 400
MIN_COMPLETION_RATE = 99

REQUEST_INTERVAL_SECONDS = 5
MAX_IN_FLIGHT = 3
HEARTBEAT_INTERVAL_SECONDS = 60
LOOP_STALL_THRESHOLD_SECONDS = 2

PROJECT_DIR = Path(__file__).resolve().parent
LOG_DIR = PROJECT_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
V1_LOG_FILE = LOG_DIR / 'v1.log'


def write_v1_log(event, message=''):
    timestamp = datetime.now().astimezone().isoformat(timespec='milliseconds')

    with open(V1_LOG_FILE, 'a', encoding='utf-8') as file:
        file.write(f'{timestamp} | {event} | {message}\n')


def write_v1_exception(event, exception, message=''):
    summary = f'{type(exception).__name__}: {exception}'

    if message:
        summary = f'{message} | {summary}'

    write_v1_log(event, summary)

    traceback_text = ''.join(
        traceback.format_exception(type(exception), exception, exception.__traceback__)
    ).rstrip()

    for line in traceback_text.splitlines():
        write_v1_log('TRACE', line)


def process_market_result(compatible_orders, desired_edge, sent_order_ids, monitor_started_at, request_id, request_diagnostics):
    try:
        reference = get_usd_rub_reference()
    except Exception as exception:
        write_v1_exception('REFERENCE_ERROR', exception, f'req={request_id}')
        return None

    best_order = compatible_orders[0]
    edge = (reference['rate'] - best_order['price']) / reference['rate'] * 100
    status = 'MATCH' if edge >= desired_edge else 'NO MATCH'

    merchant_url = 'https://www.bybit.com/ru-RU/p2p/profile/' f'{best_order["merchant_id"]}/USDT/RUB/item'
    new_match = False
    telegram_status = 'not_needed'
    telegram_time = 0.0

    if status == 'MATCH' and best_order['order_id'] not in sent_order_ids:
        bybit_deep_link = 'bybitapp://open/web?url=' + quote(merchant_url, safe='')
        app_url = 'https://app.bybit.com/inapp?by_dp=' + quote(bybit_deep_link, safe='') + '&by_web_link=' + quote(merchant_url, safe='')

        telegram_message = (
            f'new order found!\n\n'
            f'order id: {best_order["order_id"]}\n'
            f'limits: {best_order["min_amount"]:.0f}-{best_order["max_amount"]:.0f} RUB\n'
            f'price: {best_order["price"]:.2f} RUB\n'
            f'current usd/rub rate: {reference["rate"]:.5f}\n'
            f'profit: {edge:+.3f}%\n\n'
            f'merchant: {best_order["merchant"]}\n'
            f'- activity 30 days: {best_order["recent_order_num"]} orders\n'
            f'- completion rate: {best_order["recent_execute_rate"]}%\n\n'
            f'browser link: {merchant_url}\n'
            f'iphone app link: {app_url}'
        )

        telegram_started_at = time.perf_counter()

        try:
            send_telegram_message(telegram_message)
            telegram_time = time.perf_counter() - telegram_started_at
            sent_order_ids.add(best_order['order_id'])
            new_match = True
            telegram_status = 'sent'
        except Exception as exception:
            telegram_time = time.perf_counter() - telegram_started_at
            telegram_status = 'error'
            write_v1_exception(
                'TELEGRAM_ERROR',
                exception,
                f'req={request_id} order_id={best_order["order_id"]} elapsed={telegram_time:.3f}s',
            )

    elif status == 'MATCH':
        telegram_status = 'dedup'

    elapsed_seconds = time.monotonic() - monitor_started_at
    fetch_diagnostics = request_diagnostics['fetch']

    print(
        f'[{elapsed_seconds:.1f}s] {status}: {best_order["merchant"]} | '
        f'P2P={best_order["price"]:.2f} | '
        f'USD/RUB={reference["rate"]:.5f} | '
        f'quote={reference["quote_timestamp"].isoformat()} | '
        f'edge={edge:+.3f}% | '
        f'target={desired_edge:+.3f}%'
    )

    return {
        'best_order': best_order,
        'reference': reference,
        'edge': edge,
        'status': status,
        'desired_edge': desired_edge,
        'merchant_url': merchant_url,
        'new_match': new_match,
    }


def run_v1_monitor(user_amount, payment_method, user_profile, desired_edge, interval_seconds=REQUEST_INTERVAL_SECONDS, stop_event=None, on_update=None):
    sent_order_ids = set()
    pending_requests = {}

    next_request_id = 1
    latest_processed_request_id = 0
    monitor_started_at = time.monotonic()
    next_request_at = monitor_started_at
    last_heartbeat_at = monitor_started_at
    last_loop_at = monitor_started_at

    stats = {
        'launched': 0,
        'completed': 0,
        'succeeded': 0,
        'failed': 0,
        'processed': 0,
        'stale_dropped': 0,
        'telegram_sent': 0,
    }

    stop_reason = 'stop_event'

    write_v1_log(
        'V1_START',
        f'pid={os.getpid()} amount={user_amount} payment={payment_method!r} '
        f'kyc_country={user_profile.get("kyc_country")!r} user_orders_30d={user_profile.get("orders_30d")!r} '
        f'target={desired_edge:+.4f}% gate={MIN_ORDERS}/{MIN_COMPLETION_RATE} '
        f'interval={interval_seconds}s max_in_flight={MAX_IN_FLIGHT}',
    )

    try:
        with ThreadPoolExecutor(max_workers=MAX_IN_FLIGHT) as executor:
            while stop_event is None or not stop_event.is_set():
                now = time.monotonic()
                loop_gap = now - last_loop_at

                if loop_gap >= LOOP_STALL_THRESHOLD_SECONDS:
                    write_v1_log('LOOP_STALL', f'gap={loop_gap:.3f}s pending={len(pending_requests)}')

                last_loop_at = now

                if now >= next_request_at and len(pending_requests) < MAX_IN_FLIGHT:
                    request_id = next_request_id
                    schedule_delay = max(0.0, now - next_request_at)

                    future = executor.submit(
                        get_orders,
                        user_amount,
                        payment_method,
                        user_profile,
                        MIN_ORDERS,
                        MIN_COMPLETION_RATE,
                        True,
                    )

                    pending_requests[future] = {
                        'request_id': request_id,
                        'started_at': now,
                    }

                    stats['launched'] += 1
                    next_request_id += 1
                    next_request_at = now + interval_seconds

                completed = [future for future in pending_requests if future.done()]
                successful_results = []

                for future in completed:
                    request_meta = pending_requests.pop(future)
                    request_id = request_meta['request_id']
                    request_wall_time = time.monotonic() - request_meta['started_at']
                    stats['completed'] += 1

                    try:
                        compatible_orders, request_diagnostics = future.result()
                        stats['succeeded'] += 1

                        fetch_diagnostics = request_diagnostics['fetch']
                        attempt_times = ','.join(f'{value:.3f}' for value in fetch_diagnostics['attempt_times'])

                        if fetch_diagnostics['attempts'] > 1:
                            write_v1_log(
                                'BYBIT_RETRY',
                                f'req={request_id} attempts={fetch_diagnostics["attempts"]} '
                                f'attempt_times=[{attempt_times}] '
                                f'retry_sleep={fetch_diagnostics["retry_sleep_seconds"]}s',
                            )

                        successful_results.append((request_id, compatible_orders, request_diagnostics))

                    except Exception as exception:
                        stats['failed'] += 1
                        diagnostics = getattr(exception, 'diagnostics', None)

                        if isinstance(exception, ValueError) and str(exception).startswith('No compatible orders found'):
                            extra = f'req={request_id} wall={request_wall_time:.3f}s'

                            if diagnostics is not None:
                                extra += (
                                    f' raw={diagnostics["raw_orders"]}'
                                    f' qualified={diagnostics["qualified_orders"]}'
                                    f' compatible={diagnostics["compatible_orders"]}'
                                )

                            write_v1_log('NO_COMPATIBLE', f'{extra} | {exception}')
                        else:
                            write_v1_exception(
                                'REQUEST_ERROR',
                                exception,
                                f'req={request_id} wall={request_wall_time:.3f}s inflight={len(pending_requests)}',
                            )

                if successful_results:
                    freshest_request_id, compatible_orders, request_diagnostics = max(successful_results, key=lambda item: item[0])

                    for request_id, _, _ in successful_results:
                        if request_id != freshest_request_id:
                            stats['stale_dropped'] += 1
                            write_v1_log(
                                'STALE_DROP',
                                f'req={request_id} fresher_req={freshest_request_id} latest_processed={latest_processed_request_id}',
                            )

                    if freshest_request_id > latest_processed_request_id:
                        result = process_market_result(
                            compatible_orders,
                            desired_edge,
                            sent_order_ids,
                            monitor_started_at,
                            freshest_request_id,
                            request_diagnostics,
                        )

                        latest_processed_request_id = freshest_request_id

                        if result is not None:
                            stats['processed'] += 1

                            if result['new_match']:
                                stats['telegram_sent'] += 1

                            if on_update is not None and result['new_match']:
                                try:
                                    on_update(result)
                                except Exception as exception:
                                    write_v1_exception('CALLBACK_ERROR', exception, f'req={freshest_request_id}')

                now = time.monotonic()

                if now - last_heartbeat_at >= HEARTBEAT_INTERVAL_SECONDS:
                    oldest_pending_age = 0.0

                    if pending_requests:
                        oldest_pending_age = max(
                            now - request_meta['started_at']
                            for request_meta in pending_requests.values()
                        )

                    write_v1_log(
                        'HEARTBEAT',
                        f'uptime={now - monitor_started_at:.1f}s pending={len(pending_requests)} '
                        f'oldest_pending={oldest_pending_age:.1f}s latest_processed={latest_processed_request_id} '
                        f'launched={stats["launched"]} completed={stats["completed"]} '
                        f'succeeded={stats["succeeded"]} failed={stats["failed"]} '
                        f'processed={stats["processed"]} stale_dropped={stats["stale_dropped"]} '
                        f'telegram_sent={stats["telegram_sent"]}',
                    )

                    last_heartbeat_at = now

                if stop_event is None:
                    time.sleep(0.1)
                else:
                    stop_event.wait(0.1)

    except Exception as exception:
        stop_reason = 'fatal_exception'
        write_v1_exception('V1_FATAL', exception)
        raise

    finally:
        uptime = time.monotonic() - monitor_started_at
        write_v1_log(
            'V1_STOP',
            f'reason={stop_reason} uptime={uptime:.1f}s pending={len(pending_requests)} '
            f'launched={stats["launched"]} completed={stats["completed"]} '
            f'succeeded={stats["succeeded"]} failed={stats["failed"]} '
            f'processed={stats["processed"]} stale_dropped={stats["stale_dropped"]} '
            f'telegram_sent={stats["telegram_sent"]}',
        )
