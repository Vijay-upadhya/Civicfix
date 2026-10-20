# CivicFix

**Report it. Track it. Fix it.**

## Problem statement
Residents report potholes, garbage, broken streetlights and similar problems through phone calls or scattered forms. Reports get lost, duplicated and misrouted, and nobody can see what is happening or whether deadlines are met.

## Solution overview
CivicFix is a full-stack civic complaint platform. Citizens submit location-based complaints; the system suggests a category, routes the complaint to a department, warns about nearby duplicates, scores priority with plain-language reasons and starts an SLA clock. Officers and administrators work the queue and see analytics computed from the database.

> **Demo project.** Not connected to any government system. All data is synthetic; demo statistics are labelled as demo.

## Features
- Five-step complaint wizard (type, details, map location, evidence, review) with Leaflet/OpenStreetMap
- Rule-based **and** TF-IDF + Logistic Regression category prediction with confidence, top-two suggestions and explanation; low confidence goes to *General Review* (never rejected)
- Automatic department routing, admin override, least-loaded officer assignment
- Duplicate detection (200 m, 30 days, unresolved, TF-IDF cosine + category + distance) and admin merge with preserved history
- Explainable 0-100 priority score, admin override that keeps the original score and reason
- SLA deadlines, overdue flags, `check_sla` notifications (24 h warning, overdue, unassigned critical, department threshold)
- Status workflow with enforced transitions and a history table; full audit log
- Upvotes (unique per user), comments, internal notes, content reporting and moderation (hide comments/images)
- In-app notifications; optional email when SMTP variables are set
- Role dashboards with Chart.js; map/list toggle with priority-coloured markers
- REST API with token + session auth, pagination, filtering, throttling, Swagger docs at `/api/docs/`

## User roles
| Role | Can do |
|---|---|
| Citizen | Register, submit/edit own drafts, view public complaints, upvote, comment, reopen/confirm, report content |
| Officer | See own department's complaints, accept, change status, internal notes, request info, upload resolution evidence, department analytics |
| Admin | Everything: users/roles, departments/categories (also via `/admin/`), override category/department/priority, merge, moderate, audit logs, system analytics |

## Technology stack
Django 5.2, Django REST Framework, django-filter, drf-spectacular, SQLite (dev) / PostgreSQL (prod), Pillow, WhiteNoise, Gunicorn, Bootstrap 5, Leaflet, Chart.js, pandas, scikit-learn, joblib.

## Screenshots
Add screenshots to `docs/screenshots/` after you run the app (landing page, report wizard, complaint detail, officer queue, admin dashboard) and link them here.

## Installation
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # then set DEBUG=True for local work
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver
```
Open http://127.0.0.1:8000/.

## Environment variables
`SECRET_KEY`, `DEBUG`, `DATABASE_URL` (blank = SQLite), `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SECURE_SSL_REDIRECT`, `DEMO_MODE`, `EMAIL_HOST/PORT/HOST_USER/HOST_PASSWORD`, `CLASSIFIER_CONFIDENCE_THRESHOLD` (default 0.40). Never commit `.env`.

## Database setup, migrations, seed data
SQLite works out of the box. For PostgreSQL set `DATABASE_URL=postgres://user:pass@host:5432/db`.
```bash
python manage.py migrate
python manage.py seed_demo_data            # 100 complaints; add --reset to rebuild
python manage.py check_sla                 # run hourly (cron) for SLA notifications
```
The seed creates 8 departments, 12 categories, 5 officers, 20 citizens, 100 complaints (30 resolved, 10 overdue, 15 duplicate groups), comments, histories, notifications.

## Demo credentials (demo only, never use in production)
| Role | Email | Password |
|---|---|---|
| Citizen | citizen@example.com | DemoPassword123 |
| Officer (Roads) | officer@example.com | DemoPassword123 |
| Admin | admin@example.com | DemoPassword123 |

## API documentation
Swagger UI: `/api/docs/` - schema: `/api/schema/`. Auth: `POST /api/auth/login/` returns a token; send `Authorization: Token <key>`. Endpoints follow the spec (auth, complaints and actions, categories, departments, intelligence, analytics, notifications, users). Extras: `POST /api/complaints/{id}/images/`, `/accept/`, `/confirm/`, `/request-info/`, `/report/`, `PATCH /api/comments/{id}/hide/`, `PATCH /api/images/{id}/hide/`, `GET /api/audit-logs/`, `GET /api/public/stats/`.

## Architecture
```
Browser (Django templates + JS, Leaflet, Chart.js)
   ↓
Django REST API (accounts, complaints, departments, analytics, notifications)
   ↓
Business services (complaints/services.py, analytics/services.py)
   ↓
PostgreSQL / SQLite
   ↓
Machine-learning module (ml_classifier: rules + TF-IDF/LogReg)
```
Business logic lives in services: `classify_complaint`, `calculate_priority`, `find_possible_duplicates`, `assign_department`, `calculate_sla_deadline`, `create_status_event`, `send_complaint_notification`, `merge_duplicate_complaints`, `calculate_resolution_metrics`.

## Database relationships
```
User
 ├── UserProfile (role, department)
 ├── Complaint, Comment, Upvote, Notification, AuditLog, PrivacyPolicyAcceptance
Complaint
 ├── Category ── Department
 ├── ComplaintImage, ComplaintStatusHistory, Comment, Upvote, Notification
 └── parent_complaint (merged duplicates)
```

## Testing
```bash
python manage.py test
```
59 tests cover models, services, workflow transitions, API permissions, uploads, duplicate detection, priority boundaries, SLA, analytics and the ML module.

## Machine-learning details
`ml_classifier/rules.py` is a transparent keyword classifier. `train_model.py` builds a TF-IDF (1-2 grams) + Logistic Regression pipeline from `dataset.csv` and saves `model.pkl`. `predictor.py` returns label, confidence, top-two and a short explanation of the words that drove the prediction; a keyword hit overrides a weak ML guess. Below the threshold the complaint goes to General Review.

**Honest caveat:** `dataset.csv` (528 rows) is synthetic and generated from templates by `generate_dataset.py`, so the ~100% hold-out accuracy it reports is *not* evidence of real-world accuracy. Replace it with real, anonymised complaint text before making accuracy claims. The dashboard's "prediction accuracy" compares predicted vs final category on actual complaints.
Retrain: `python -m ml_classifier.train_model`.

## Social login (Facebook, X) and location permission
Email + password login always works. Social buttons appear on `/login/` only when a provider's keys are set in `.env`; new social accounts are always created as **citizens**, record privacy-policy acceptance, and are never auto-linked to an existing account by email.

**Google (free).** Only the basic `openid`, `email` and `profile` scopes are used, which need no Google verification. In console.cloud.google.com create a project → Google Auth Platform → configure the consent screen (External; app name, support email) → Clients → Create client → *Web application*, with authorized redirect URI `http://localhost:8000/auth/google/login/callback/` (add your https URL too). Copy the Client ID and secret into `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`. In *Testing* status only listed test users can log in; click *Publish app* so anyone can.

**Facebook (free).** Needs only the `public_profile` and `email` permissions, which do not require App Review. 1) developers.facebook.com → Create app → use case *Authenticate and request data from users with Facebook Login*. 2) Add the `email` permission. 3) Facebook Login → Settings → *Valid OAuth Redirect URIs*: `http://localhost:8000/auth/facebook/login/callback/` (add your https production URL too). 4) Copy App ID and App Secret into `FACEBOOK_APP_ID` / `FACEBOOK_APP_SECRET`. 5) While the app is in *Development mode* only people with a role on the app (admins, developers, testers) can log in; to open it to everyone, add a privacy-policy URL (`/privacy/`), a data-deletion URL (`/data-deletion/`) and an app icon, then switch the app to *Live*.

**X (not free for new developers).** X ended its free API tier for new signups in February 2026 and uses pay-per-use billing, so signing users in can incur charges. The code is included but off by default; set `X_CLIENT_ID` / `X_CLIENT_SECRET` (callback `/auth/twitter_oauth2/login/callback/`) only if you decide to pay. X usually does not return an email address.

**Location permission.** Before using the device location, "nearest to me" sorting, or address search/lookup (which call OpenStreetMap's Nominatim), the app shows a consent dialog and stores the choice (`location_consent_at`, audited). The browser then shows its own permission prompt, and denial is handled with a clear message. Clicking the map to drop a pin always works without consent. Users can withdraw consent on the profile page. Set `PUBLIC_MAP_MARKERS=False` to hide the landing-page map from logged-out visitors.

## Google Maps (optional)
Leave `GOOGLE_MAPS_API_KEY` blank to use OpenStreetMap. To use Google's basemap and address lookup (still drawn with Leaflet, via the GoogleMutant plugin): in the same Google Cloud project, 1) **attach a billing account** (required; low usage stays inside the monthly free allowance, but Google has no default spending cap, so also set a budget alert and a daily quota limit), 2) enable **Maps JavaScript API** and **Geocoding API**, 3) Credentials → Create API key, 4) restrict it: *Application restrictions* → HTTP referrers → `http://localhost:8000/*` (add your production domain later), *API restrictions* → those two APIs, 5) put the key in `.env` as `GOOGLE_MAPS_API_KEY` and restart. If Google rejects the key, the app falls back to OpenStreetMap and shows a notice. This key is visible in the browser by design, so the referrer restriction is what protects it.

## Troubleshooting
- **Map shows grey tiles saying "403 Access blocked":** OpenStreetMap needs a Referer header. `SECURE_REFERRER_POLICY` in `config/settings.py` must be `"strict-origin-when-cross-origin"` (Django's default blocks it). Restart the server and hard-refresh (Ctrl+Shift+R).

## Security considerations
Hashed passwords, token/session auth, per-role object permissions (citizens see only public + own; officers only their department; internal notes hidden), explicit field-level edit rules, unique upvotes, DRF throttling, pagination, CSRF on session calls, upload checks (extension, real image content via Pillow, 5 MB, 3 images, random server filenames), authenticated permission-checked media serving, hidden-content moderation, audit log with IP, secrets from environment, `DEBUG=False` + HTTPS settings in production.

## Deployment
`render.yaml` and `build.sh` target Render with a free PostgreSQL database (or use Railway/Docker: `docker compose up --build`). Steps: push to GitHub, create a Blueprint from `render.yaml`, set env vars, deploy, open the URL. **Uploaded images are stored on local disk, which is ephemeral on most free hosts**; use object storage (e.g. S3/Cloudinary via django-storages) for real use. Add a cron job for `python manage.py check_sla`.

## Known limitations
- Social login code is tested at the adapter level, but live Facebook/X logins need your own developer credentials and have not been exercised end to end. X login is optional because X's API is paid.
- No email verification, password reset or MFA yet.
- Local-disk media; in-memory throttle cache; no Celery/Redis; email is optional and console-only by default.
- Reverse geocoding uses the public Nominatim service (low volume only, per its usage policy).
- Training data is synthetic; ward is free text rather than boundary-polygon lookup.
- Hand-written front end (no SPA); no automated browser tests; not yet deployed or load-tested.

## Future improvements
Social login, email/SMS notifications, ward polygons, S3 media, background jobs for SLA checks, real labelled dataset, marker clustering, i18n, accessibility audit.

## Developer information
Built by Vijay Upadhyay as a portfolio project.
