# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helper to start the Karma environment to run MAAS JS unit-tests."""

__all__ = [
    ]

import os
from subprocess import (
    CalledProcessError,
    check_output,
    Popen,
)

from maastesting.fixtures import DisplayFixture


def is_browser_available(browser):
    """Return True if browser is available."""
    try:
        check_output(('which', browser))
    except CalledProcessError:
        return False
    else:
        return True


def gen_available_browsers():
    """Find available browsers for the current system.

    Yields ``(name, environ)`` tuples, where ``name`` is passed to the runner,
    and ``environ`` is a dict of additional environment variables needed to
    run the given browser.
    """
    # PhantomJS is always enabled.
    yield "PhantomJS", {}

    # XXX: allenap bug=1427492 2015-03-03: Firefox has been very unreliable
    # both with Karma and with Selenium. Disabling it.
    # if is_browser_available("firefox"):
    #     yield "Firefox", {}

    # Prefer Chrome, but fall-back to Chromium.
    if is_browser_available("google-chrome"):
        yield "Chrome", {"CHROME_BIN": "google-chrome"}
    elif is_browser_available("chromium-browser"):
        yield "Chrome", {"CHROME_BIN": "chromium-browser"}

    if is_browser_available("opera"):
        yield "Opera", {}


def run_karma():
    """Start Karma with the MAAS JS testing configuration."""

    def run_with_browser(browser, env):
        """Run tests with a specific browser and environment."""
        command = (
            'include/nodejs/bin/node', 'bin/karma', 'start', '--single-run',
            '--no-colors', '--browsers', browser,
            'src/maastesting/karma.conf.js')
        karma = Popen(command, env=dict(os.environ, **env))
        return karma.wait()

    with DisplayFixture():
        for browser, env in gen_available_browsers():
            # run karma separately for each browser, since running multiple
            # browsers seems to tringger a buggy behavior in karma which makes
            # some tests fail with page reload (lp:1762344)
            ret = run_with_browser(browser, env)
            if ret:
                SystemExit(ret)
