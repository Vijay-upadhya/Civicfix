#!/usr/bin/env bash
# Render / Railway build step
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py seed_demo_data   # idempotent; remove for a production site with real data
