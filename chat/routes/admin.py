"""
Agregador do painel admin: monta os routers de cada área sob /admin.

Cada módulo routes/admin_<area>.py exporta `router` (prefix="/admin") e usa
routes/admin_common.py (require_admin, verify_csrf, render).
"""

from fastapi import APIRouter

from routes import (
    admin_access,
    admin_admins,
    admin_auth,
    admin_knowledge,
    admin_logs,
    admin_prompt,
    admin_queue,
    admin_skills,
    admin_usage,
)

router = APIRouter()
for _m in (admin_auth, admin_queue, admin_prompt, admin_skills, admin_knowledge, admin_access, admin_logs, admin_usage, admin_admins):
    router.include_router(_m.router)
