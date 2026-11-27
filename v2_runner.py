import os
import time
import traceback
from datetime import datetime
from pathlib import Path

from collector import collect_market_snapshot
from database import save_market_snapshot
from reference import get_usd_rub_reference


interval_seconds = 60

PROJECT_DIR = Path(__file__).resolve().parent
LOG_DIR = PROJECT_DIR / 'logs'
LOG_DIR.mkdir(exist_ok=True)
V2_LOG_FILE = LOG_DIR / 'v2.log'


def write_v2_log(event, message=''):
    timestamp = datetime.now().astimezone().isoformat(timespec='milliseconds')

    with open(V2_LOG_FILE, 'a', encoding='utf-8') as file:
        file.write(f'{timestamp} | {event} | {message}\n')


def write_v2_exception(event, exception, message=''):
    summary = f'{type(exception).__name__}: {exception}'

    if message:
        summary = f'{message} | {summary}'

    write_v2_log(event, summary)

    traceback_text = ''.join(
        traceback.format_exception(type(exception), exception, exception.__traceback__)
    ).rstrip()

    for line in traceback_text.splitlines():
        write_v2_log('TRACE', line)


write_v2_log('V2_START', f'pid={os.getpid()} interval={interval_seconds}s')

cycle_number = 0
previous_cycle_started_at = None
stop_reason = 'keyboard_interrupt'
try:
    while True:
        cycle_number += 1
        cycle_started_at = time.monotonic()
        local_started_at = datetime.now().astimezone()

        if previous_cycle_started_at is None:
            start_interval = 0.0
        else:
            start_interval = cycle_started_at - previous_cycle_started_at

        previous_cycle_started_at = cycle_started_at

        print()
        print(f'[{local_started_at:%H:%M:%S}] COLLECTION STARTED')

        reference = None
        orders = None
        collection_started_at = None
        collection_finished_at = None
        collector_diagnostics = None
        cycle_failed = False

        try:
            reference = get_usd_rub_reference()
        except Exception as exception:
            cycle_failed = True
            write_v2_exception('REFERENCE_ERROR', exception, f'cycle={cycle_number}')

        if not cycle_failed:
            try:
                (
                    orders,
                    collection_started_at,
                    collection_finished_at,
                    collector_diagnostics,
                ) = collect_market_snapshot(True)
            except Exception as exception:
                cycle_failed = True
                write_v2_exception(
                    'COLLECTOR_ERROR',
                    exception,
                    f'cycle={cycle_number}',
                )

        if not cycle_failed:
            try:
                snapshot_id, database_diagnostics = save_market_snapshot(
                    orders=orders,
                    token_id='USDT',
                    currency_id='RUB',
                    side='1',
                    collection_started_at=collection_started_at,
                    collection_finished_at=collection_finished_at,
                    reference_rate=reference['rate'],
                    reference_quote_timestamp=reference['quote_timestamp'],
                    reference_fetched_at=reference['fetched_at'],
                    return_diagnostics=True,
                )
                cycle_time = time.monotonic() - cycle_started_at

                for page_diagnostics in collector_diagnostics['page_diagnostics']:
                    if page_diagnostics['attempts'] > 1:
                        write_v2_log(
                            'BYBIT_RETRY',
                            f'cycle={cycle_number} page={page_diagnostics["page"]} '
                            f'attempts={page_diagnostics["attempts"]}',
                        )

                write_v2_log(
                    'SNAPSHOT_SAVED',
                    f'cycle={cycle_number} snapshot_id={snapshot_id} '
                    f'orders={len(orders)} pages={collector_diagnostics["pages"]} '
                    f'collection={collector_diagnostics["collection_duration_seconds"]:.3f}s '
                    f'reference_rate={reference["rate"]:.5f} '
                    f'quote_time={reference["quote_timestamp"].isoformat()} '
                    f'cycle_total={cycle_time:.3f}s',
                )

                print(f'SNAPSHOT SAVED: id={snapshot_id} | orders={len(orders)}')

            except Exception as exception:
                cycle_failed = True
                write_v2_exception('DATABASE_ERROR', exception, f'cycle={cycle_number} orders={len(orders)}')

        cycle_time = time.monotonic() - cycle_started_at
        sleep_seconds = max(0, interval_seconds - cycle_time)
        overrun_seconds = max(0, cycle_time - interval_seconds)

        if cycle_failed:
            write_v2_log(
                'CYCLE_FAILED',
                f'cycle={cycle_number} total={cycle_time:.3f}s',
            )

        if overrun_seconds > 0:
            write_v2_log(
                'CYCLE_OVERRUN',
                f'cycle={cycle_number} total={cycle_time:.3f}s '
                f'overrun={overrun_seconds:.3f}s',
            )

        print()
        time.sleep(sleep_seconds)

except KeyboardInterrupt:
    stop_reason = 'keyboard_interrupt'
    write_v2_log('V2_STOP_REQUEST', 'KeyboardInterrupt')

except Exception as exception:
    stop_reason = 'fatal_exception'
    write_v2_exception('V2_FATAL', exception)
    raise

finally:
    write_v2_log('V2_STOP', f'reason={stop_reason} cycles={cycle_number}')
