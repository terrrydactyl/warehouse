# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from unittest import mock

import fs.opener
import pretend
import pytest

from pyramid import renderers
from pyramid.httpexceptions import HTTPMovedPermanently

from warehouse import config


class TestCSPTween:

    def test_csp_policy(self):
        response = pretend.stub(headers={})
        handler = pretend.call_recorder(lambda request: response)
        registry = pretend.stub(
            settings={
                "csp": {
                    "default-src": ["*"],
                    "style-src": ["'self'", "example.net"],
                },
            },
        )

        tween = config.content_security_policy_tween_factory(handler, registry)

        request = pretend.stub(path="/project/foobar/")

        assert tween(request) is response
        assert response.headers == {
            "Content-Security-Policy":
                "default-src *; style-src 'self' example.net",
        }

    def test_csp_policy_debug_disables(self):
        response = pretend.stub(headers={})
        handler = pretend.call_recorder(lambda request: response)
        registry = pretend.stub(
            settings={
                "csp": {
                    "default-src": ["*"],
                    "style-src": ["'self'", "example.net"],
                },
            },
        )

        tween = config.content_security_policy_tween_factory(handler, registry)

        request = pretend.stub(path="/_debug_toolbar/foo/")

        assert tween(request) is response
        assert response.headers == {}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/foo/bar/", True),
        ("/static/wat/", False),
        ("/_debug_toolbar/thing/", False),
    ],
)
def test_activate_hook(path, expected):
    request = pretend.stub(path=path)
    assert config.activate_hook(request) == expected


@pytest.mark.parametrize(
    ("environ", "name", "envvar", "coercer", "default", "expected"),
    [
        ({}, "test.foo", "TEST_FOO", None, None, {}),
        (
            {"TEST_FOO": "bar"}, "test.foo", "TEST_FOO", None, None,
            {"test.foo": "bar"},
        ),
        (
            {"TEST_INT": "1"}, "test.int", "TEST_INT", int, None,
            {"test.int": 1},
        ),
        ({}, "test.foo", "TEST_FOO", None, "lol", {"test.foo": "lol"}),
        (
            {"TEST_FOO": "bar"}, "test.foo", "TEST_FOO", None, "lol",
            {"test.foo": "bar"},
        ),
    ],
)
def test_maybe_set(monkeypatch, environ, name, envvar, coercer, default,
                   expected):
    for key, value in environ.items():
        monkeypatch.setenv(key, value)
    settings = {}
    config.maybe_set(settings, name, envvar, coercer=coercer, default=default)
    assert settings == expected


@pytest.mark.parametrize(
    ("environ", "base", "name", "envvar", "expected"),
    [
        ({}, "test", "foo", "TEST_FOO", {}),
        ({"TEST_FOO": "bar"}, "test", "foo", "TEST_FOO", {"test.foo": "bar"}),
        (
            {"TEST_FOO": "bar thing=other"}, "test", "foo", "TEST_FOO",
            {"test.foo": "bar", "test.thing": "other"},
        ),
        (
            {"TEST_FOO": "bar thing=other wat=\"one two\""},
            "test", "foo", "TEST_FOO",
            {"test.foo": "bar", "test.thing": "other", "test.wat": "one two"},
        ),
    ],
)
def test_maybe_set_compound(monkeypatch, environ, base, name, envvar,
                            expected):
    for key, value in environ.items():
        monkeypatch.setenv(key, value)
    settings = {}
    config.maybe_set_compound(settings, base, name, envvar)
    assert settings == expected


@pytest.mark.parametrize(
    ("settings", "environment"),
    [
        (None, config.Environment.production),
        ({}, config.Environment.production),
        ({"my settings": "the settings value"}, config.Environment.production),
        (None, config.Environment.development),
        ({}, config.Environment.development),
        (
            {"my settings": "the settings value"},
            config.Environment.development,
        ),
    ],
)
def test_configure(monkeypatch, settings, environment):
    fs_obj = pretend.stub()
    opener = pretend.call_recorder(lambda path, create_dir: fs_obj)
    monkeypatch.setattr(fs.opener, "fsopendir", opener)

    json_renderer_obj = pretend.stub()
    json_renderer_cls = pretend.call_recorder(lambda **kw: json_renderer_obj)
    monkeypatch.setattr(renderers, "JSON", json_renderer_cls)

    if environment == config.Environment.development:
        monkeypatch.setenv("WAREHOUSE_ENV", "development")

    class FakeRegistry(dict):
        def __init__(self):
            self.settings = {
                "warehouse.env": environment,
                "camo.url": "http://camo.example.com/",
                "pyramid.reload_assets": False,
                "dirs.packages": "/srv/data/pypi/packages/",
            }

    configurator_settings = {}
    configurator_obj = pretend.stub(
        registry=FakeRegistry(),
        include=pretend.call_recorder(lambda include: None),
        add_renderer=pretend.call_recorder(lambda name, renderer: None),
        add_jinja2_renderer=pretend.call_recorder(lambda renderer: None),
        add_jinja2_search_path=pretend.call_recorder(lambda path, name: None),
        get_settings=lambda: configurator_settings,
        add_settings=pretend.call_recorder(
            lambda d: configurator_settings.update(d)
        ),
        add_tween=pretend.call_recorder(lambda tween_factory: None),
        add_notfound_view=pretend.call_recorder(lambda append_slash: None),
        add_static_view=pretend.call_recorder(
            lambda name, path, cachebust: None
        ),
        scan=pretend.call_recorder(lambda ignore: None),
    )
    configurator_cls = pretend.call_recorder(lambda settings: configurator_obj)
    monkeypatch.setattr(config, "Configurator", configurator_cls)

    cachebuster_obj = pretend.stub()
    cachebuster_cls = pretend.call_recorder(lambda m, cache: cachebuster_obj)
    monkeypatch.setattr(config, "WarehouseCacheBuster", cachebuster_cls)

    transaction_manager = pretend.stub()
    transaction = pretend.stub(
        TransactionManager=pretend.call_recorder(lambda: transaction_manager),
    )
    monkeypatch.setattr(config, "transaction", transaction)

    result = config.configure(settings=settings)

    expected_settings = {
        "warehouse.env": environment,
        "site.name": "Warehouse",
    }

    if environment == config.Environment.development:
        expected_settings.update({
            "pyramid.reload_templates": True,
            "pyramid.reload_assets": True,
            "pyramid.prevent_http_cache": True,
            "debugtoolbar.hosts": ["0.0.0.0/0"],
            "debugtoolbar.panels": [
                "pyramid_debugtoolbar.panels.versions.VersionDebugPanel",
                "pyramid_debugtoolbar.panels.settings.SettingsDebugPanel",
                "pyramid_debugtoolbar.panels.headers.HeaderDebugPanel",
                (
                    "pyramid_debugtoolbar.panels.request_vars."
                    "RequestVarsDebugPanel"
                ),
                "pyramid_debugtoolbar.panels.renderings.RenderingsDebugPanel",
                "pyramid_debugtoolbar.panels.logger.LoggingPanel",
                (
                    "pyramid_debugtoolbar.panels.performance."
                    "PerformanceDebugPanel"
                ),
                "pyramid_debugtoolbar.panels.routes.RoutesDebugPanel",
                "pyramid_debugtoolbar.panels.sqla.SQLADebugPanel",
                "pyramid_debugtoolbar.panels.tweens.TweensDebugPanel",
                (
                    "pyramid_debugtoolbar.panels.introspection."
                    "IntrospectionDebugPanel"
                ),
            ],
        })

    if settings is not None:
        expected_settings.update(settings)

    assert configurator_cls.calls == [pretend.call(settings=expected_settings)]
    assert result is configurator_obj
    assert configurator_obj.include.calls == (
        [
            pretend.call(x) for x in [
                (
                    "pyramid_debugtoolbar"
                    if environment == config.Environment.development else None
                ),
            ]
            if x is not None
        ]
        +
        [
            pretend.call(".logging"),
            pretend.call("pyramid_jinja2"),
            pretend.call("pyramid_tm"),
            pretend.call("pyramid_services"),
            pretend.call(".legacy.action_routing"),
            pretend.call(".i18n"),
            pretend.call(".db"),
            pretend.call(".aws"),
            pretend.call(".sessions"),
            pretend.call(".cache.http"),
            pretend.call(".cache.origin"),
            pretend.call(".csrf"),
            pretend.call(".accounts"),
            pretend.call(".packaging"),
            pretend.call(".redirects"),
            pretend.call(".routes"),
        ]
    )
    assert configurator_obj.add_jinja2_renderer.calls == [
        pretend.call(".html"),
    ]
    assert configurator_obj.add_jinja2_search_path.calls == [
        pretend.call("warehouse:templates", name=".html"),
    ]
    assert configurator_obj.add_settings.calls == [
        pretend.call({"jinja2.newstyle": True}),
        pretend.call({
            "tm.attempts": 3,
            "tm.manager_hook": mock.ANY,
            "tm.activate_hook": config.activate_hook,
            "tm.annotate_user": False,
        }),
        pretend.call({
            "csp": {
                "default-src": ["'none'"],
                "frame-ancestors": ["'none'"],
                "img-src": [
                    "'self'",
                    "http://camo.example.com/",
                    "https://secure.gravatar.com",
                ],
                "referrer": ["cross-origin"],
                "reflected-xss": ["block"],
                "script-src": ["'self'"],
                "style-src": ["'self'"],
            },
        }),
    ]
    add_settings_dict = configurator_obj.add_settings.calls[1].args[0]
    assert add_settings_dict["tm.manager_hook"](pretend.stub()) is \
        transaction_manager
    assert configurator_obj.add_tween.calls == [
        pretend.call("warehouse.config.content_security_policy_tween_factory"),
    ]
    assert configurator_obj.registry["filesystems"] == {"packages": fs_obj}
    assert configurator_obj.add_static_view.calls == [
        pretend.call(
            name="static",
            path="warehouse:static",
            cachebust=cachebuster_obj,
        ),
    ]
    assert cachebuster_cls.calls == [
        pretend.call("warehouse:static/manifest.json", cache=True),
    ]
    assert configurator_obj.scan.calls == [
        pretend.call(ignore=["warehouse.migrations.env"]),
    ]
    assert opener.calls == [
        pretend.call("/srv/data/pypi/packages/", create_dir=True),
    ]
    assert configurator_obj.add_notfound_view.calls == [
        pretend.call(append_slash=HTTPMovedPermanently),
    ]
    assert configurator_obj.add_renderer.calls == [
        pretend.call("json", json_renderer_obj),
    ]

    assert json_renderer_cls.calls == [
        pretend.call(sort_keys=True, separators=(",", ":")),
    ]
