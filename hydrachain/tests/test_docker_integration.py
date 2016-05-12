from collections import OrderedDict
import os
from os.path import abspath, dirname, join
import socket
from urlparse import urlsplit
import time
from logging import getLogger
import operator

from pyethapp.rpc_client import JSONRPCClient as OrigJSONRPCClient
import pytest
from requests.exceptions import RequestException
from tinyrpc.transports.http import HttpPostClientTransport

pytest.importorskip('compose', minversion="1.7.0")

try:
    from compose.cli.command import get_project, get_client
except ImportError:
    pass

log = getLogger(__name__)

JSONRPC_PORT = 4000
PROJECT_NAME = "hydrachaintest"
SERVICE_SCALE = OrderedDict((
    ('statsmon', 1),
    ('bootstrap', 1),
    ('node', 3),
))


try:
    get_client(os.environ).info()
except RequestException:
    pytest.skip("Unable to connect to docker daemon. Skipping docker tests.")


# Taken from http://stackoverflow.com/questions/12411431
def pytest_runtest_makereport(item, call):
    if "incremental" in item.keywords:
        if call.excinfo is not None:
            parent = item.parent
            parent._previousfailed = item


# Taken from http://stackoverflow.com/questions/12411431
def pytest_runtest_setup(item):
    previousfailed = getattr(item.parent, "_previousfailed", None)
    if previousfailed is not None:
        pytest.xfail("previous test failed (%s)" % previousfailed.name)


class DockerHarness(object):

    def __init__(self):
        self.base_dir = abspath(join(dirname(__file__), "..", "..", "docker", "dev", "hydrachain"))

        self.docker_host = None
        if os.environ.get('DOCKER_HOST'):
            self.docker_host = urlsplit(os.environ['DOCKER_HOST']).netloc.partition(":")[0]

        # This needs to happen before the `get_project()` call below since it caches os.environ.
        os.environ['HYDRACHAIN_HOST_PREFIX'] = PROJECT_NAME

        self.project = get_project(self.base_dir, project_name=PROJECT_NAME)
        self._modify_service_config()
        self.project.build()

    def _modify_service_config(self):
        """
        Modify the services configurations to allow testing.
        """
        # Add exposed ports to `node`s
        self.project.get_service('node').options['ports'] = ["4000"]

        # Remove localhost binding from `bootstrap` to ensure we can connect
        # (even under boot2docker, etc.)
        # FIXME: Find better general solution for this
        bootstrap = self.project.get_service('bootstrap')
        bootstrap.options['ports'] = [p.replace("127.0.0.1:", "")
                                      for p in bootstrap.options['ports']]

        # Ensure `container_name` prefix matches test project name
        for service in self.project.services:
            container_name = service.options.get('container_name')
            if container_name:
                service.options['container_name'] = container_name.replace("hydrachain",
                                                                           PROJECT_NAME)

    def start(self):
        for service_name, scale in SERVICE_SCALE.items():
            self.project.get_service(service_name).scale(scale)

    @property
    def containers_running(self):
        if len(self.project.containers()) < sum(SERVICE_SCALE.values()):
            for container in self.project.containers(stopped=True):
                if not container.is_running:
                    print(container.logs())
            return False
        return True

    def stop(self, remove=True):
        self.project.stop()
        if remove:
            self.project.remove_stopped()

    @property
    def rpc_ports(self):
        return [
            self._transform_netloc(container.get_local_port(JSONRPC_PORT))
            for container in self.hydrachain_containers
        ]

    @property
    def hydrachain_containers(self):
        for c in self._containers(["node", "bootstrap"]):
            yield c

    @property
    def stats_container(self):
        try:
            return next(self._containers(["statsmon"]))
        except StopIteration:
            return None

    def _containers(self, service_names):
        for service in self.project.get_services(service_names):
            for container in service.containers():
                yield container

    def _transform_netloc(self, netloc):
        if not self.docker_host:
            return netloc
        _, sep, port = netloc.partition(":")
        return sep.join([self.docker_host, port])


class JSONRPCClient(OrigJSONRPCClient):

    def __init__(self, host="127.0.0.1", port=4000, print_communication=True, privkey=None,
                 sender=None):
        super(JSONRPCClient, self).__init__(port, print_communication, privkey, sender)
        self.transport = HttpPostClientTransport("http://{}:{}".format(host, port))


@pytest.yield_fixture(scope='module')
def docker_harness():
    try:
        harness = DockerHarness()
    except RequestException:
        pytest.skip("Can't connect to docker daemon")
        return
    harness.start()
    yield harness
    for container in harness.hydrachain_containers:
        print(container.logs())
    harness.stop()


def _can_connect(target):
    sock = socket.socket()
    sock.settimeout(.1)
    try:
        host, port = target.split(":")
        port = int(port)
        sock.connect((host, port))
        return True
    except socket.error:
        return False
    finally:
        sock.close()


def _get_block_no(target):
    client = JSONRPCClient(*target.split(":"))
    try:
        return client.blocknumber()
    except RequestException:
        return None


def wait_callback_or_timeout(callback, timeout, interval=.5):
    start = time.time()
    while time.time() - start < timeout:
        if callback():
            return True
        time.sleep(interval)
    return False


# The `incremental` mark causes one failure to abort all following tests in this class
@pytest.mark.incremental
class TestDockerSetup(object):

    # Since we're (usually) runnnig tests serially the wait times are cumulative

    @pytest.mark.parametrize('wait', (0, 1, 4, 5, 5))
    def test_containers_up(self, docker_harness, wait):
        """
        Ensure the containers keep running after increasing amounts of time have elapsed.
        """
        time.sleep(wait)
        assert docker_harness.containers_running

    def test_all_nodes_rpc_connectable(self, docker_harness):
        targets = docker_harness.rpc_ports
        assert wait_callback_or_timeout(
            lambda: all(_can_connect(target) for target in targets),
            60
        )

    @pytest.mark.parametrize(('block_no', 'op', 'timeout'),
                             ((1, operator.ge, 120),
                              (10, operator.eq, 25),
                              ))
    def test_all_nodes_reach_block_no(self, docker_harness, block_no, op, timeout):
        targets = docker_harness.rpc_ports
        assert wait_callback_or_timeout(
            lambda: all(op(_get_block_no(target), block_no) for target in targets),
            timeout,
            interval=2
        )

    # TODO: Fix bug and remove
    @pytest.mark.xfail(reason="Probable hydrachain bug")
    def test_transaction_increases_block_no(self, docker_harness):
        targets = docker_harness.rpc_ports
        client = JSONRPCClient(*(targets[0].split(":")))
        client.send_transaction(
            client.coinbase,
            "1" * 40,
            1
        )
        assert wait_callback_or_timeout(
            lambda: all(_get_block_no(target) == 101 for target in targets),
            10,
            interval=2
        )
