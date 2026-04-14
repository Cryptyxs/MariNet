import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timezone
import uuid
import requests
import json
import pytz
from dotenv import load_dotenv
from markupsafe import Markup, escape

# Load environment variables
load_dotenv('.env.local')

# Initialize Flask app
app = Flask(__name__)

@app.template_filter('nl2br')
def nl2br_filter(value):
    if value is None:
        return ''
    escaped = escape(value)
    return Markup(str(escaped).replace('\n', '<br>\n'))

@app.template_filter('chat_time')
def chat_time_filter(value):
    if value is None:
        return ''
    eastern = pytz.timezone('US/Eastern')
    dt_value = value
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(eastern).strftime('%I:%M %p')

# Configuration from environment variables
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-change-in-production')
database_url = os.getenv('DATABASE_URL')

# Handle SQLAlchemy 1.4+ compatibility with PostgreSQL
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

# Neon/PostgreSQL requires SSL in production environments like Vercel.
if database_url and database_url.startswith('postgresql://') and 'sslmode=' not in database_url:
    separator = '&' if '?' in database_url else '?'
    database_url = f"{database_url}{separator}sslmode=require"

app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///marinet.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True
}
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# API Keys from environment variables
app.config['GEMINI_API_KEY'] = os.getenv('GEMINI_API_KEY')
app.config['GEMINI_MODEL'] = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
app.config['QWEN_API_KEY'] = os.getenv('QWEN_API_KEY')
app.config['GEMINI_MODEL_RESOLVED'] = None

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize SQLAlchemy
db = SQLAlchemy(app)

# Initialize Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info'

# AI Response templates
AI_RESPONSES = {
    "default": [
        "That's an interesting question. Let me help you understand this better.",
        "I'd be happy to explain this topic. Here's what you need to know:",
        "Great question! Let me break this down for you:",
        "I can definitely help with that. Here's an explanation:",
        "Let me share some information about this topic that might help you understand better."
    ],
    "math": [
        "When solving math problems, it's helpful to break them down into smaller steps.",
        "In mathematics, we often look for patterns and relationships between numbers.",
        "This mathematical concept can be understood by thinking about it visually.",
        "Let's approach this step-by-step to find the solution.",
        "Mathematical problems often have multiple solution methods. Let me show you one approach."
    ],
    "science": [
        "This scientific concept is based on observations and experiments that show...",
        "In science, we try to explain phenomena through testable hypotheses.",
        "Scientists have found that this process works by...",
        "The scientific evidence suggests that...",
        "This can be explained using the scientific principle of..."
    ],
    "english": [
        "In literature, authors often use various techniques to convey meaning.",
        "This literary device is commonly used to emphasize...",
        "When analyzing this text, consider the author's intended audience and purpose.",
        "The language used here creates a specific tone that...",
        "Let's look at how the structure of this text contributes to its meaning."
    ],
    "history": [
        "Historical events should be understood within their broader context.",
        "Historians analyze primary and secondary sources to understand...",
        "This historical development was influenced by several factors including...",
        "From a historical perspective, this event was significant because...",
        "The historical evidence suggests that this occurred due to..."
    ]
}

# Helper function for EST timezone
def get_est_time():
    utc_now = datetime.utcnow()
    eastern = pytz.timezone('US/Eastern')
    est_now = utc_now.replace(tzinfo=pytz.utc).astimezone(eastern)
    return est_now

# Database Models
group_members = db.Table('group_members',
    db.Column('user_id', db.String(36), db.ForeignKey('user.id'), primary_key=True),
    db.Column('group_id', db.String(36), db.ForeignKey('group.id'), primary_key=True),
    db.Column('is_admin', db.Boolean, default=False),
    db.Column('joined_at', db.DateTime, default=get_est_time)
)

class User(db.Model, UserMixin):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar_url = db.Column(db.String(500), nullable=True, default='/static/default_avatar.jpg')
    bio = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=get_est_time)
    
    posts = db.relationship('Post', backref='user', lazy=True)
    group_posts = db.relationship('GroupPost', backref='user', lazy=True)
    groups = db.relationship('Group', secondary=group_members, backref=db.backref('members', lazy='dynamic'))
    
    def __repr__(self):
        return f'<User {self.username}>'

class UserAvatar(db.Model):
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), primary_key=True)
    mime_type = db.Column(db.String(100), nullable=False)
    image_data = db.Column(db.Text, nullable=False)

    user = db.relationship('User', backref=db.backref('avatar_blob', uselist=False, cascade='all, delete-orphan'))

class UploadedImage(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mime_type = db.Column(db.String(100), nullable=False)
    image_data = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=get_est_time)

class Post(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=get_est_time)
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    upvotes = db.Column(db.Integer, default=0)
    downvotes = db.Column(db.Integer, default=0)

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True, nullable=False)
    count = db.Column(db.Integer, default=1)

class Group(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(50), nullable=False, default='people')
    created_at = db.Column(db.DateTime, default=get_est_time)
    created_by = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    
    posts = db.relationship('GroupPost', backref='group', lazy=True)
    
    @property
    def members_count(self):
        return self.members.count()
        
    def is_member(self, user):
        return self.members.filter_by(id=user.id).first() is not None
        
    def is_admin(self, user):
        membership = db.session.query(group_members).filter_by(
            user_id=user.id, 
            group_id=self.id
        ).first()
        return membership and membership.is_admin if membership else False

class GroupPost(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=get_est_time)
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    group_id = db.Column(db.String(36), db.ForeignKey('group.id'), nullable=False)
    upvotes = db.Column(db.Integer, default=0)
    downvotes = db.Column(db.Integer, default=0)

class Vote(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    post_id = db.Column(db.String(36), db.ForeignKey('post.id'), nullable=True)
    group_post_id = db.Column(db.String(36), db.ForeignKey('group_post.id'), nullable=True)
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    vote_type = db.Column(db.String(10), nullable=False)  
    created_at = db.Column(db.DateTime, default=get_est_time)
    
    post = db.relationship('Post', backref=db.backref('votes', lazy=True), foreign_keys=[post_id])
    group_post = db.relationship('GroupPost', backref=db.backref('votes', lazy=True), foreign_keys=[group_post_id])
    user = db.relationship('User', backref=db.backref('votes', lazy=True))

class AiConversation(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=get_est_time)
    
    messages = db.relationship('AiMessage', backref='conversation', lazy=True, order_by="AiMessage.created_at")
    user = db.relationship('User', backref=db.backref('ai_conversations', lazy=True))

class AiMessage(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = db.Column(db.String(36), db.ForeignKey('ai_conversation.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_user = db.Column(db.Boolean, default=True)  
    created_at = db.Column(db.DateTime, default=get_est_time)

class Notification(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    sender_id = db.Column(db.String(36), db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    post_id = db.Column(db.String(36), db.ForeignKey('post.id'), nullable=True)
    group_post_id = db.Column(db.String(36), db.ForeignKey('group_post.id'), nullable=True)
    notification_type = db.Column(db.String(20), nullable=False)  
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=get_est_time)
    
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('notifications', lazy='dynamic'))
    sender = db.relationship('User', foreign_keys=[sender_id])
    post = db.relationship('Post', backref=db.backref('notifications', lazy=True), foreign_keys=[post_id])
    group_post = db.relationship('GroupPost', backref=db.backref('notifications', lazy=True), foreign_keys=[group_post_id])

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(user_id)

# Gemini API integration
def normalize_gemini_model_name(model_name):
    if not model_name:
        return ''
    return model_name.replace('models/', '').strip()

def list_generate_content_models(api_key, api_version='v1beta'):
    url = f"https://generativelanguage.googleapis.com/{api_version}/models"
    try:
        response = requests.get(
            url,
            headers={"x-goog-api-key": api_key},
            timeout=15
        )
        if response.status_code != 200:
            app.logger.error(f"ListModels failed on {api_version}: {response.status_code} - {response.text[:300]}")
            return []

        data = response.json()
        models = data.get('models', [])
        supported = []

        for model in models:
            methods = model.get('supportedGenerationMethods', [])
            if 'generateContent' in methods:
                supported.append(normalize_gemini_model_name(model.get('name', '')))

        return [m for m in supported if m]
    except Exception as e:
        app.logger.error(f"ListModels request failed on {api_version}: {str(e)}")
        return []

def choose_best_gemini_model(preferred_model, models):
    if not models:
        return None

    preferred = normalize_gemini_model_name(preferred_model)

    if preferred in models:
        return preferred

    for m in models:
        if preferred and preferred in m:
            return m

    # Prefer lower-cost models first when auto-selecting.
    priority_markers = [
        'flash-lite',
        'flash_8b',
        'flash-8b',
        '1.5-flash-8b',
        'flash'
    ]

    for marker in priority_markers:
        for m in models:
            if marker in m.lower():
                return m

    return models[0]

def get_low_cost_model_candidates(models, current_model):
    current = normalize_gemini_model_name(current_model)
    candidates = [m for m in models if normalize_gemini_model_name(m) != current]

    def score(name):
        n = name.lower()
        if 'flash-lite' in n:
            return 0
        if 'flash-8b' in n or 'flash_8b' in n or '1.5-flash-8b' in n:
            return 1
        if 'flash' in n:
            return 2
        if 'pro' in n:
            return 4
        return 3

    return sorted(candidates, key=score)

def call_gemini_generate(api_key, model, user_message, api_version='v1beta'):
    api_url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [{"text": user_message}]
            }
        ]
    }

    response = requests.post(
        api_url,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        },
        data=json.dumps(payload),
        timeout=20
    )
    return response

def generate_ai_response(user_message, conversation_history=None):
    api_key = app.config.get('GEMINI_API_KEY')
    configured_model = normalize_gemini_model_name(app.config.get('GEMINI_MODEL', 'gemini-1.5-flash'))
    resolved_model = normalize_gemini_model_name(app.config.get('GEMINI_MODEL_RESOLVED'))
    model = resolved_model or configured_model
    
    if not api_key or 'add_your' in api_key.lower() or 'your_' in api_key.lower():
        app.logger.error('GEMINI_API_KEY is missing or placeholder value')
        raise RuntimeError("AI Tutor is not configured yet. Please set a valid GEMINI_API_KEY in Vercel environment variables.")
    
    try:
        response = call_gemini_generate(api_key, model, user_message, api_version='v1beta')

        if response.status_code == 404:
            error_message = response.text[:500]
            try:
                error_json = response.json()
                error_message = error_json.get('error', {}).get('message', error_message)
            except Exception:
                pass

            if 'not found for API version' in error_message or 'not supported for generateContent' in error_message:
                available = list_generate_content_models(api_key, api_version='v1beta')
                selected = choose_best_gemini_model(configured_model, available)

                if selected and selected != model:
                    app.logger.warning(f"Switching Gemini model from '{model}' to '{selected}'")
                    app.config['GEMINI_MODEL_RESOLVED'] = selected
                    response = call_gemini_generate(api_key, selected, user_message, api_version='v1beta')
                    model = selected
        
        if response.status_code == 200:
            response_data = response.json()
            ai_response = response_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            
            if not ai_response:
                app.logger.error('Gemini response contained no candidate text')
                raise RuntimeError("AI Tutor returned an empty response. Please try asking again.")
            
            return ai_response
        else:
            error_message = response.text[:300]
            try:
                error_json = response.json()
                error_message = error_json.get('error', {}).get('message', error_message)
            except Exception:
                pass

            lowered_error = error_message.lower()
            if 'spending cap' in lowered_error or 'insufficient quota' in lowered_error or 'quota' in lowered_error:
                available = list_generate_content_models(api_key, api_version='v1beta')
                for candidate in get_low_cost_model_candidates(available, model):
                    retry_response = call_gemini_generate(api_key, candidate, user_message, api_version='v1beta')
                    if retry_response.status_code == 200:
                        app.logger.warning(f"Recovered from quota/cap error by switching model to '{candidate}'")
                        app.config['GEMINI_MODEL_RESOLVED'] = candidate
                        response_data = retry_response.json()
                        ai_response = response_data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if ai_response:
                            return ai_response

            app.logger.error(
                f"Gemini API non-200 response ({response.status_code}) model='{model}': {error_message}"
            )
            raise RuntimeError(f"AI Tutor service error: {error_message}")
    
    except requests.exceptions.Timeout:
        app.logger.error('Gemini API timeout')
        raise RuntimeError("AI Tutor request timed out. Please try again in a few seconds.")
    except RuntimeError:
        raise
    except Exception as e:
        app.logger.error(f"Gemini API error: {str(e)}")
        raise RuntimeError("AI Tutor is temporarily unavailable due to a server error.")

# Import routes after app initialization
from routes import *

# Context processor for popular groups
@app.context_processor
def inject_popular_groups():
    def get_popular_groups(limit=3):
        try:
            groups = Group.query.all()
            groups_sorted = sorted(
                groups,
                key=lambda g: g.members.count(),
                reverse=True
            )
            return groups_sorted[:limit]
        except Exception as e:
            app.logger.error(f"Error fetching popular groups: {str(e)}")
            return []
    return dict(get_popular_groups=get_popular_groups)

# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500

def ensure_database_initialized():
    try:
        with app.app_context():
            db.create_all()
    except Exception as e:
        app.logger.error(f"Database initialization failed: {str(e)}")

# Ensure tables exist on serverless cold starts (Vercel imports module, not __main__).
ensure_database_initialized()

if __name__ == '__main__':
    ensure_database_initialized()
    app.run(debug=False)
