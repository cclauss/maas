# Copyright 2005-2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the psmaas TAP."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = []

from functools import partial
import os

from maastesting.factory import factory
from maastesting.testcase import MAASTestCase
import provisioningserver
from provisioningserver import plugin as plugin_module
from provisioningserver.image_download_service import (
    PeriodicImageDownloadService,
    )
from provisioningserver.plugin import (
    Options,
    ProvisioningRealm,
    ProvisioningServiceMaker,
    SingleUsernamePasswordChecker,
    )
from provisioningserver.tftp import (
    TFTPBackend,
    TFTPService,
    )
from testtools.deferredruntest import (
    assert_fails_with,
    AsynchronousDeferredRunTest,
    )
from testtools.matchers import (
    AfterPreprocessing,
    Equals,
    IsInstance,
    MatchesAll,
    MatchesException,
    MatchesStructure,
    Raises,
    )
from twisted.application.service import MultiService
from twisted.cred.credentials import UsernamePassword
from twisted.cred.error import UnauthorizedLogin
from twisted.internet.defer import inlineCallbacks
from twisted.python.usage import UsageError
from twisted.web.resource import IResource
import yaml


class TestOptions(MAASTestCase):
    """Tests for `provisioningserver.plugin.Options`."""

    def test_defaults(self):
        options = Options()
        expected = {"config-file": "pserv.yaml"}
        self.assertEqual(expected, options.defaults)

    def check_exception(self, options, message, *arguments):
        # Check that a UsageError is raised when parsing options.
        self.assertThat(
            partial(options.parseOptions, arguments),
            Raises(MatchesException(UsageError, message)))

    def test_parse_minimal_options(self):
        options = Options()
        # The minimal set of options that must be provided.
        arguments = []
        options.parseOptions(arguments)  # No error.


class TestProvisioningServiceMaker(MAASTestCase):
    """Tests for `provisioningserver.plugin.ProvisioningServiceMaker`."""

    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=5)

    def setUp(self):
        super(TestProvisioningServiceMaker, self).setUp()
        self.patch(provisioningserver, "services", MultiService())
        self.tempdir = self.make_dir()
        cluster_uuid = factory.make_UUID()
        self.patch(plugin_module, 'get_cluster_uuid').return_value = (
            cluster_uuid)

    def write_config(self, config):
        config_filename = os.path.join(self.tempdir, "config.yaml")
        with open(config_filename, "wb") as stream:
            yaml.safe_dump(config, stream)
        return config_filename

    def test_init(self):
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        self.assertEqual("Harry", service_maker.tapname)
        self.assertEqual("Hill", service_maker.description)

    def test_makeService(self):
        """
        Only the site service is created when no options are given.
        """
        options = Options()
        options["config-file"] = self.write_config({})
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options)
        self.assertIsInstance(service, MultiService)
        self.assertSequenceEqual(
            ["image_download", "log", "oops", "rpc", "tftp"],
            sorted(service.namedServices))
        self.assertEqual(
            len(service.namedServices), len(service.services),
            "Not all services are named.")
        self.assertEqual(service, provisioningserver.services)

    def test_image_download_service(self):
        options = Options()
        options["config-file"] = self.write_config({})
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options)
        image_service = service.getServiceNamed("image_download")
        self.assertIsInstance(image_service, PeriodicImageDownloadService)

    def test_tftp_service(self):
        # A TFTP service is configured and added to the top-level service.
        config = {
            "tftp": {
                "generator": "http://candlemass/solitude",
                "resource_root": self.tempdir,
                "port": factory.pick_port(),
                },
            }
        options = Options()
        options["config-file"] = self.write_config(config)
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options)
        tftp_service = service.getServiceNamed("tftp")
        self.assertIsInstance(tftp_service, TFTPService)

        expected_backend = MatchesAll(
            IsInstance(TFTPBackend),
            AfterPreprocessing(
                lambda backend: backend.base.path,
                Equals(config["tftp"]["resource_root"])),
            AfterPreprocessing(
                lambda backend: backend.generator_url.geturl(),
                Equals(config["tftp"]["generator"])))

        self.assertThat(
            tftp_service, MatchesStructure(
                backend=expected_backend,
                port=Equals(config["tftp"]["port"]),
            ))


class TestSingleUsernamePasswordChecker(MAASTestCase):
    """Tests for `SingleUsernamePasswordChecker`."""

    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=5)

    @inlineCallbacks
    def test_requestAvatarId_okay(self):
        credentials = UsernamePassword("frank", "zappa")
        checker = SingleUsernamePasswordChecker("frank", "zappa")
        avatar = yield checker.requestAvatarId(credentials)
        self.assertEqual("frank", avatar)

    def test_requestAvatarId_bad(self):
        credentials = UsernamePassword("frank", "zappa")
        checker = SingleUsernamePasswordChecker("zap", "franka")
        d = checker.requestAvatarId(credentials)
        return assert_fails_with(d, UnauthorizedLogin)


class TestProvisioningRealm(MAASTestCase):
    """Tests for `ProvisioningRealm`."""

    def test_requestAvatar_okay(self):
        resource = object()
        realm = ProvisioningRealm(resource)
        avatar = realm.requestAvatar(
            "irrelevant", "also irrelevant", IResource)
        self.assertEqual((IResource, resource, realm.noop), avatar)

    def test_requestAvatar_bad(self):
        # If IResource is not amongst the interfaces passed to requestAvatar,
        # NotImplementedError is raised.
        resource = object()
        realm = ProvisioningRealm(resource)
        self.assertRaises(
            NotImplementedError, realm.requestAvatar,
            "irrelevant", "also irrelevant")
