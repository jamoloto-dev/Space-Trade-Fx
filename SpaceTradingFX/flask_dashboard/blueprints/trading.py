"""
Trading Blueprint
Handles trading operations, preferences, and API endpoints
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import current_user, login_required

trading_bp = Blueprint('trading', __name__)


def require_license(f):
    """Decorator to require a valid license for a route"""
    from functools import wraps
    from license_manager import check_license_valid
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            flash('Please log in to access this feature', 'warning')
            return redirect(url_for('auth.login'))
        
        is_valid, result = check_license_valid(current_user.id)
        if not is_valid:
            flash(f'Valid license required: {result}', 'error')
            return redirect(url_for('auth.buy_license'))
        
        return f(*args, **kwargs)
    
    return decorated_function


@trading_bp.route('/dashboard')
@login_required
@require_license
def dashboard():
    """Main trading dashboard"""
    from models import Trade, TradingSignal
    from trading_engine import TradingEngine
    from license_manager import check_license_valid
    
    is_valid, license_info = check_license_valid(current_user.id)
    engine = TradingEngine(current_user.id)
    account_summary = engine.get_account_summary()
    
    active_trades = Trade.query.filter_by(user_id=current_user.id, status='open').all()
    recent_signals = TradingSignal.query.order_by(TradingSignal.created_at.desc()).limit(10).all()
    
    return render_template(
        'dashboard.html',
        user=current_user,
        account_summary=account_summary,
        active_trades=active_trades,
        recent_signals=recent_signals,
        license=license_info if is_valid else None
    )


@trading_bp.route('/preferences', methods=['GET', 'POST'])
@login_required
@require_license
def preferences():
    """Trading preferences page"""
    from app import db
    from models import TradingPreference
    
    prefs = TradingPreference.query.filter_by(user_id=current_user.id).first()
    
    if not prefs:
        prefs = TradingPreference()  # type: ignore
        prefs.user_id = current_user.id
        db.session.add(prefs)
        db.session.commit()
    
    if request.method == 'POST':
        currency_pairs = request.form.getlist('currency_pairs')
        prefs.currency_pairs = currency_pairs
        prefs.timeframe = request.form.get('timeframe', '1H')
        prefs.risk_percentage = float(request.form.get('risk_percentage', 1.0))
        prefs.max_concurrent_trades = int(request.form.get('max_concurrent_trades', 3))
        prefs.trading_enabled = request.form.get('trading_enabled') == 'on'
        
        direction_prefs = {}
        for p in currency_pairs:
            val = request.form.get(f'direction_{p}', 'BOTH')
            if val not in ('BOTH', 'BUY', 'SELL'):
                val = 'BOTH'
            direction_prefs[p] = val
        prefs.direction_preferences = direction_prefs
        
        prefs.mt5_account = request.form.get('mt5_account') or prefs.mt5_account
        prefs.mt5_server = request.form.get('mt5_server') or prefs.mt5_server
        
        db.session.commit()
        flash('Trading preferences updated!', 'success')
        return redirect(url_for('trading.dashboard'))
    
    available_pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'NZDUSD']
    
    return render_template(
        'preferences.html',
        preferences=prefs,
        available_pairs=available_pairs
    )


@trading_bp.route('/analyze-markets')
@login_required
@require_license
def analyze_markets():
    """Analyze markets and generate signals"""
    from trading_engine import TradingEngine
    
    engine = TradingEngine(current_user.id)
    signals = engine.analyze_markets()
    
    flash(f'Analyzed {len(signals)} currency pairs', 'success')
    return redirect(url_for('mobile.home'))


@trading_bp.route('/manual-trade', methods=['POST'])
@login_required
@require_license
def manual_trade():
    """Execute a manual trade"""
    from trading_engine import TradingEngine
    from forex_data import get_forex_provider
    
    currency_pair = request.form.get('currency_pair')
    trade_type = request.form.get('trade_type')
    
    if not currency_pair or not trade_type:
        flash('Currency pair and trade type are required', 'error')
        return redirect(url_for('trading.dashboard'))
    
    engine = TradingEngine(current_user.id)
    forex_provider = get_forex_provider()
    signal_data = forex_provider.analyze_signal(currency_pair)
    
    trade = engine.execute_trade(currency_pair, trade_type, signal_data)
    
    if trade:
        flash(f'Trade opened: {currency_pair} {trade_type}', 'success')
    else:
        flash('Could not execute trade. Check your settings.', 'error')
    
    return redirect(url_for('mobile.home'))


@trading_bp.route('/close-trade/<int:trade_id>', methods=['POST'])
@login_required
@require_license
def close_trade(trade_id):
    """Close an open trade"""
    from app import db
    from models import Trade
    from trading_engine import TradingEngine
    
    trade = Trade.query.get_or_404(trade_id)
    
    if trade.user_id != current_user.id:
        flash('Unauthorized', 'error')
        return redirect(url_for('mobile.home'))
    
    if trade.status != 'open':
        flash('Trade is already closed', 'error')
        return redirect(url_for('mobile.home'))
    
    engine = TradingEngine(current_user.id)
    current_price = engine._get_current_price(trade.currency_pair)
    engine._close_trade(trade, current_price)
    db.session.commit()
    
    flash(f'Trade closed. P/L: ${trade.profit_loss:.2f}', 'success')
    return redirect(url_for('mobile.home'))


# =====================================================
# API ENDPOINTS
# =====================================================

@trading_bp.route('/api/account-summary')
@login_required
def api_account_summary():
    """Get account summary via API"""
    from trading_engine import TradingEngine
    
    engine = TradingEngine(current_user.id)
    summary = engine.get_account_summary()
    
    trades_data = [{
        'id': t.id,
        'currency_pair': t.currency_pair,
        'trade_type': t.trade_type,
        'entry_price': t.entry_price,
        'lot_size': t.lot_size,
        'profit_loss': t.profit_loss,
        'opened_at': t.opened_at.isoformat()
    } for t in summary['trades']]
    
    summary['trades'] = trades_data
    return jsonify(summary)


@trading_bp.route('/api/forex-data/<currency_pair>')
@login_required
def api_forex_data(currency_pair):
    """Get forex data for a currency pair"""
    from forex_data import get_forex_provider
    
    forex_provider = get_forex_provider()
    data = forex_provider.get_forex_intraday(currency_pair[:3], currency_pair[3:])
    return jsonify(data)


@trading_bp.route('/api/market-signal/<currency_pair>')
@login_required
def api_market_signal(currency_pair):
    """Get market signal for a currency pair"""
    from forex_data import get_forex_provider
    
    forex_provider = get_forex_provider()
    signal = forex_provider.analyze_signal(currency_pair)
    return jsonify(signal)


@trading_bp.route('/api/notifications/count')
@login_required
def api_notifications_count():
    """Get unread notifications count"""
    try:
        from notifications import get_unread_count
        count = get_unread_count(current_user.id)
    except Exception:
        count = 0
    return jsonify({'count': count})


@trading_bp.route('/api/notifications/test', methods=['POST'])
@login_required
def api_test_notification():
    """Create a test notification"""
    try:
        from notifications import create_notification
        notification = create_notification(
            user_id=current_user.id,
            title="Test Notification",
            message="This is a test notification from SpaceTradingFX",
            notification_type='system'
        )
        return jsonify({'success': True, 'id': notification.id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@trading_bp.route('/api/mt5/connect', methods=['POST'])
@login_required
@require_license
def api_mt5_connect():
    """Connect to MT5 account"""
    data = request.get_json() or {}
    account = data.get('account')
    password = data.get('password')
    server = data.get('server')
    
    if not account or not password or not server:
        return jsonify({'success': False, 'error': 'account, password, and server are required'}), 400
    
    try:
        from mt5_connector import MT5Connector
        account_int: int = int(account)  # type: ignore
        connector = MT5Connector(account=account_int, password=str(password), server=str(server))
        if connector.connect():
            info = connector.get_account_info()
            return jsonify({'success': True, 'account_info': info})
        else:
            return jsonify({'success': False, 'error': connector.get_last_error()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@trading_bp.route('/api/mt5/positions')
@login_required
@require_license
def api_mt5_positions():
    """Get open MT5 positions"""
    try:
        from mt5_connector import get_mt5_connector
        connector = get_mt5_connector()
        if connector.connected:
            positions = connector.get_positions()
            return jsonify({'success': True, 'positions': positions})
        else:
            return jsonify({'success': False, 'error': 'Not connected to MT5'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@trading_bp.route('/api/mt5/trade', methods=['POST'])
@login_required
@require_license
def api_mt5_trade():
    """Execute MT5 trade"""
    data = request.get_json() or {}
    symbol = data.get('symbol')
    order_type = data.get('type')
    volume = data.get('volume', 0.01)
    sl = data.get('sl')
    tp = data.get('tp')
    
    if not symbol or not order_type:
        return jsonify({'success': False, 'error': 'symbol and type are required'}), 400
    
    symbol_str: str = str(symbol)
    order_type_str: str = str(order_type)
    
    try:
        from mt5_connector import get_mt5_connector
        connector = get_mt5_connector()
        if connector.connected:
            result = connector.open_position(symbol_str, order_type_str, volume, sl, tp)
            if result:
                return jsonify({'success': True, 'trade': result})
            else:
                return jsonify({'success': False, 'error': connector.get_last_error()})
        else:
            return jsonify({'success': False, 'error': 'Not connected to MT5'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# Error handlers for the blueprint
@trading_bp.errorhandler(404)
def not_found(e):
    return render_template('error.html', error='Page not found'), 404


@trading_bp.errorhandler(500)
def server_error(e):
    return render_template('error.html', error='Server error'), 500
