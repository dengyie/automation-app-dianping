def test_app_package_imports():
    from automation_app_dianping import __version__
    from automation_app_dianping import composition, config, live, services, session, storage, workflow

    assert __version__ == "0.3.0"
    assert composition.build_composition
    assert config.DianpingAppConfig
    assert live.live_enabled
    assert session.build_session_factory
    assert services.prepare_publish_checklist
    assert storage.DraftStore
    assert workflow.create_workflow


def test_workflow_module_does_not_import_slidex_on_load():
    import automation_app_dianping.workflow as module

    source = open(module.__file__, encoding="utf-8").read()
    assert "slidex" not in source
