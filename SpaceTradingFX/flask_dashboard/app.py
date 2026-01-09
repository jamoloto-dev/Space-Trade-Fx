from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
import os
from werkzeug.middleware.proxy_fix import ProxyFix
import logging

# Security imports
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Configure logging
logging.basicConfig(level=logging.DEBUG)

class Base(DeclarativeBase):
    pass

# Initialize Flask app
app = Flask(__name__)

# Load configuration
from config import get_config
config_class = get_config()
app.config.from_object(config_class)

# Validate configuration
config_errors = config_class.validate()
if config_errors:
    for error in config_errors:
        logging.warning(f"Configuration warning: {error}")

app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=[app.config.get('RATELIMIT_DEFAULT', '200 per day, 50 per hour')],
    storage_uri=app.config.get('RATELIMIT_STORAGE_URI', 'memory://'),
    enabled=app.config.get('RATELIMIT_ENABLED', True)
)

# Initialize database
db = SQLAlchemy(app, model_class=Base)

# Initialize Flask-Login
from flask_login import LoginManager
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

# Expose feature flags to templates
@app.context_processor
def inject_feature_flags():
    return {
        "ENABLE_GPT5_FOR_ALL_CLIENTS": app.config.get("ENABLE_GPT5_FOR_ALL_CLIENTS", False)
    }

@login_manager.user_loader
def load_user(user_id):
    from models import User
    return User.query.get(user_id)

# Create tables
with app.app_context():
    import models  # noqa: F401
    db.create_all()
    logging.info("Database tables created")

    # Ensure a local default admin account exists for development/testing.
    try:
        from models import User

        admin_email = os.environ.get("DEFAULT_ADMIN_EMAIL", "molotojafta30@gmail.com")
        admin_first = os.environ.get("DEFAULT_ADMIN_FIRST", "Jafta")
        admin_last = os.environ.get("DEFAULT_ADMIN_LAST", "Moloto")

        existing = User.query.filter_by(email=admin_email).first()
        if not existing:
            # Create a local admin user with a deterministic id for local setups
            u = User()
            u.id = os.environ.get("DEFAULT_ADMIN_ID", "jafta-moloto")
            u.email = admin_email
            u.first_name = admin_first
            u.last_name = admin_last
            # Set password if provided via env var (development only)
            admin_password = os.environ.get("DEFAULT_ADMIN_PASSWORD")
            if admin_password:
                try:
                    u.set_password(admin_password)
                except Exception:
                    # In case the User model doesn't expose set_password, ignore
                    pass

            # Mark as admin with unlimited premium
            u.is_admin = True
            u.has_unlimited_premium = True
            db.session.add(u)
            db.session.commit()
            logging.info(f"Created default admin user: {admin_first} {admin_last} <{admin_email}> with unlimited premium")
        else:
            logging.debug(f"Default admin user already exists: {existing.email}")
    except Exception:
        # If models/User schema isn't present or DB isn't ready, continue silently.
        logging.debug("Could not create default admin user (models may not be ready)")


# Health check endpoint for load balancers
@app.route('/health')
@limiter.exempt
def health_check():
    """Health check endpoint for load balancers and monitoring"""
    from flask import jsonify
    try:
        # Check database connection
        db.session.execute(db.text('SELECT 1'))
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'version': '1.0.0'
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'database': 'disconnected',
            'error': str(e)
        }), 503


# Exempt certain routes from CSRF (webhooks, APIs that use tokens)
@csrf.exempt
@app.route('/payments/webhook', methods=['POST'])
def payments_webhook_csrf_exempt():
    """CSRF exempt endpoint - actual logic in payments blueprint"""
    pass  # Handled by payments blueprint
