# P2P MONITOR

**P2P MONITOR** is a prototype decision-support service for monitoring **Bybit P2P RUB/USDT** offers. It continuously searches for suitable orders, applies merchant-quality and implemented user search filters, compares prices with an external USD/RUB reference, and notifies the user when a configured target is reached.

The service also accumulates historical market data in PostgreSQL and uses it to study merchant behavior and market conditions over time.

This repository contains the full source code of the service together with product demos, anonymized historical analysis, and QA documentation.

> Experimental decision-support project. It does not execute trades or provide financial advice.

## Problem

Attractive P2P offers can appear and disappear quickly, so finding one manually may require constantly refreshing the market throughout the day.

At the same time, the cheapest available ad is not automatically the best choice. A useful order also has to satisfy merchant-quality rules, amount and payment constraints, and the configured target-profit condition relative to an external FX benchmark.

P2P NOOB automates this routine by continuously monitoring the market and notifying the user when a suitable opportunity appears.

## Demo

### Live monitoring

The web interface starts continuous monitoring, locks the active search parameters, tracks elapsed time, and displays the latest matching qualified order.

![Live monitoring demo](demos/web_monitor_demo.gif)

### Telegram alert

When a qualified order reaches the configured target, the monitor sends a Telegram notification with the order details and calculated edge.

<p align="center">
  <img src="demos/telegram_alert_demo.gif" alt="Telegram alert demo" width="380">
</p>

> Merchant names, order IDs, and merchant-specific links shown in the public demos are anonymized.

## Historical database & analysis

The PostgreSQL collector accumulated a real multi-day history containing:

- **2,376 snapshots**;
- **581,962 stored market-order rows**;
- **887 distinct merchants**.

The collected history is used to examine market behavior over time, compare listed prices with an external reference, study individual merchant activity, and evaluate filtering decisions on real historical data.

![Historical P2P market vs reference](analysis/charts/market_price_vs_reference.png)

![Merchant price history](analysis/charts/merchant_price_history.png)

See [`analysis/README.md`](analysis/README.md) for the full historical analysis, anonymized data exports, integrity checks, and methodology.

## QA

The project has gone through structured QA covering smoke, functional, negative, exploratory, endurance, research, retest, and targeted regression testing.

Input-validation and UI issues found during testing were fixed and retested.

One major issue remains open: a rare historical collection cycle had a roughly 12-hour recorded wall-clock interval, included a Bybit timeout, and later saved the delayed snapshot. The cause and location of the delay remain unconfirmed. The issue was not reliably reproduced by manual network-loss experiments; its evidence and reproduction history are documented in the QA bug report.

See [`qa/README.md`](qa/README.md) for the testing approach, results, and current defect status.

## Running locally

Requirements: Python 3.10+, PostgreSQL (only for the historical collector), a [Twelve Data](https://twelvedata.com/) API key, and a Telegram bot.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Credentials are not stored in the repository. Each one is read from a plain-text file on the user's Desktop (`~/Desktop`):

| File | Used by | Content |
|---|---|---|
| `twelve_data_api_key.txt` | `reference.py` | Twelve Data API key |
| `telegram_bot_token.txt` | `telegram_bot.py` | Telegram bot token |
| `telegram_chat_id.txt` | `telegram_bot.py` | Telegram chat ID for alerts |
| `postgreSQL_password.txt` | `database.py` | password of the `postgres` user |

**Live monitor + web interface**

```bash
python web_app.py
```

Then open <http://127.0.0.1:5000>, set the search conditions and press `START`.

**Historical collector (PostgreSQL)**

Create a database named `p2p_monitor` on `localhost:5432`, apply the schema, and start the collector:

```bash
psql -U postgres -d p2p_monitor -f schema.sql
python v2_runner.py
```

Logs are written to `logs/`, and the USD/RUB reference cache to `data/`; both folders are git-ignored.

## Code overview

| File | Purpose |
|---|---|
| `web_app.py` | Flask web interface; starts and stops the live monitor |
| `v1_runner.py` | live monitor: merchant-quality filters, edge calculation, Telegram alerts |
| `v2_runner.py` | historical collector: saves full market snapshots every 60 seconds |
| `bybit.py` | Bybit P2P API requests and order normalization |
| `collector.py` | collection of a full market snapshot |
| `reference.py` | USD/RUB reference rate from Twelve Data, with local cache |
| `database.py` | PostgreSQL access layer |
| `telegram_bot.py` | Telegram notifications |
| `schema.sql` | database schema |
| `templates/`, `static/` | web interface template and styles |

## Repository contents

```text
.
├── README.md
├── requirements.txt
├── schema.sql
├── web_app.py
├── v1_runner.py
├── v2_runner.py
├── bybit.py
├── collector.py
├── database.py
├── reference.py
├── telegram_bot.py
├── demos/
│   ├── web_monitor_demo.gif
│   └── telegram_alert_demo.gif
├── analysis/
│   ├── README.md
│   ├── charts/
│   └── data/
├── qa/
│   ├── README.md
│   ├── test_plan.md
│   ├── bug_report.md
│   ├── test_results.md
│   └── evidence/
│       └── long_collection_cycle_terminal.jpg
├── templates/
│   └── index.html
└── static/
    └── style.css
```

Credentials and the full historical dataset are not included; the `analysis/data/` folder contains anonymized exports only.
