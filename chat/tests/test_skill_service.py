import asyncio
import functools

import pytest

from services import skill_service as ss


def arun(fn):
    """Roda teste async sem plugin (pytest-asyncio não instalado)."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))
    return wrapper


@pytest.fixture
def store(monkeypatch):
    rows = {}

    async def lst():
        return list(rows.values())

    async def get(slug):
        return rows.get(slug)

    async def insert(slug, v):
        if slug in rows:
            raise ss.SkillError("Já existe uma skill com esse slug.")
        rows[slug] = {"slug": slug, "name": v["name"], "description": v["description"],
                      "body": v["body"], "updated_at": None}
        return rows[slug]

    async def update(slug, v):
        if slug not in rows:
            raise ss.SkillNotFound(slug)
        rows[slug].update(name=v["name"], description=v["description"],
                          body=v["body"])
        return rows[slug]

    async def delete(slug):
        if rows.pop(slug, None) is None:
            raise ss.SkillNotFound(slug)

    for n, f in (("_db_list", lst), ("_db_get", get), ("_db_insert", insert),
                 ("_db_update", update), ("_db_delete", delete)):
        monkeypatch.setattr(ss, n, f)
    return rows


@arun
async def test_crud(store):
    await ss.create_skill("nova", {"name": "Nova", "body": "x"})
    assert (await ss.get_skill("nova"))["name"] == "Nova"
    with pytest.raises(ss.SkillError):
        await ss.create_skill("nova", {"name": "Nova", "body": "x"})
    await ss.update_skill("nova", {"name": "Outra", "body": "y"})
    assert (await ss.get_skill("nova"))["name"] == "Outra"
    with pytest.raises(ss.SkillNotFound):
        await ss.update_skill("nada", {"name": "N", "body": "y"})
    await ss.delete_skill("nova")
    assert await ss.get_skill("nova") is None


@arun
async def test_validation(store):
    for bad in ("../x", "a/b", "", "x.md", "a" * 81):
        with pytest.raises(ss.SkillError):
            await ss.create_skill(bad, {"name": "N", "body": "b"})
        assert await ss.get_skill(bad) is None
    with pytest.raises(ss.SkillError):
        await ss.create_skill("ok", {"name": "", "body": "b"})
    with pytest.raises(ss.SkillError):
        await ss.create_skill("ok", {"name": "N", "body": " "})
