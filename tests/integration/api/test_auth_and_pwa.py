"""인증(B2)과 PWA(B3) 통합 테스트."""

from pathlib import Path

from fastapi.testclient import TestClient

from pams.interfaces.api.app import create_app


class TestBasicAuth:
    def make_client(self, tmp_path: Path) -> TestClient:
        return TestClient(create_app(data_dir=tmp_path, password="secret-pass"))

    def test_no_password_configured_means_open(self, tmp_path: Path) -> None:
        client = TestClient(create_app(data_dir=tmp_path))
        assert client.get("/api/dashboard").status_code == 200

    def test_unauthorized_without_credentials(self, tmp_path: Path) -> None:
        client = self.make_client(tmp_path)
        response = client.get("/api/dashboard")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"].startswith("Basic")

    def test_dashboard_page_also_protected(self, tmp_path: Path) -> None:
        assert self.make_client(tmp_path).get("/").status_code == 401

    def test_wrong_password_rejected(self, tmp_path: Path) -> None:
        client = self.make_client(tmp_path)
        assert client.get("/api/dashboard", auth=("pams", "wrong")).status_code == 401

    def test_correct_password_allows_any_username(self, tmp_path: Path) -> None:
        client = self.make_client(tmp_path)
        assert client.get("/api/dashboard", auth=("pams", "secret-pass")).status_code == 200
        assert client.get("/", auth=("anyone", "secret-pass")).status_code == 200

    def test_health_stays_open_for_monitoring(self, tmp_path: Path) -> None:
        assert self.make_client(tmp_path).get("/api/health").status_code == 200


class TestPwa:
    def make_client(self, tmp_path: Path) -> TestClient:
        return TestClient(create_app(data_dir=tmp_path))

    def test_manifest_served(self, tmp_path: Path) -> None:
        response = self.make_client(tmp_path).get("/manifest.json")
        assert response.status_code == 200
        manifest = response.json()
        assert manifest["name"] == "PAMS"
        assert manifest["display"] == "standalone"
        assert len(manifest["icons"]) >= 2

    def test_service_worker_served(self, tmp_path: Path) -> None:
        response = self.make_client(tmp_path).get("/sw.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]

    def test_icons_served(self, tmp_path: Path) -> None:
        client = self.make_client(tmp_path)
        for size in (192, 512):
            response = client.get(f"/static/pams-{size}.png")
            assert response.status_code == 200
            assert response.content.startswith(b"\x89PNG")

    def test_dashboard_links_manifest_and_registers_sw(self, tmp_path: Path) -> None:
        html = self.make_client(tmp_path).get("/").text
        assert 'rel="manifest"' in html
        assert "serviceWorker" in html
