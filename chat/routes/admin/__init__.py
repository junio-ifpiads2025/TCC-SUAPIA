"""
Agregador do painel admin: monta os routers de cada área sob /admin.

Cada módulo routes/admin/<area>.py exporta `router` (prefix="/admin") e usa
routes/admin/common.py (require_admin, verify_csrf, render).
"""

from fastapi import APIRouter

from routes.admin import access, admins, auth, knowledge, logs, prompt, queue, skills, usage

router = APIRouter()
for _m in (auth, queue, prompt, skills, knowledge, access, logs, usage, admins):
    router.include_router(_m.router)
