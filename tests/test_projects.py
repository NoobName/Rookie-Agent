from fastapi.testclient import TestClient

from services.agent.app import create_app


def test_project_persistence_workspace_and_session_cleanup(tmp_path):
    data = tmp_path / "data"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with TestClient(create_app(data, "test")) as c:
        c.headers["Authorization"] = "Bearer test"
        assert (
            c.post("/api/projects", json={"name": "", "workspace": str(workspace)}).status_code
            == 400
        )
        assert (
            c.post("/api/projects", json={"name": "bad", "workspace": "relative"}).status_code
            == 400
        )
        project = c.post(
            "/api/projects", json={"name": "Rookie project", "workspace": str(workspace)}
        ).json()
        sid = c.post(
            "/api/sessions", json={"title": "project chat", "project_id": project["id"]}
        ).json()["id"]
        task = c.post(
            f"/api/sessions/{sid}/tasks",
            json={
                "goal": "project task",
                "workspace": "",
                "provider": "scripted",
                "deliverables": ["test.txt"],
                "acceptance": ["inspect"],
            },
        ).json()
        assert task["spec"]["workspace"] == str(workspace.resolve())
        listing = c.get("/api/directories", params={"path": str(tmp_path)}).json()
        assert any(d["path"] == str(workspace) for d in listing["directories"])
    with TestClient(create_app(data, "test")) as c:
        c.headers["Authorization"] = "Bearer test"
        boot = c.get("/api/bootstrap").json()
        assert boot["projects"][0]["id"] == project["id"]
        assert boot["sessions"][0]["project_id"] == project["id"]
        assert c.delete("/api/sessions/" + sid).status_code == 200
        assert not c.app.state.store.rows("SELECT * FROM session_projects")
        assert workspace.is_dir()
