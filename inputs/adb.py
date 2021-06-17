#!/usr/bin/python3
#-*- encoding: Utf-8 -*-
import os
from subprocess import Popen, run, PIPE, DEVNULL, STDOUT, TimeoutExpired, list2cmdline
from socket import socket, AF_INET, SOCK_STREAM
from os.path import realpath, dirname
from sys import stderr, platform
from logging import debug
from shutil import which
from time import sleep
from re import search

try:
  from os import setpgrp
except ImportError:
  setpgrp = None

from inputs._hdlc_mixin import HdlcMixin
from inputs._base_input import BaseInput

INPUTS_DIR = dirname(realpath(__file__))
ROOT_DIR = realpath(INPUTS_DIR + '/..')
ADB_BRIDGE_DIR = realpath(INPUTS_DIR + '/adb_bridge')
ADB_BIN_DIR = realpath(INPUTS_DIR + '/external/adb')

ANDROID_TMP_DIR = '/data/local/tmp'

# Print adb output to stdout when "-v" is passed to QCSuper


QCSUPER_TCP_PORT = 43555


class AdbConnector(HdlcMixin, BaseInput):

  def __init__(self):

    self.ADB_TIMEOUT = 10

    # Launch the adb_bridge
    self._relaunch_adb_bridge()

    self.socket = socket(AF_INET, SOCK_STREAM)
    try:
      self.socket.connect(('localhost', QCSUPER_TCP_PORT))
    except:
      self.adb_proc.terminate()
      exit('Could not communicate with the adb_bridge through TCP')

    self.packet_buffer = b''
    super().__init__()

  def _relaunch_adb_bridge(self):
    if hasattr(self, 'adb_proc'):
      self.adb_proc.terminate()
    os.system("killall -q ./adb_bridge")

    self.adb_proc = Popen(["/data/openpilot/selfdrive/debug/modem/QCSuper/inputs/adb_bridge/adb_bridge"],
      stdin = DEVNULL, stdout = PIPE, stderr = STDOUT,
      preexec_fn = setpgrp,
      bufsize = 0, universal_newlines = True
    )

    for line in self.adb_proc.stdout:
      if 'Connection to Diag established' in line:
        break
      else:
        stderr.write(line)
        stderr.flush()

    print("init ok")

    self.received_first_packet = False

  def __del__(self):
    try:
      if hasattr(self, 'adb_proc'):
        self.adb_proc.terminate()
    except Exception:
      pass

  def send_request(self, packet_type, packet_payload):
    raw_payload = self.hdlc_encapsulate(bytes([packet_type]) + packet_payload)
    self.socket.send(raw_payload)

  def get_gps_location(self):
    return None, None

  def read_loop(self):
    while True:
      while self.TRAILER_CHAR not in self.packet_buffer:
        # Read message from the TCP socket
        socket_read = self.socket.recv(1024 * 1024 * 10)
        if not socket_read:
          print('\nThe connection to the adb bridge was closed, or ' +
                'preempted by another QCSuper instance')
          return

        self.packet_buffer += socket_read

      while self.TRAILER_CHAR in self.packet_buffer:
        # Parse frame
        raw_payload, self.packet_buffer = self.packet_buffer.split(self.TRAILER_CHAR, 1)

        # Decapsulate and dispatch
        try:
          unframed_message = self.hdlc_decapsulate(
              payload = raw_payload + self.TRAILER_CHAR,
              raise_on_invalid_frame = not self.received_first_packet
          )
        except self.InvalidFrameError:
          # The first packet that we receive over the Diag input may
          # be partial
          continue

        finally:
          self.received_first_packet = True
        self.dispatch_received_diag_packet(unframed_message)

