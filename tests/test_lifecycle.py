"""
Integration tests — run against a real local Kubernetes cluster (minikube).

Mark: pytest -m integration
These are skipped by default; pass -m integration to enable.
"""
import time
import pytest
import httpx

pytestmark = pytest.mark.integration

BASE = "http://localhost:8000/api/deployments"
TEST_NS = "shakudo-test"


@pytest.fixture(scope="module")
def http():
    """Module-scoped HTTP client."""
    with httpx.Client(timeout=30) as c:
        yield c


def wait_for_health(http, uid, target, retries=18, interval=5):
    """Poll until deployment health matches target or timeout."""
    for _ in range(retries):
        r = http.get(f"{BASE}/{uid}")
        if r.status_code == 200 and r.json().get("health") == target:
            return r.json()
        time.sleep(interval)
    r = http.get(f"{BASE}/{uid}")
    return r.json() if r.status_code == 200 else {}


# ── Full lifecycle ────────────────────────────────────────────────────────────

class TestDeploymentLifecycle:
    created_uid = None

    def test_create(self, http):
        r = http.post(BASE, json={
            "name": "lifecycle-test",
            "namespace": TEST_NS,
            "image": "nginx:latest",
            "replicas": 2,
        })
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "lifecycle-test"
        assert body["namespace"] == TEST_NS
        assert "id" in body
        TestDeploymentLifecycle.created_uid = body["id"]

    def test_appears_in_list(self, http):
        uid = TestDeploymentLifecycle.created_uid
        assert uid, "create must run first"
        r = http.get(BASE, params={"namespace": TEST_NS})
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()]
        assert uid in ids

    def test_list_namespace_filter(self, http):
        r_all = http.get(BASE)
        r_ns  = http.get(BASE, params={"namespace": TEST_NS})
        assert r_all.status_code == 200
        assert r_ns.status_code == 200
        ns_ids = {d["id"] for d in r_ns.json()}
        assert all(d["namespace"] == TEST_NS for d in r_ns.json())

    def test_detail_has_pod_info(self, http):
        uid = TestDeploymentLifecycle.created_uid
        # Wait for pods to appear
        detail = wait_for_health(http, uid, "HEALTHY")
        assert "pods" in detail
        assert "conditions" in detail
        assert "replicas" in detail

    def test_scale_up(self, http):
        uid = TestDeploymentLifecycle.created_uid
        r = http.patch(f"{BASE}/{uid}", json={"replicas": 3})
        assert r.status_code == 200
        body = r.json()
        assert body["replicas"]["desired"] == 3

    def test_replica_count_reflects_in_get(self, http):
        uid = TestDeploymentLifecycle.created_uid
        # wait for rollout
        time.sleep(5)
        r = http.get(f"{BASE}/{uid}")
        assert r.status_code == 200
        assert r.json()["replicas"]["desired"] == 3

    def test_scale_down(self, http):
        uid = TestDeploymentLifecycle.created_uid
        r = http.patch(f"{BASE}/{uid}", json={"replicas": 1})
        assert r.status_code == 200
        assert r.json()["replicas"]["desired"] == 1

    def test_image_update_triggers_rollout(self, http):
        uid = TestDeploymentLifecycle.created_uid
        r = http.patch(f"{BASE}/{uid}", json={"image": "nginx:stable"})
        assert r.status_code == 200
        body = r.json()
        assert body["image"] == "nginx:stable"

    def test_restart(self, http):
        uid = TestDeploymentLifecycle.created_uid
        r = http.post(f"{BASE}/{uid}/restart")
        assert r.status_code == 200

    def test_delete(self, http):
        uid = TestDeploymentLifecycle.created_uid
        r = http.delete(f"{BASE}/{uid}")
        assert r.status_code == 204

    def test_gone_after_delete(self, http):
        uid = TestDeploymentLifecycle.created_uid
        # give cascade a moment
        time.sleep(3)
        r = http.get(f"{BASE}/{uid}")
        assert r.status_code == 404

    def test_duplicate_name_returns_409(self, http):
        # create fresh; then try to create again
        payload = {"name": "dup-test", "namespace": TEST_NS, "image": "nginx:latest"}
        r1 = http.post(BASE, json=payload)
        assert r1.status_code == 201
        uid = r1.json()["id"]

        r2 = http.post(BASE, json=payload)
        assert r2.status_code == 409

        # cleanup
        http.delete(f"{BASE}/{uid}")


# ── Bad image scenario ────────────────────────────────────────────────────────

class TestBadImage:
    bad_uid = None

    def test_bad_image_creates(self, http):
        r = http.post(BASE, json={
            "name": "bad-image-test",
            "namespace": TEST_NS,
            "image": "nginx:nonexistent-tag-xyz",
            "replicas": 1,
        })
        assert r.status_code == 201
        TestBadImage.bad_uid = r.json()["id"]

    def test_bad_image_reports_failing(self, http):
        uid = TestBadImage.bad_uid
        # ImagePullBackOff typically surfaces within ~60s
        result = wait_for_health(http, uid, "FAILING", retries=15, interval=6)
        assert result.get("health") == "FAILING", f"Got health={result.get('health')}"

    def test_bad_image_pod_shows_pull_error(self, http):
        uid = TestBadImage.bad_uid
        r = http.get(f"{BASE}/{uid}")
        assert r.status_code == 200
        pods = r.json().get("pods", [])
        reasons = []
        for pod in pods:
            for c in pod.get("containers", []):
                state = c.get("state") or {}
                reasons.append(state.get("reason", ""))
        # At least one container should show ImagePullBackOff or ErrImagePull
        pull_errors = {"ImagePullBackOff", "ErrImagePull"}
        assert any(r in pull_errors for r in reasons), f"No pull error in: {reasons}"

    def test_cleanup_bad_image(self, http):
        uid = TestBadImage.bad_uid
        if uid:
            http.delete(f"{BASE}/{uid}")
