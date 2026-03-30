# Web Analyzer Pro

A comprehensive web analysis tool built with Flask that provides detailed insights into website structure, SEO metrics, and content analysis.

![Python](https://img.shields.io/badge/python-v3.8+-blue.svg)
![Flask](https://img.shields.io/badge/flask-v3.0+-green.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)

## 🚀 Features

### Core Analysis Tools
- **URL Analysis** - Comprehensive link analysis with robots.txt compliance
- **Keyword Research** - Text extraction and keyword density analysis
- **Image Analysis** - Image extraction with metadata and optimization insights
- **Meta Tag Analysis** - SEO meta tags and schema markup analysis
- **Heading Structure** - H1-H6 tag hierarchy and SEO compliance
- **Site Structure** - Complete site crawling and visualization

### User Management
- **User Authentication** - Secure login/signup with email verification
- **Subscription Management** - Multiple pricing tiers with usage tracking
- **Profile Management** - User profiles with activity tracking
- **Usage Analytics** - Detailed usage statistics and trends

### Admin Panel
- **User Management** - Admin controls for user accounts
- **Subscription Management** - Plan creation and management
- **Role-based Access** - Granular permission system
- **Payment Tracking** - Complete payment and invoice management
- **Analytics Dashboard** - System-wide usage and revenue analytics

### Payment Integration
- **Razorpay Integration** - Secure payment processing
- **Invoice Generation** - Professional PDF invoices with GST
- **Subscription Billing** - Automated billing cycles
- **Payment History** - Complete transaction tracking

## 🛠️ Technology Stack

- **Backend**: Flask 3.0+, SQLAlchemy, PostgreSQL
- **Frontend**: HTML5, CSS3, JavaScript, Bootstrap
- **Authentication**: Flask-Login, Flask-WTF
- **Payments**: Razorpay API
- **Web Scraping**: BeautifulSoup4, Scrapy, Requests
- **Email**: Flask-Mail with SMTP
- **Caching**: Flask-Caching
- **PDF Generation**: ReportLab

## 📋 Prerequisites

- Python 3.8 or higher
- PostgreSQL 12 or higher
- Redis (optional, for caching)
- Git

## 🔧 Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/web-analyzer-pro.git
cd web-analyzer-pro
```

### 2. Create Virtual Environment
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Environment Configuration
Create a `.env` file in the root directory:

```env
# Flask Configuration
SECRET_KEY=your-super-secret-key-change-this-in-production
FLASK_ENV=development

# Database Configuration
DB_USERNAME=postgres
DB_PASSWORD=your-db-password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=web_analyzer_db

# Email Configuration
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password

# Razorpay Configuration
RAZORPAY_KEY_ID=your-razorpay-key-id
RAZORPAY_KEY_SECRET=your-razorpay-key-secret
```

### 5. Database Setup
```bash
# Create PostgreSQL database
createdb web_analyzer_db

# Initialize database tables
python -c "from app import app, db; app.app_context().push(); db.create_all()"
```

### 6. Run the Application
```bash
# Development mode
python -m flask run --debug

# Or using the WSGI file
python wsgi.py
```

## 🔨 Configuration

### Database Configuration
Update `config.py` with your database settings:

```python
class Config:
    SQLALCHEMY_DATABASE_URI = f"postgresql://{DB_USERNAME}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    SECRET_KEY = os.environ.get('SECRET_KEY')
    # ... other configurations
```

### Email Configuration
Configure SMTP settings for email functionality:

```python
MAIL_SERVER = 'smtp.gmail.com'
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
```

### Payment Configuration
Set up Razorpay for payment processing:

```python
RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET')
```

## 📖 Usage

### User Registration and Login
1. Visit `/signup` to create a new account
2. Verify your email address
3. Login at `/login`
4. Choose a subscription plan at `/subscriptions`

### Web Analysis Tools

#### URL Analysis
```python
# Navigate to /url_analysis
# Enter a website URL
# Get comprehensive link analysis with robots.txt compliance
```

#### Keyword Analysis
```python
# Navigate to /keyword_search
# Enter target URL and keywords
# Get keyword density and SEO recommendations
```

#### Image Analysis
```python
# Navigate to /image_search
# Analyze images, alt tags, and optimization opportunities
```

### Admin Panel
Access admin features at `/admin` (requires admin privileges):

- User management
- Subscription plans
- Payment tracking
- System analytics

## 🏗️ Project Structure

```
web-analyzer-pro/
├── app.py                 # Main Flask application
├── config.py             # Configuration settings
├── wsgi.py               # WSGI entry point
├── requirements.txt      # Python dependencies
├── README.md            # Project documentation
├── templates/           # HTML templates
│   ├── admin/          # Admin panel templates
│   ├── user/           # User dashboard templates
│   └── ...
├── static/             # Static files (CSS, JS, images)
├── utils/              # Utility modules
│   ├── link_analyzer.py
│   ├── text_extractor.py
│   ├── image_extractor.py
│   └── seo_analyzer.py
├── logs/               # Application logs
└── download_files/     # Generated reports
```

## 🔌 API Endpoints

### Authentication
- `POST /signup` - User registration
- `POST /login` - User login
- `GET /logout` - User logout
- `POST /reset_password` - Password reset

### Analysis Tools
- `POST /url_analysis` - URL analysis
- `POST /keyword_search` - Keyword analysis
- `POST /image_search` - Image analysis
- `POST /meta_search` - Meta tag analysis

### Subscriptions
- `GET /subscriptions` - View subscription plans
- `POST /subscribe/<plan_id>` - Subscribe to plan
- `POST /payment/verify/<order_id>` - Verify payment

### Admin (Requires Authentication)
- `GET /admin` - Admin dashboard
- `GET /admin/users` - User management
- `GET /admin/subscriptions` - Subscription management
- `GET /admin/payments` - Payment tracking

## 🚀 Deployment

### Production Setup

1. **Update Configuration**
```python
# config.py
class ProductionConfig(Config):
    DEBUG = False
    WTF_CSRF_ENABLED = True
    SESSION_COOKIE_SECURE = True  # Enable when using HTTPS
```

2. **Environment Variables**
```bash
export FLASK_ENV=production
export SECRET_KEY=your-production-secret-key
```

3. **WSGI Server (Gunicorn)**
```bash
pip install gunicorn
gunicorn --bind 0.0.0.0:8000 wsgi:application
```

4. **Web Server (Nginx)**
```nginx
server {
    listen 80;
    server_name your-domain.com;
    
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Docker Deployment

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "wsgi:application"]
```

## 🧪 Testing

### Manual Testing
1. Visit `/test-csrf` to verify CSRF protection
2. Test all analysis tools with various URLs
3. Verify subscription and payment flows

### CSRF Token Testing
```javascript
// Check CSRF token functionality
fetch('/debug/csrf-status')
  .then(response => response.json())
  .then(data => console.log(data));
```

## 📊 Monitoring and Logs

### Application Logs
```bash
# View application logs
tail -f logs/app_$(date +%Y%m%d).log
```

### Database Monitoring
```sql
-- Monitor active subscriptions
SELECT COUNT(*) FROM subscribed_users WHERE end_date > NOW();

-- Check payment statistics
SELECT status, COUNT(*) FROM payments GROUP BY status;
```

## 🔒 Security Features

- **CSRF Protection** - All forms protected against CSRF attacks
- **Email Verification** - Required for account activation
- **Password Security** - Bcrypt hashing with complexity requirements
- **Session Management** - Secure session handling
- **SQL Injection Prevention** - SQLAlchemy ORM protection
- **XSS Protection** - Template auto-escaping

## 🐛 Troubleshooting

### Common Issues

1. **CSRF Token Errors**
```bash
# Check CSRF configuration
curl http://localhost:5000/debug/csrf-status
```

2. **Database Connection Issues**
```bash
# Test database connection
python -c "from app import db; print(db.engine.execute('SELECT 1').scalar())"
```

3. **Email Configuration**
```bash
# Test email sending
python -c "from app import mail; print('Email configured properly')"
```

4. **Payment Integration**
```bash
# Verify Razorpay configuration
curl -u KEY_ID:KEY_SECRET https://api.razorpay.com/v1/payments
```

## 📈 Performance Optimization

- **Caching**: Implement Redis for session and analysis caching
- **Database**: Use connection pooling and query optimization
- **Static Files**: Use CDN for static asset delivery
- **Monitoring**: Implement application performance monitoring

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

### Development Guidelines
- Follow PEP 8 style guidelines
- Add tests for new features
- Update documentation
- Ensure CSRF protection for all forms

## 📝 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Flask community for excellent documentation
- Bootstrap for responsive UI components
- Razorpay for payment processing
- Contributors and testers

## 📞 Support

For support and questions:
- Email: support@webanalyzerpro.com
- Documentation: [Wiki](https://github.com/yourusername/web-analyzer-pro/wiki)
- Issues: [GitHub Issues](https://github.com/yourusername/web-analyzer-pro/issues)

## 🚀 Roadmap

- [ ] API rate limiting
- [ ] Advanced analytics dashboard
- [ ] White-label solutions
- [ ] Mobile application
- [ ] Integration with Google Analytics
- [ ] Bulk URL analysis
- [ ] Competitive analysis features
- [ ] SEO recommendations engine

---

**Made with ❤️ for the SEO and web development community**