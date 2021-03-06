# -*- coding: utf-8 -*-
# test_blobs_server.py
# Copyright (C) 2017 LEAP
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
"""
Integration tests for blobs server
"""
import pytest
from io import BytesIO
from twisted.trial import unittest
from twisted.web.server import Site
from twisted.internet import reactor
from twisted.internet import defer
from leap.soledad.server import _blobs as server_blobs
from leap.soledad.client._blobs import BlobManager, BlobAlreadyExistsError


class BlobServerTestCase(unittest.TestCase):

    def setUp(self):
        root = server_blobs.BlobsResource(self.tempdir)
        site = Site(root)
        self.port = reactor.listenTCP(0, site, interface='127.0.0.1')
        self.host = self.port.getHost()
        self.uri = 'http://%s:%s/' % (self.host.host, self.host.port)
        self.secret = 'A' * 96

    def tearDown(self):
        self.port.stopListening()

    @defer.inlineCallbacks
    @pytest.mark.usefixtures("method_tmpdir")
    def test_upload_download(self):
        manager = BlobManager('', self.uri, self.secret,
                              self.secret, 'user')
        fd = BytesIO("save me")
        yield manager._encrypt_and_upload('blob_id', fd)
        blob, size = yield manager._download_and_decrypt('blob_id')
        self.assertEquals(blob.getvalue(), "save me")

    @defer.inlineCallbacks
    @pytest.mark.usefixtures("method_tmpdir")
    def test_upload_changes_remote_list(self):
        manager = BlobManager('', self.uri, self.secret,
                              self.secret, 'user')
        yield manager._encrypt_and_upload('blob_id1', BytesIO("1"))
        yield manager._encrypt_and_upload('blob_id2', BytesIO("2"))
        blobs_list = yield manager.remote_list()
        self.assertEquals(set(['blob_id1', 'blob_id2']), set(blobs_list))

    @defer.inlineCallbacks
    @pytest.mark.usefixtures("method_tmpdir")
    def test_upload_deny_duplicates(self):
        manager = BlobManager('', self.uri, self.secret,
                              self.secret, 'user')
        fd = BytesIO("save me")
        yield manager._encrypt_and_upload('blob_id', fd)
        fd = BytesIO("save me")
        with pytest.raises(BlobAlreadyExistsError):
            yield manager._encrypt_and_upload('blob_id', fd)
