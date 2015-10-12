#!/usr/bin/env python
from __future__ import absolute_import, division, print_function, \
    unicode_literals
import os
import re
import sys
import time
import socket
try:
    import urllib.request as urllib
    import urllib.parse as urlparse
except ImportError:
    import urllib
    import urlparse
import hashlib
import argparse
import logging
import requests

from zeroconf import ServiceBrowser, Zeroconf

from . import utils

__all__ = ["get"]


class ServiceListener(object):
    """
    Custom zeroconf listener that is trying to find the service we're looking
    for.

    """
    filehash = ""
    address = None
    port = False

    def remove_service(*args):
        pass

    def add_service(self, zeroconf, type, name):
        if name == self.filehash + "._zget._http._tcp.local.":
            utils.logger.info("Peer found. Downloading...")
            info = zeroconf.get_service_info(type, name)
            if info:
                self.address = socket.inet_ntoa(info.address)
                self.port = info.port


def cli(inargs=None):
    """
    Commandline interface for receiving files

    """
    parser = argparse.ArgumentParser()

    parser.add_argument(
        '--verbose', '-v',
        action='count', default=0,
        help="Verbose mode. Multiple -v options increase the verbosity"
    )
    parser.add_argument(
        '--quiet', '-q',
        action='count', default=0,
        help="Quiet mode. Hides progess bar"
    )
    parser.add_argument(
        '--timeout', '-t',
        type=int, metavar="SECONDS",
        help="Set timeout after which program aborts transfer"
    )
    parser.add_argument(
        '--version', '-V',
        action='version',
        version='%%(prog)s %s' % utils.__version__
    )
    parser.add_argument(
        'filename',
        help="The filename to look for on the network"
    )
    parser.add_argument(
        'output',
        nargs='?',
        help="The local filename to save to"
    )
    args = parser.parse_args(inargs)

    utils.enable_logger(args.verbose)

    try:
        with utils.Progresshook(args.filename) as progress:
            get(
                args.filename,
                args.output,
                reporthook=progress if args.quiet == 0 else None,
                timeout=args.timeout
            )
    except Exception as e:
        if args.verbose:
            raise
        utils.logger.error(e.message)
        sys.exit(1)


def unique_filename(filename):
    if not os.path.exists(filename):
        return filename

    path, name = os.path.split(filename)
    name, ext = os.path.splitext(name)

    def make_filename(i):
        return os.path.join(path, '%s_%d%s' % (name, i, ext))

    for i in xrange(1, sys.maxint):
        unique_filename = make_filename(i)
        if not os.path.exists(unique_filename):
            return unique_filename

    raise FileExistsError()


def urlretrieve(
    url,
    output=None,
    reporthook=None
):
    r = requests.get(url, stream=True)
    try:
        maxsize = int(r.headers['content-length'])
    except KeyError:
        maxsize = -1

    if output is None:
        try:
            filename = re.findall(
                "filename=(\S+)", r.headers['content-disposition']
            )[0].strip('\'"')
        except (IndexError, KeyError):
            filename = urlparse.unquote(
                os.path.basename(urlparse.urlparse(url).path)
            )
        filename = unique_filename(filename)
        reporthook.filename = filename
    else:
        filename = output

    with open(filename, 'wb') as f:
        for i, chunk in enumerate(r.iter_content(chunk_size=1024 * 8)):
            if chunk:
                f.write(chunk)
                if reporthook is not None:
                    reporthook(i, 1024 * 8, maxsize)


def get(
    filename,
    output=None,
    reporthook=None,
    timeout=None
):
    """Receive and save a file using the zget protocol.

    Parameters
    ----------
    filename : string
        The filename to be transferred
    output : string
        The filename to save to. Optional.
    reporthook : callable
        A hook that will be called during transfer. Handy for watching the
        transfer. See :code:`urllib.urlretrieve` for callback parameters.
        Optional.
    timeout : int
        Seconds to wait until process is aborted. A running transfer is not
        aborted even when timeout was hit. Optional.

    Raises
    -------
    TimeoutException
        When a timeout occurred.

    """
    basename = os.path.basename(filename)
    filehash = hashlib.sha1(basename.encode('utf-8')).hexdigest()

    zeroconf = Zeroconf()
    listener = ServiceListener()
    listener.filehash = filehash

    utils.logger.debug("Looking for " + filehash + "._zget._http._tcp.local.")

    browser = ServiceBrowser(zeroconf, "_zget._http._tcp.local.", listener)

    start_time = time.time()
    try:
        while listener.address is None:
            time.sleep(0.5)
            if (
                timeout is not None and
                time.time() - start_time > timeout
            ):
                zeroconf.close()
                raise utils.TimeoutException()

        utils.logger.debug(
            "Downloading from %s:%d" % (listener.address, listener.port)
        )
        url = "http://" + listener.address + ":" + str(listener.port) + "/" + \
              urllib.pathname2url(filename)

        urlretrieve(
            url, output,
            reporthook=reporthook
        )
    except KeyboardInterrupt:
        pass
    utils.logger.info("Done.")
    zeroconf.close()

if __name__ == '__main__':
    cli(sys.argv[1:])
