"""
Authentication Blueprint
Handles login, logout, registration, and license activation
"""
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import current_user, login_required, login_user, logout_user

auth_bp = Blueprint('auth', __name__)


@auth_bp.before_app_request
def make_session_permanent():
    """Make session permanent for all requests"""
    session.permanent = True


@auth_bp.route('/')
def index():
    """Home/Landing page - Redirect to mobile home or show landing"""
    if current_user.is_authenticated:
        return redirect(url_for('mobile.home'))
    return render_template('landing.html')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Simple login for development"""
    from app import db
    from models import User
    from license_manager import check_license_valid
    
    if current_user.is_authenticated:
        is_valid, _ = check_license_valid(current_user.id)
        if is_valid:
            return redirect(url_for('mobile.home'))
        else:
            return redirect(url_for('auth.activate_license'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        mentor_id = request.form.get('mentor_id', '')
        
        if not email:
            flash('Email is required', 'error')
            return render_template('login.html')
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            user = User()
            user.id = email.replace('@', '_').replace('.', '_')
            user.email = email
            user.first_name = mentor_id if mentor_id else 'User'
            db.session.add(user)
            db.session.commit()
            
            # Track mentor referral if provided
            if mentor_id:
                try:
                    from mentor_system import track_referral
                    track_referral(user.id, mentor_id)
                except Exception:
                    pass
            
            flash('Account created! Please activate your license.', 'success')
        
        login_user(user, remember=True)
        
        # Check license status
        is_valid, _ = check_license_valid(current_user.id)
        if is_valid:
            return redirect(url_for('mobile.home'))
        else:
            return redirect(url_for('auth.activate_license'))
    
    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    """Log out the current user"""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.index'))


@auth_bp.route('/activate', methods=['GET', 'POST'])
@login_required
def activate_license():
    """License activation page"""
    from models import License
    from license_manager import check_license_valid, validate_license_key
    
    is_valid, license_info = check_license_valid(current_user.id)
    if is_valid:
        return redirect(url_for('mobile.home'))
    
    if request.method == 'POST':
        license_key = request.form.get('license_key', '').strip().upper()
        
        if not license_key:
            flash('Please enter a license key', 'error')
            return render_template('activate_license.html')
        
        is_valid, result = validate_license_key(license_key)
        
        if is_valid:
            existing = License.query.filter_by(license_key=license_key).first()
            if existing and existing.user_id == current_user.id:
                flash('License activated successfully!', 'success')
                return redirect(url_for('mobile.home'))
            elif existing:
                flash('This license key belongs to another account', 'error')
            else:
                flash('License key not found', 'error')
        else:
            flash(f'Invalid license key: {result}', 'error')
        
        return render_template('activate_license.html')
    
    return render_template('activate_license.html')


@auth_bp.route('/licenses')
@login_required
def view_licenses():
    """View user's licenses"""
    from models import License
    
    licenses = License.query.filter_by(user_id=current_user.id).all()
    return render_template('licenses.html', licenses=licenses)


@auth_bp.route('/buy-license', methods=['GET', 'POST'])
@login_required
def buy_license():
    """Purchase or activate a license"""
    from app import db
    from models import License
    from license_manager import (
        create_user_license,
        validate_license_key,
        LICENSE_TYPES
    )
    
    if request.method == 'POST':
        license_key = request.form.get('license_key', '').strip().upper()
        license_type = request.form.get('license_type')
        
        if license_key:
            is_valid, result = validate_license_key(license_key)
            
            if is_valid:
                existing = License.query.filter_by(license_key=license_key).first()
                if existing:
                    if existing.user_id != current_user.id:
                        existing.user_id = current_user.id
                        existing.status = 'active'
                        db.session.commit()
                    
                    flash('License key activated successfully!', 'success')
                    return redirect(url_for('trading.dashboard'))
                else:
                    flash(f'Invalid license key: {result}', 'error')
            else:
                flash(f'Invalid license key: {result}', 'error')
        
        elif license_type and license_type in LICENSE_TYPES:
            new_license = create_user_license(current_user.id, license_type)
            flash(f'{license_type.title()} license created! Your key: {new_license.license_key}', 'success')
            return redirect(url_for('auth.view_licenses'))
        else:
            flash('Please select a license type or enter a valid key', 'error')
    
    from license_manager import LICENSE_TYPES
    return render_template('buy_license.html', license_types=LICENSE_TYPES)
