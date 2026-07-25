from bot.constants import DragonflyCluster


def test_dragonfly_cluster_redacts_access_secret() -> None:
    cluster = DragonflyCluster.model_validate(
        {
            "api_url": "https://dragonfly-staging.vipyrsec.com",
            "access_client_id": "staging-client",
            "access_client_secret": "staging-secret",
        }
    )

    assert cluster.access_client_secret.get_secret_value() == "staging-secret"
    assert "staging-secret" not in repr(cluster)
