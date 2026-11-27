import logging
import threading
import time

from flask import Flask, jsonify, render_template, request

from v1_runner import run_v1_monitor
from telegram_bot import send_telegram_message


app = Flask(__name__)
logging.getLogger('werkzeug').setLevel(logging.ERROR)


monitor_thread = None
monitor_stop_event = None
monitor_started_at = None
monitor_latest = None
monitor_settings = None


def update_monitor_latest(result):
    global monitor_latest
    monitor_latest = result


def get_monitor_running():
    return monitor_thread is not None and monitor_thread.is_alive()


def get_monitor_stopping():
    return (
        get_monitor_running()
        and monitor_stop_event is not None
        and monitor_stop_event.is_set()
    )


@app.route('/monitor-status')
def monitor_status():
    running = get_monitor_running()
    stopping = get_monitor_stopping()

    elapsed_seconds = 0

    if running and monitor_started_at is not None:
        elapsed_seconds = int(
            time.time() - monitor_started_at
        )

    if monitor_latest is None:
        latest = None
    else:
        order = monitor_latest['best_order']
        reference = monitor_latest['reference']

        latest = {
            'merchant': order['merchant'],
            'price': order['price'],
            'reference_rate': reference['rate'],
            'edge': monitor_latest['edge'],
            'target_profit': monitor_latest['desired_edge'],
            'target_met': monitor_latest['status'] == 'MATCH',
            'min_amount': order['min_amount'],
            'max_amount': order['max_amount'],
            'recent_order_num': order['recent_order_num'],
            'recent_execute_rate': order['recent_execute_rate'],
            'merchant_url': monitor_latest['merchant_url'],
        }

    return jsonify(
        running=running,
        stopping=stopping,
        elapsed_seconds=elapsed_seconds,
        latest=latest,
    )


@app.route('/', methods=['GET', 'POST'])
def index():
    global monitor_thread
    global monitor_stop_event
    global monitor_started_at
    global monitor_latest
    global monitor_settings

    if monitor_thread is not None and not monitor_thread.is_alive():
        monitor_thread = None
        monitor_stop_event = None
        monitor_started_at = None
        monitor_latest = None
        monitor_settings = None

    amount = ''
    payment_method = ''
    target_profit = None

    user_profile = {
        'kyc_country': None,
        'orders_30d': None,
        'account_age_days': None,
        'completion_rate_30d': None,
    }

    monitor_running = get_monitor_running()
    monitor_stopping = get_monitor_stopping()

    if monitor_running and monitor_settings is not None:
        amount = monitor_settings['amount']
        payment_method = monitor_settings['payment_method']
        target_profit = monitor_settings['target_profit']
        user_profile = monitor_settings['user_profile'].copy()

    error = None
    notice = None

    monitor_elapsed_seconds = 0

    if monitor_running and monitor_started_at is not None:
        monitor_elapsed_seconds = int(
            time.time() - monitor_started_at
        )

    if request.method == 'POST':
        search_action = request.form.get('search_action', 'start_monitor')

        if search_action == 'stop_monitor':
            if monitor_running and monitor_stop_event is not None:
                monitor_stop_event.set()
                monitor_stopping = True
                notice = 'STOPPING MONITORING...'
            else:
                notice = 'MONITORING IS NOT RUNNING'

        else:
            amount = request.form.get('amount', '').strip()
            payment_method = request.form.get('payment_method', '').strip()

            kyc_country = request.form.get('kyc_country', '').strip()
            orders_30d_text = request.form.get('orders_30d', '').strip()
            target_profit_text = request.form.get('target_profit', '').strip()

            if amount:
                try:
                    amount_number = float(amount)
                except ValueError:
                    error = 'amount must be a number'
                else:
                    if amount_number <= 0:
                        error = 'amount must be greater than 0'

            if orders_30d_text:
                orders_30d = int(orders_30d_text)
            else:
                orders_30d = None

            if target_profit_text:
                if target_profit_text.startswith('+'):
                    target_profit = None
                    error = 'target profit must not start with +'
                else:
                    try:
                        target_profit = float(target_profit_text)
                    except ValueError:
                        target_profit = None
                        error = 'target profit must be a number'
                    else:
                        if target_profit == 0:
                            target_profit = 0.0
            else:
                target_profit = None

            user_profile = {
                'kyc_country': kyc_country or None,
                'orders_30d': orders_30d,
                'account_age_days': None,
                'completion_rate_30d': None,
            }

            if error is None and target_profit is None:
                error = 'target profit is required for monitoring'

            elif error is None and monitor_running:
                notice = 'MONITORING IS ALREADY RUNNING'

            elif error is None:
                monitor_latest = None
                monitor_stop_event = threading.Event()

                monitor_settings = {
                    'amount': amount,
                    'payment_method': payment_method,
                    'target_profit': target_profit,
                    'user_profile': user_profile.copy(),
                }

                monitor_thread = threading.Thread(
                    target=run_v1_monitor,
                    kwargs={
                        'user_amount': amount,
                        'payment_method': payment_method,
                        'user_profile': user_profile.copy(),
                        'desired_edge': target_profit,
                        'stop_event': monitor_stop_event,
                        'on_update': update_monitor_latest,
                    },
                    daemon=True,
                )

                monitor_thread.start()

                monitor_started_at = time.time()
                monitor_running = True
                monitor_stopping = False
                monitor_elapsed_seconds = 0

                send_telegram_message('monitoring started...')

                notice = 'MONITORING STARTED'

    return render_template(
        'index.html',
        amount=amount,
        payment_method=payment_method,
        target_profit=target_profit,
        user_profile=user_profile,
        monitor_running=monitor_running,
        monitor_stopping=monitor_stopping,
        monitor_elapsed_seconds=monitor_elapsed_seconds,
        error=error,
        notice=notice,
    )


app.run(
    debug=True,
    use_reloader=False,
)
