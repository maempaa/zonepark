async def test_health_responde(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "zonepark-api"
    assert body["database"] == "ok", "la API no está viendo la base de datos"


async def test_meta_expone_configuracion(client):
    r = await client.get("/api/v1/meta")
    assert r.status_code == 200
    assert r.json()["tenant_mode"] == "path"
