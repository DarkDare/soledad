# -*- coding: utf-8 -*-
# _crypto.py
# Copyright (C) 2016 LEAP Encryption Access Project
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
Cryptographic operations for the soledad client
"""

import binascii
import base64
import hashlib
import hmac
import os
import struct
import time

from io import BytesIO
from cStringIO import StringIO
from collections import namedtuple

import six

from twisted.internet import defer
from twisted.internet import interfaces
from twisted.logger import Logger
from twisted.persisted import dirdbm
from twisted.web import client
from twisted.web.client import FileBodyProducer

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.hmac import HMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends.multibackend import MultiBackend
from cryptography.hazmat.backends.openssl.backend \
    import Backend as OpenSSLBackend

from zope.interface import implements

from leap.common.config import get_path_prefix


log = Logger()

MAC_KEY_LENGTH = 64

crypto_backend = MultiBackend([OpenSSLBackend()])


class ENC_SCHEME:
    symkey = 1


class ENC_METHOD:
    aes_256_ctr = 1


class EncryptionDecryptionError(Exception):
    pass


class InvalidBlob(Exception):
    pass


docinfo = namedtuple('docinfo', 'doc_id rev')


class SoledadCrypto(object):

    def __init__(self, secret):
        self.secret = secret

    def encrypt_doc(self, doc):

        def put_raw(blob):
            raw = blob.getvalue()
            return '{"raw": "' + raw + '"}'

        content = BytesIO()
        content.write(str(doc.get_json()))
        info = docinfo(doc.doc_id, doc.rev)
        del doc
        encryptor = BlobEncryptor(info, content, secret=self.secret)
        d = encryptor.encrypt()
        d.addCallback(put_raw)
        return d

    def decrypt_doc(self, doc):
        info = docinfo(doc.doc_id, doc.rev)
        ciphertext = BytesIO()
        payload = doc.content['raw']
        del doc
        ciphertext.write(str(payload))
        decryptor = BlobDecryptor(info, ciphertext, secret=self.secret)
        buf = decryptor.decrypt()
        return buf.getvalue()


def encrypt_sym(data, key):
    iv = os.urandom(16)
    encryptor = AESEncryptor(key, iv)
    encryptor.write(data)
    encryptor.end()
    ciphertext = encryptor.fd.getvalue()
    return base64.b64encode(iv), ciphertext


def decrypt_sym(data, key, iv):
    _iv = base64.b64decode(str(iv))
    decryptor = AESDecryptor(key, _iv)
    decryptor.write(data)
    decryptor.end()
    plaintext = decryptor.fd.getvalue()
    return plaintext


class BlobEncryptor(object):

    """
    Encrypts a payload associated with a given Document.
    """

    def __init__(self, doc_info, content_fd, result=None, secret=None,
                 iv=None):
        if iv is None:
            iv = os.urandom(16)
        else:
            log.warn('Using a fixed IV. Use only for testing!')
        self.iv = iv
        if not secret:
            raise EncryptionDecryptionError('no secret given')

        self.doc_id = doc_info.doc_id
        self.rev = doc_info.rev

        content_fd.seek(0)
        self._producer = FileBodyProducer(content_fd, readSize=2**16)
        self._content_fd = content_fd

        self._preamble = BytesIO()
        if result is None:
            result = BytesIO()
        self.result = result

        sym_key = _get_sym_key_for_doc(doc_info.doc_id, secret)
        mac_key = _get_mac_key_for_doc(doc_info.doc_id, secret)

        self._aes_fd = BytesIO()
        self._aes = AESEncryptor(sym_key, self.iv, self._aes_fd)
        self._hmac = HMACWriter(mac_key)
        self._write_preamble()

        self._crypter = VerifiedEncrypter(self._aes, self._hmac)

    def encrypt(self):
        d = self._producer.startProducing(self._crypter)
        d.addCallback(self._end_crypto_stream)
        return d

    def encrypt_whole(self):
        self._crypter.write(self._content_fd.getvalue())
        self._end_crypto_stream(None)
        return '{"raw":"' + self.result.getvalue() + '"}'

    def _write_preamble(self):

        def write(data):
            self._preamble.write(data)
            self._hmac.write(data)

        current_time = int(time.time())

        write(b'\x80')
        write(struct.pack(
            'Qbb',
            current_time,
            ENC_SCHEME.symkey,
            ENC_METHOD.aes_256_ctr))
        write(self.iv)
        write(str(self.doc_id))
        write(str(self.rev))

    def _end_crypto_stream(self, ignored):
        self._aes.end()
        self._hmac.end()
        self._content_fd.close()

        preamble = self._preamble.getvalue()
        encrypted = self._aes_fd.getvalue()
        hmac = self._hmac.result.getvalue()

        self.result.write(
            base64.urlsafe_b64encode(preamble + encrypted + hmac))
        self._preamble.close()
        self._aes_fd.close()
        self._hmac.result.close()
        self.result.seek(0)
        return defer.succeed(self.result)


class BlobDecryptor(object):
    """
    Decrypts an encrypted blob associated with a given Document.

    Will raise an exception if the blob doesn't have the expected structure, or
    if the HMAC doesn't verify.
    """

    def __init__(self, doc_info, ciphertext_fd, result=None,
                 secret=None):
        self.doc_id = doc_info.doc_id
        self.rev = doc_info.rev

        self.ciphertext = ciphertext_fd

        self.sym_key = _get_sym_key_for_doc(doc_info.doc_id, secret)
        self.mac_key = _get_mac_key_for_doc(doc_info.doc_id, secret)

        if result is None:
            result = BytesIO()
        self.result = result

    def decrypt(self):
        try:
            data = base64.urlsafe_b64decode(self.ciphertext.getvalue())
        except (TypeError, binascii.Error):
            raise InvalidBlob
        self.ciphertext.close()

        current_time = int(time.time())
        if not data or six.indexbytes(data, 0) != 0x80:
            raise InvalidBlob
        try:
            ts, sch, meth = struct.unpack("Qbb", data[1:11])
        except struct.error:
            raise InvalidBlob

        # TODO check timestamp
        if sch != ENC_SCHEME.symkey:
            raise InvalidBlob('invalid scheme')
        # TODO should adapt the assymetric-gpg too, rigth?
        if meth != ENC_METHOD.aes_256_ctr:
            raise InvalidBlob('invalid encryption scheme')

        iv = data[11:27]
        docidlen = len(self.doc_id)
        ciph_idx = 26 + docidlen
        doc_id = data[26:ciph_idx]
        revlen = len(self.rev)
        rev_idx = ciph_idx + 1 + revlen
        rev = data[ciph_idx + 1:rev_idx]

        if rev != self.rev:
            raise InvalidBlob('invalid revision')

        ciphertext = data[rev_idx:-64]
        hmac = data[-64:]

        h = HMAC(self.mac_key, hashes.SHA512(), backend=crypto_backend)
        h.update(data[:-64])
        try:
            h.verify(hmac)
        except InvalidSignature:
            raise InvalidBlob('HMAC could not be verifed')

        decryptor = _get_aes_ctr_cipher(self.sym_key, iv).decryptor()

        # TODO pass chunks, streaming, instead
        # Use AESDecryptor below

        self.result.write(decryptor.update(ciphertext))
        self.result.write(decryptor.finalize())
        return self.result


class AESEncryptor(object):

    implements(interfaces.IConsumer)

    def __init__(self, key, iv, fd=None):
        if len(key) != 32:
            raise EncryptionDecryptionError('key is not 256 bits')
        if len(iv) != 16:
            raise EncryptionDecryptionError('iv is not 128 bits')

        cipher = _get_aes_ctr_cipher(key, iv)
        self.encryptor = cipher.encryptor()

        if fd is None:
            fd = BytesIO()
        self.fd = fd

        self.done = False

    def write(self, data):
        encrypted = self.encryptor.update(data)
        self.fd.write(encrypted)
        return encrypted

    def end(self):
        if not self.done:
            final = self.encryptor.finalize()
        self.done = True


class HMACWriter(object):

    implements(interfaces.IConsumer)
    hashtype = 'sha512'

    def __init__(self, key):
        self._hmac = hmac.new(key, '', getattr(hashlib, self.hashtype))
        self.result = BytesIO('')

    def write(self, data):
        self._hmac.update(data)

    def end(self):
        self.result.write(self._hmac.digest())


class VerifiedEncrypter(object):

    implements(interfaces.IConsumer)

    def __init__(self, crypter, hmac):
        self.crypter = crypter
        self.hmac = hmac

    def write(self, data):
        enc_chunk = self.crypter.write(data)
        self.hmac.write(enc_chunk)


class AESDecryptor(object):

    implements(interfaces.IConsumer)

    def __init__(self, key, iv, fd=None):
        if iv is None:
            iv = os.urandom(16)
        if len(key) != 32:
            raise EncryptionhDecryptionError('key is not 256 bits')
        if len(iv) != 16:
            raise EncryptionDecryptionError('iv is not 128 bits')

        cipher = _get_aes_ctr_cipher(key, iv)
        self.decryptor = cipher.decryptor()

        if fd is None:
            fd = BytesIO()
        self.fd = fd
        self.done = False
        self.deferred = defer.Deferred()

    def write(self, data):
        decrypted = self.decryptor.update(data)
        self.fd.write(decrypted)
        return decrypted

    def end(self):
        if not self.done:
            self.decryptor.finalize()
            self.deferred.callback(self.fd)
        self.done = True


def is_symmetrically_encrypted(payload):
    header = base64.urlsafe_b64decode(enc[:15] + '===')
    ts, sch, meth = struct.unpack('Qbb', header[1:11])
    return sch == ENC_SCHEME.symkey


# utils


def _hmac_sha256(key, data):
    return hmac.new(key, data, hashlib.sha256).digest()


def _get_mac_key_for_doc(doc_id, secret):
    key = secret[:MAC_KEY_LENGTH]
    return _hmac_sha256(key, doc_id)


def _get_sym_key_for_doc(doc_id, secret):
    key = secret[MAC_KEY_LENGTH:]
    return _hmac_sha256(key, doc_id)


def _get_aes_ctr_cipher(key, iv):
    return Cipher(algorithms.AES(key), modes.CTR(iv), backend=crypto_backend)