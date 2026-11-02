"""
Agregador do painel admin: monta os routers de cada área sob /admin.

Cada módulo routes/admin/<area>.py exporta `router` (prefix="/admin") e usa
routes/admin/common.py (require_admin, verify_csrf, render).
"""

from fastapi import APIRouter

from routes.admin import access, admins, audit, auth, broadcast, exports, health, knowledge, logs, prompt, quality, queue, skills, usage, users

router = APIRouter()
# exports antes de knowledge: /api/knowledge/export.json não pode cair em /api/knowledge/{doc_id}
for _m in (auth, queue, prompt, skills, exports, knowledge, access, logs, audit, quality, usage, admins, broadcast, health, users):
    router.include_router(_m.router)
