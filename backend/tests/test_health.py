def test_health_returns_unified_payload(client) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["data"]["status"] == "ok"
    assert body["data"]["database"] in {"up", "down"}


def test_unknown_route_uses_unified_error_shape(client) -> None:
    response = client.get("/api/v1/not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == 40400
    assert body["message"] == "对象不存在"


def test_wrong_method_is_client_error_not_server_error(client) -> None:
    response = client.post("/api/v1/health")

    assert response.status_code == 405
    body = response.json()
    assert body["code"] == 40001
    assert body["message"] == "请求方法不允许"
