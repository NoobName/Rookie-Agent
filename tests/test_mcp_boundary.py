import json

import pytest
from fastapi.testclient import TestClient

from services.agent.app import create_app
from services.agent.mcp_registry import MCPServer, resolve, snapshot
from services.agent.store import Store
from services.agent.tools import MCPCall


def test_model_cannot_choose_launch_parameters(tmp_path):
    store = Store(tmp_path)
    for args in ({}, {"command": "cmd", "args": ["/c", "echo arbitrary"]}):
        with pytest.raises(ValueError):
            resolve(store, args)
        with pytest.raises(ValueError):
            snapshot(store, args)
        with pytest.raises(ValueError):
            MCPCall.model_validate(args)
    config = MCPServer(id="saved", name="Saved", command="python").model_dump()
    store.run("INSERT INTO mcp_servers VALUES(?,?,NULL)", ("saved", json.dumps(config)))
    for key in ("command", "args", "url", "transport", "_headers"):
        args = {"server_id": "saved", key: "model controlled"}
        with pytest.raises(ValueError):
            snapshot(store, args)
        with pytest.raises(ValueError):
            MCPCall.model_validate(args)
    args = snapshot(store, {"server_id": "saved", "tool": "test", "arguments": {}})
    assert "command" not in args
    assert resolve(store, args)["command"] == "python"
    config["command"] = "different"
    store.run("UPDATE mcp_servers SET config=?", (json.dumps(config),))
    with pytest.raises(PermissionError):
        resolve(store, args)


def test_custom_port_csp(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PORT", "8793")
    with TestClient(create_app(tmp_path, "t")) as client:
        response = client.get("/health")
        csp = response.headers["content-security-policy"]
        assert "http://127.0.0.1:8793" in csp
        assert "8765" not in csp
