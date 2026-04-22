from kubernetes import client, config


def init_k8s():
    """Load K8s configuration — in-cluster first, then kubeconfig."""
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def get_apps_v1() -> client.AppsV1Api:
    return client.AppsV1Api()


def get_core_v1() -> client.CoreV1Api:
    return client.CoreV1Api()
