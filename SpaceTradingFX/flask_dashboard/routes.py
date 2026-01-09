from flask import render_template, request, redirect, url_for, flash, jsonify, session
try:
    from . import admin, payments  # ensure admin and payments blueprints are registered
except Exception:
    # Support running the app from different working directories / contexts
    try:
        import SpaceTradingFX.flask_dashboard.admin as admin
        import SpaceTradingFX.flask_dashboard.payments as payments
    except Exception:
        try:
            import admin
            import payments
        except Exception:
            # If none import, continue — routes may still function without admin/payments
            admin = None
            payments = None
from flask_login import current_user, login_required, login_user, logout_user
from app import app, db
from models import User, License, TradingPreference, Trade, TradingSignal
from license_manager import (
    create_user_license, 
    check_license_valid, 
    require_license,
    validate_license_key,
    LICENSE_TYPES
)
from trading_engine import TradingEngine
from forex_data import get_forex_provider
from datetime import datetime
import os


# Default lot sizes for symbols
DEFAULT_LOT_SIZES = {
    'EURUSD': 0.02,
    'GBPUSD': 0.01,
    'XAUUSD': 0.01,
    'USDJPY': 0.02,
    'AUDUSD': 0.01,
    'USDCAD': 0.01,
    'USDCHF': 0.01,
    'NZDUSD': 0.01,
}

# Common MT5 servers
COMMON_MT5_SERVERS = [
    'ICMarkets-Demo',
    'ICMarkets-Live',
    'RazorMarkets-Live',
    'Pepperstone-Demo',
    'Pepperstone-Live',
    'XM-Demo',
    'XM-Real',
    'FXCM-Demo',
    'FXCM-Real',
]


# Make session permanent
@app.before_request
def make_session_permanent():
    session.permanent = True


# Home/Landing page - Redirect to mobile home
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('mobile_home'))
    return render_template('landing.html')


# Simple login for development (without Replit Auth)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        # Check if user has a valid license
        is_valid, _ = check_license_valid(current_user.id)
        if is_valid:
            return redirect(url_for('mobile_home'))
        else:
            return redirect(url_for('activate_license'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        mentor_id = request.form.get('mentor_id', '')
        
        if not email:
            flash('Email is required', 'error')
            return render_template('login.html')
        
        # Find or create user
        user = User.query.filter_by(email=email).first()
        
        if not user:
            # Create new user
            user = User(
                id=email.replace('@', '_').replace('.', '_'),
                email=email,
                first_name=mentor_id if mentor_id else 'User'
            )
            db.session.add(user)
            db.session.commit()
            flash(f'Welcome! New account created for {email}', 'success')
        else:
            flash(f'Welcome back, {email}!', 'success')
        
        # Log in the user
        login_user(user, remember=True)
        
        # Check if user has a valid license
        is_valid, _ = check_license_valid(user.id)
        if is_valid:
            return redirect(url_for('mobile_home'))
        else:
            return redirect(url_for('activate_license'))
    
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('index'))


# Main dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    # Check if user has valid license
    is_valid, license_info = check_license_valid(current_user.id)
    
    # Get trading engine
    engine = TradingEngine(current_user.id)
    account_summary = engine.get_account_summary()
    
    # Get trading preferences
    preferences = TradingPreference.query.filter_by(user_id=current_user.id).first()
    
    # Get recent signals
    recent_signals = TradingSignal.query.order_by(
        TradingSignal.created_at.desc()
    ).limit(5).all()
    
    return render_template(
        'dashboard.html',
        user=current_user,
        has_license=is_valid,
        license=license_info if is_valid else None,
        account_summary=account_summary,
        preferences=preferences,
        recent_signals=recent_signals
    )


# License management
@app.route('/licenses')
@login_required
def view_licenses():
    user_licenses = License.query.filter_by(user_id=current_user.id).order_by(
        License.created_at.desc()
    ).all()
    
    return render_template(
        'licenses.html',
        licenses=user_licenses,
        license_types=LICENSE_TYPES
    )


@app.route('/buy-license', methods=['GET', 'POST'])
@login_required
def buy_license():
    if request.method == 'POST':
        license_type = request.form.get('license_type')
        license_key = request.form.get('license_key')
        
        if license_key:
            # User entering existing license key
            from license_manager import validate_license_key
            is_valid, result = validate_license_key(license_key)
            
            if is_valid:
                # Create license record for user
                new_license = License(
                    user_id=current_user.id,
                    license_key=license_key,
                    license_type=result['license_type'],
                    status='active',
                    issued_at=datetime.fromisoformat(result['issued']),
                    expires_at=datetime.fromisoformat(result['expires']),
                    max_active_trades=result['max_trades'],
                    features=result['features']
                )
                db.session.add(new_license)
                db.session.commit()
                
                flash('License key activated successfully!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash(f'Invalid license key: {result}', 'error')
        
        elif license_type and license_type in LICENSE_TYPES:
            # Generate new license (demo mode - in production, integrate Stripe)
            new_license = create_user_license(current_user.id, license_type)
            
            flash(f'{license_type.title()} license created! Your key: {new_license.license_key}', 'success')
            return redirect(url_for('view_licenses'))
        else:
            flash('Please select a license type or enter a valid key', 'error')
    
    return render_template('buy_license.html', license_types=LICENSE_TYPES)


# Trading preferences
@app.route('/preferences', methods=['GET', 'POST'])
@login_required
@require_license
def trading_preferences():
    preferences = TradingPreference.query.filter_by(user_id=current_user.id).first()
    
    if not preferences:
        preferences = TradingPreference(user_id=current_user.id)
        db.session.add(preferences)
        db.session.commit()
    
    if request.method == 'POST':
        # Update preferences
        currency_pairs = request.form.getlist('currency_pairs')
        preferences.currency_pairs = currency_pairs
        preferences.timeframe = request.form.get('timeframe', '1H')
        preferences.risk_percentage = float(request.form.get('risk_percentage', 1.0))
        preferences.max_concurrent_trades = int(request.form.get('max_concurrent_trades', 3))
        preferences.trading_enabled = request.form.get('trading_enabled') == 'on'
        # Direction preferences per pair (BOTH/BUY/SELL)
        direction_prefs = {}
        for p in currency_pairs:
            val = request.form.get(f'direction_{p}', 'BOTH')
            if val not in ('BOTH', 'BUY', 'SELL'):
                val = 'BOTH'
            direction_prefs[p] = val
        preferences.direction_preferences = direction_prefs
        # Optional MT5 fields
        preferences.mt5_account = request.form.get('mt5_account') or preferences.mt5_account
        preferences.mt5_server = request.form.get('mt5_server') or preferences.mt5_server
        
        db.session.commit()
        flash('Trading preferences updated!', 'success')
        return redirect(url_for('dashboard'))
    
    # Available currency pairs
    available_pairs = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'NZDUSD']
    
    return render_template(
        'preferences.html',
        preferences=preferences,
        available_pairs=available_pairs
    )


# Trading actions
@app.route('/analyze-markets')
@login_required
@require_license
def analyze_markets():
    engine = TradingEngine(current_user.id)
    signals = engine.analyze_markets()
    
    flash(f'Analyzed {len(signals)} currency pairs', 'success')
    return redirect(url_for('mobile_home'))


@app.route('/manual-trade', methods=['POST'])
@login_required
@require_license
def manual_trade():
    currency_pair = request.form.get('currency_pair')
    trade_type = request.form.get('trade_type')  # BUY or SELL
    
    if not currency_pair or not trade_type:
        flash('Currency pair and trade type are required', 'error')
        return redirect(url_for('dashboard'))
    
    engine = TradingEngine(current_user.id)
    
    # Get current market analysis
    forex_provider = get_forex_provider()
    signal_data = forex_provider.analyze_signal(currency_pair)
    
    # Execute trade
    trade = engine.execute_trade(currency_pair, trade_type, signal_data)
    
    if trade:
        flash(f'Trade opened: {currency_pair} {trade_type}', 'success')
    else:
        flash('Could not execute trade. Check your settings.', 'error')
    
    return redirect(url_for('mobile_home'))


@app.route('/close-trade/<int:trade_id>', methods=['POST'])
@login_required
@require_license
def close_trade(trade_id):
    trade = Trade.query.get_or_404(trade_id)
    
    # Verify ownership
    if trade.user_id != current_user.id:
        flash('Unauthorized', 'error')
        return redirect(url_for('mobile_home'))
    
    if trade.status != 'open':
        flash('Trade is already closed', 'error')
        return redirect(url_for('mobile_home'))
    
    # Close trade
    engine = TradingEngine(current_user.id)
    current_price = engine._get_current_price(trade.currency_pair)
    engine._close_trade(trade, current_price)
    db.session.commit()
    
    flash(f'Trade closed. P/L: ${trade.profit_loss:.2f}', 'success')
    return redirect(url_for('mobile_home'))


# API endpoints for AJAX
@app.route('/api/account-summary')
@login_required
def api_account_summary():
    engine = TradingEngine(current_user.id)
    summary = engine.get_account_summary()
    
    # Convert trades to dict
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


@app.route('/api/forex-data/<currency_pair>')
@login_required
def api_forex_data(currency_pair):
    forex_provider = get_forex_provider()
    data = forex_provider.get_forex_intraday(currency_pair[:3], currency_pair[3:])
    return jsonify(data)


@app.route('/api/market-signal/<currency_pair>')
@login_required
def api_market_signal(currency_pair):
    forex_provider = get_forex_provider()
    signal = forex_provider.analyze_signal(currency_pair)
    return jsonify(signal)


# Error handlers
@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', error='Page not found'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', error='Server error'), 500

# =====================================================
# MOBILE APP ROUTES
# =====================================================

@app.route('/m/')
@app.route('/m/home')
@login_required
def mobile_home():
    """Mobile Home Screen - EA Connection Status"""
    # Check if user has valid license
    is_valid, license_info = check_license_valid(current_user.id)
    
    # Get trading engine
    engine = TradingEngine(current_user.id)
    account_summary = engine.get_account_summary()
    
    # Get trading preferences
    preferences = TradingPreference.query.filter_by(user_id=current_user.id).first()
    
    return render_template(
        'mobile_home.html',
        user=current_user,
        has_license=is_valid,
        license=license_info if is_valid else None,
        account_summary=account_summary,
        preferences=preferences,
        active_page='home'
    )


@app.route('/m/quotes', methods=['GET', 'POST'])
@login_required
def mobile_quotes():
    """Mobile Quotes Screen - Trading Symbols Configuration"""
    # Get or create preferences
    preferences = TradingPreference.query.filter_by(user_id=current_user.id).first()
    if not preferences:
        preferences = TradingPreference(user_id=current_user.id)
        db.session.add(preferences)
        db.session.commit()
    
    # Available symbols
    available_pairs = ['EURUSD', 'GBPUSD', 'XAUUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'NZDUSD']
    
    if request.method == 'POST':
        # Get enabled pairs
        enabled_pairs = request.form.getlist('enabled_pairs')
        preferences.currency_pairs = enabled_pairs
        
        # Get direction preferences and lot sizes
        direction_prefs = {}
        lot_sizes = preferences.strategy_settings.get('lot_sizes', {}) if preferences.strategy_settings else {}
        
        for pair in available_pairs:
            direction = request.form.get(f'direction_{pair}', 'BOTH')
            if direction in ('BOTH', 'BUY', 'SELL'):
                direction_prefs[pair] = direction
            
            lot_size = request.form.get(f'lot_{pair}')
            if lot_size:
                try:
                    lot_sizes[pair] = float(lot_size)
                except ValueError:
                    lot_sizes[pair] = DEFAULT_LOT_SIZES.get(pair, 0.01)
        
        preferences.direction_preferences = direction_prefs
        
        # Save lot sizes in strategy_settings
        if not preferences.strategy_settings:
            preferences.strategy_settings = {}
        preferences.strategy_settings['lot_sizes'] = lot_sizes
        
        # Trading enabled toggle
        preferences.trading_enabled = request.form.get('trading_enabled') == 'on'
        
        db.session.commit()
        flash('Settings saved successfully!', 'success')
        return redirect(url_for('mobile_quotes'))
    
    # Build symbols list with current settings
    symbols = []
    lot_sizes = preferences.strategy_settings.get('lot_sizes', {}) if preferences.strategy_settings else {}
    direction_prefs = preferences.direction_preferences if preferences.direction_preferences else {}
    
    for pair in available_pairs:
        symbols.append({
            'pair': pair,
            'enabled': pair in (preferences.currency_pairs or []),
            'lot_size': lot_sizes.get(pair, DEFAULT_LOT_SIZES.get(pair, 0.01)),
            'direction': direction_prefs.get(pair, 'BOTH'),
            'platform': 'MT5'
        })
    
    return render_template(
        'mobile_quotes.html',
        symbols=symbols,
        trading_enabled=preferences.trading_enabled,
        active_page='quotes'
    )


@app.route('/m/metatrader', methods=['GET', 'POST'])
@login_required
def mobile_metatrader():
    """Mobile MetaTrader Screen - Account Linking"""
    platform = request.args.get('platform', 'mt5')
    
    # Get or create preferences
    preferences = TradingPreference.query.filter_by(user_id=current_user.id).first()
    if not preferences:
        preferences = TradingPreference(user_id=current_user.id)
        db.session.add(preferences)
        db.session.commit()
    
    if request.method == 'POST':
        account_number = request.form.get('account_number', '').strip()
        server = request.form.get('server', '').strip()
        
        if account_number:
            preferences.mt5_account = account_number
        if server:
            preferences.mt5_server = server
        
        db.session.commit()
        flash('MT5 account details saved!', 'success')
        return redirect(url_for('mobile_metatrader'))
    
    # Check if connected (has account number)
    is_connected = bool(preferences.mt5_account)
    
    return render_template(
        'mobile_metatrader.html',
        preferences=preferences,
        platform=platform,
        is_connected=is_connected,
        common_servers=COMMON_MT5_SERVERS,
        active_page='metatrader'
    )


@app.route('/activate', methods=['GET', 'POST'])
@login_required
def activate_license():
    """License activation page - shown after login if no license"""
    # Check if user already has valid license
    is_valid, license_info = check_license_valid(current_user.id)
    if is_valid:
        return redirect(url_for('mobile_home'))
    
    if request.method == 'POST':
        license_key = request.form.get('license_key', '').strip().upper()
        
        if not license_key:
            flash('Please enter a license key', 'error')
            return render_template('activate_license.html')
        
        # Validate the license key
        is_valid, result = validate_license_key(license_key)
        
        if is_valid:
            # License exists and is valid - check if it belongs to current user
            existing = License.query.filter_by(license_key=license_key).first()
            if existing and existing.user_id == current_user.id:
                flash('License activated successfully!', 'success')
                return redirect(url_for('mobile_home'))
            elif existing:
                flash('This license key belongs to another account', 'error')
            else:
                flash('License key not found', 'error')
        else:
            flash(f'Invalid license key: {result}', 'error')
        
        return render_template('activate_license.html')
    
    return render_template('activate_license.html')


# Mobile Trade History Page
@app.route('/m/history')
@login_required
def mobile_history():
    """Mobile trade history page"""
    filter_type = request.args.get('filter', 'all')
    
    # Get all trades for user
    query = Trade.query.filter_by(user_id=current_user.id)
    
    if filter_type == 'open':
        query = query.filter_by(status='open')
    elif filter_type == 'closed':
        query = query.filter_by(status='closed')
    elif filter_type == 'profit':
        query = query.filter(Trade.profit_loss >= 0, Trade.status == 'closed')
    elif filter_type == 'loss':
        query = query.filter(Trade.profit_loss < 0, Trade.status == 'closed')
    
    trades = query.order_by(Trade.opened_at.desc()).all()
    
    # Calculate stats
    closed_trades = Trade.query.filter_by(user_id=current_user.id, status='closed').all()
    total_trades = len(closed_trades)
    total_profit = sum(t.profit_loss for t in closed_trades)
    winning_trades = len([t for t in closed_trades if t.profit_loss >= 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    return render_template(
        'mobile_history.html',
        trades=trades,
        filter=filter_type,
        total_trades=total_trades,
        total_profit=total_profit,
        win_rate=round(win_rate, 1),
        active_page='history'
    )


# Mobile Profile/Settings Page
@app.route('/m/profile', methods=['GET', 'POST'])
@login_required
def mobile_profile():
    """Mobile profile and settings page"""
    if request.method == 'POST':
        # Handle become mentor
        if request.form.get('become_mentor'):
            try:
                from mentor_system import register_as_mentor
                mentor_id = register_as_mentor(current_user.id)
                flash(f'You are now a mentor! Your ID is: {mentor_id}', 'success')
            except Exception as e:
                flash(f'Could not register as mentor: {e}', 'error')
        else:
            # Update notification preferences
            current_user.email_notifications = 'email_notifications' in request.form
            current_user.trade_alerts = 'trade_alerts' in request.form
            current_user.signal_alerts = 'signal_alerts' in request.form
            db.session.commit()
            flash('Settings saved!', 'success')
        
        return redirect(url_for('mobile_profile'))
    
    # Get license info
    license_obj = License.query.filter_by(
        user_id=current_user.id, 
        status='active'
    ).first()
    
    # Get mentor stats if user is a mentor
    mentor_stats = None
    if current_user.is_mentor:
        try:
            from mentor_system import get_mentor_stats
            mentor_stats = get_mentor_stats(current_user.id)
        except:
            pass
    
    return render_template(
        'mobile_profile.html',
        license=license_obj,
        mentor_stats=mentor_stats,
        active_page='profile'
    )


# Mobile Notifications Page
@app.route('/m/notifications', methods=['GET', 'POST'])
@login_required
def mobile_notifications():
    """Mobile notifications page"""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'mark_read':
            notification_id = request.form.get('notification_id')
            try:
                from notifications import mark_as_read
                mark_as_read(int(notification_id), current_user.id)
            except:
                pass
        
        elif action == 'mark_all_read':
            try:
                from notifications import mark_all_as_read
                mark_all_as_read(current_user.id)
                flash('All notifications marked as read', 'success')
            except:
                pass
        
        return redirect(url_for('mobile_notifications'))
    
    # Get notifications
    try:
        from notifications import get_user_notifications, get_unread_count
        notifications = get_user_notifications(current_user.id, limit=50)
        unread_count = get_unread_count(current_user.id)
    except:
        notifications = []
        unread_count = 0
    
    return render_template(
        'mobile_notifications.html',
        notifications=notifications,
        unread_count=unread_count,
        active_page='notifications'
    )


# API: Get notifications count
@app.route('/api/notifications/count')
@login_required
def api_notifications_count():
    """Get unread notifications count"""
    try:
        from notifications import get_unread_count
        count = get_unread_count(current_user.id)
    except:
        count = 0
    return jsonify({'count': count})


# API: Create notification (for testing)
@app.route('/api/notifications/test', methods=['POST'])
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


# MT5 API endpoints
@app.route('/api/mt5/connect', methods=['POST'])
@login_required
@require_license
def api_mt5_connect():
    """Connect to MT5 account"""
    data = request.get_json() or {}
    account = data.get('account')
    password = data.get('password')
    server = data.get('server')
    
    try:
        from mt5_connector import MT5Connector
        connector = MT5Connector(account=int(account), password=password, server=server)
        if connector.connect():
            info = connector.get_account_info()
            return jsonify({'success': True, 'account_info': info})
        else:
            return jsonify({'success': False, 'error': connector.get_last_error()})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/mt5/positions')
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


@app.route('/api/mt5/trade', methods=['POST'])
@login_required
@require_license
def api_mt5_trade():
    """Execute MT5 trade"""
    data = request.get_json() or {}
    symbol = data.get('symbol')
    order_type = data.get('type')  # BUY or SELL
    volume = data.get('volume', 0.01)
    sl = data.get('sl')
    tp = data.get('tp')
    
    try:
        from mt5_connector import get_mt5_connector
        connector = get_mt5_connector()
        if connector.connected:
            result = connector.open_position(symbol, order_type, volume, sl, tp)
            if result:
                return jsonify({'success': True, 'trade': result})
            else:
                return jsonify({'success': False, 'error': connector.get_last_error()})
        else:
            return jsonify({'success': False, 'error': 'Not connected to MT5'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500