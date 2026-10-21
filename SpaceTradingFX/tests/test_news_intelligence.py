"""Test AI News & Macro Intelligence Engine, Sentiment Scoring, and AI Veto Gate."""

import pytest
from flask_dashboard import create_app
from flask_dashboard.extensions import db
from flask_dashboard.models import Notification, Trade, TradingPreference, User
from flask_dashboard.services.news_intelligence import (
    CORE_TRADING_PAIRS,
    check_ai_veto,
    evaluate_macro_sentiment,
    get_macro_pulse,
)
from flask_dashboard.trading_engine import TradingEngine


@pytest.fixture
def app():
    test_app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            "BROKER_ENCRYPTION_KEY": "test-news-intelligence-broker-encryption-key-for-unit-tests",
        }
    )
    with test_app.app_context():
        db.create_all()
        yield test_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def macro_user_id(app):
    with app.app_context():
        user = User(
            id="test-macro-user",
            email="macro-trader@institutional.fx",
            first_name="Macro",
            last_name="Analyst",
            password_hash="argon2-hash",
        )
        db.session.add(user)

        from flask_dashboard.models import License

        lic = License(
            user_id="test-macro-user",
            license_key="TEST-MACRO-LICENSE-KEY",
            license_type="lifetime",
            status="active",
        )
        db.session.add(lic)

        prefs = TradingPreference(
            user_id="test-macro-user",
            currency_pairs=["XAUUSD", "USDJPY", "EURUSD", "GBPUSD", "USDZAR"],
            trading_enabled=True,
            direction_preferences={"XAUUSD": "BOTH", "USDJPY": "BOTH"},
            strategy_settings={"auto_pilot": True, "lot_sizes": {"XAUUSD": "0.01", "USDJPY": "0.01"}},
        )
        db.session.add(prefs)
        db.session.commit()
        return "test-macro-user"


def test_evaluate_macro_sentiment_all_core_pairs():
    """Verify macro sentiment evaluator computes valid scores, directions, and modifiers for all core pairs."""
    for symbol in CORE_TRADING_PAIRS:
        eval_res = evaluate_macro_sentiment(symbol, force_refresh=True)
        assert eval_res["symbol"] == symbol
        assert -1.0 <= eval_res["score"] <= 1.0
        assert eval_res["direction"] in {"BULLISH", "BEARISH", "NEUTRAL"}
        assert isinstance(eval_res["confidence_modifier"], int)
        assert len(eval_res["headline"]) > 10
        assert eval_res["impact"] in {"HIGH", "MEDIUM", "LOW"}
        assert isinstance(eval_res["keywords"], list)
        assert "timestamp" in eval_res


def test_ai_veto_gate_directional_rules():
    """Verify that AI Veto blocks trades that strictly contradict extreme macro sentiment."""
    # 1. Strong BEARISH macro sentiment (-0.60) vetoes BUY technical signal
    bearish_sentiment = {
        "score": -0.60,
        "direction": "BEARISH",
        "headline": "Fed Signals Emergency Rate Hike; Dollar Surges Across Major Pairs",
    }
    veto_active, veto_reason = check_ai_veto("EURUSD", "BUY", bearish_sentiment)
    assert veto_active is True
    assert "contradicted by strong BEARISH news" in veto_reason

    # 2. Strong BEARISH macro sentiment does NOT veto SELL technical signal
    veto_active_sell, _ = check_ai_veto("EURUSD", "SELL", bearish_sentiment)
    assert veto_active_sell is False

    # 3. Strong BULLISH macro sentiment (+0.70) vetoes SELL technical signal
    bullish_sentiment = {
        "score": 0.70,
        "direction": "BULLISH",
        "headline": "US Inflation Drops to 3-Year Low; Fed Doves Signal Aggressive Easing",
    }
    veto_active_sell, veto_reason_sell = check_ai_veto("XAUUSD", "SELL", bullish_sentiment)
    assert veto_active_sell is True
    assert "contradicted by strong BULLISH news" in veto_reason_sell

    # 4. Neutral macro sentiment (score 0.10) does NOT veto either direction
    neutral_sentiment = {
        "score": 0.10,
        "direction": "NEUTRAL",
        "headline": "Markets Consolidate in Quiet Session Ahead of Central Bank Meetings",
    }
    veto_buy, _ = check_ai_veto("USDJPY", "BUY", neutral_sentiment)
    veto_sell, _ = check_ai_veto("USDJPY", "SELL", neutral_sentiment)
    assert veto_buy is False
    assert veto_sell is False


def test_get_macro_pulse_aggregation():
    """Verify that get_macro_pulse returns aggregated institutional pulse across all 5 pairs."""
    pulse = get_macro_pulse()
    assert pulse["overall_direction"] in {"BULLISH", "BEARISH", "NEUTRAL"}
    assert -1.0 <= pulse["average_score"] <= 1.0
    assert len(pulse["top_headline"]) > 5
    assert pulse["top_impact"] in {"HIGH", "MEDIUM", "LOW"}
    assert len(pulse["pair_evaluations"]) == 5
    for sym in CORE_TRADING_PAIRS:
        assert sym in pulse["pair_evaluations"]


def test_trading_engine_ai_veto_blocks_auto_execution_and_alerts(app, macro_user_id):
    """Verify that when AI Veto is active, TradingEngine suppresses automated order and logs risk alert."""
    with app.app_context():
        engine = TradingEngine(macro_user_id)

        # Mock scanner that returns BUY with high technical confidence
        class MockVetoScanner:
            def analyze_signal(self, symbol, timeframe="1H", direction_preference="BOTH"):
                return {
                    "currency_pair": symbol,
                    "signal": "BUY",
                    "strength": 85,
                    "price": 2000.0,
                    "entry_price": 2000.0,
                    "stop_loss": 1980.0,
                    "take_profit": 2040.0,
                    "indicators": {
                        "rsi": 40.0,
                        "macro_sentiment": {
                            "score": -0.65,
                            "direction": "BEARISH",
                            "headline": "Massive Hawkish Shift Triggering Severe Precious Metals Selloff",
                            "veto_active": True,
                            "veto_reason": "Severe macro divergence",
                        },
                    },
                    "macro_sentiment": {
                        "score": -0.65,
                        "direction": "BEARISH",
                        "headline": "Massive Hawkish Shift Triggering Severe Precious Metals Selloff",
                        "veto_active": True,
                        "veto_reason": "Severe macro divergence",
                    },
                }

        engine.forex_provider = MockVetoScanner()

        # Run analyze_markets with submit_automatically=True
        signals = engine.analyze_markets(submit_automatically=True)
        assert len(signals) >= 1

        # Assert no trade was executed because AI Veto was triggered!
        open_trades = Trade.query.filter_by(user_id=macro_user_id, status="open").all()
        assert len(open_trades) == 0

        # Assert a high-priority risk alert notification was delivered
        alerts = Notification.query.filter_by(user_id=macro_user_id, type="risk").all()
        assert len(alerts) >= 1
        assert "AI VETO ACTIVE" in alerts[0].title


def test_mobile_home_and_history_macro_pulse_ui(client, macro_user_id):
    """Verify that /m/home and /m/history render the AI News & Macro Pulse banner."""
    with client.session_transaction() as sess:
        sess["_user_id"] = macro_user_id

    # 1. /m/home
    home_resp = client.get("/m/home")
    assert home_resp.status_code == 200
    assert b"AI NEWS &amp; MACRO PULSE" in home_resp.data or b"AI NEWS & MACRO PULSE" in home_resp.data

    # 2. /m/history
    history_resp = client.get("/m/history?tab=analysing")
    assert history_resp.status_code == 200
    assert b"AI NEWS &amp; MACRO PULSE" in history_resp.data or b"AI NEWS & MACRO PULSE" in history_resp.data
