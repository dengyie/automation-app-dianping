from automation_app_dianping.config import DianpingAppConfig


def test_dianping_app_config_holds_domain_fields():
    config = DianpingAppConfig(city="shanghai", app_id="com.dianping.v1")

    assert config.city == "shanghai"
    assert config.app_id == "com.dianping.v1"
