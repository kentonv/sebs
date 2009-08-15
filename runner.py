# Scalable Extendable Build System
# Copyright (c) 2009 Kenton Varda and contributors.  All rights reserved.
# Portions copyright Google, Inc.
# http://code.google.com/p/sebs
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#     * Redistributions of source code must retain the above copyright
# notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above
# copyright notice, this list of conditions and the following disclaimer
# in the documentation and/or other materials provided with the
# distribution.
#     * Neither the name of the SEBS project nor the names of its
# contributors may be used to endorse or promote products derived from
# this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import cStringIO
import collections
import os
import subprocess
import sys
import tempfile
import threading
import time

from sebs.core import Action, Artifact, ContentToken
from sebs.filesystem import Directory
from sebs.helpers import typecheck
from sebs.command import CommandContext, Command
from sebs.console import ColoredText

class ActionRunner(object):
  """Abstract interface for an object which can execute actions."""

  def __init__(self):
    pass

  def run(self, action, inputs, outputs, test_result, lock):
    """Executes the given action.  Returns true if the command succeeds, false
    if it fails.  |inputs| and |outputs| are lists of artifacts that are the
    inputs and outputs of this action, as determined by calling
    enumerate_artifacts on the command."""
    raise NotImplementedError

class _CommandContextImpl(CommandContext):
  def __init__(self, working_dir, pending_message, verbose, lock):
    self.__working_dir = working_dir
    self.__temp_files_for_mem = {}
    self.__pending_message = pending_message
    self.__verbose = verbose
    self.__lock = lock

    self.__original_text = list(self.__pending_message.text)
    self.__verbose_text = []

  def get_disk_path(self, artifact, use_temporary=True):
    filename = artifact.filename
    result = self.__working_dir.get_disk_path(filename)
    if result is None and use_temporary:
      if filename in self.__temp_files_for_mem:
        result = self.__temp_files_for_mem[filename]
      else:
        (fd, result) = tempfile.mkstemp(
            suffix = "_" + os.path.basename(filename))
        if self.__working_dir.exists(filename):
          os.write(fd, self.__working_dir.read(filename))
          os.close(fd)
          mtime = self.__working_dir.getmtime(filename)
          os.utime(result, (mtime, mtime))
        else:
          os.close(fd)
        # We don't track whether files are executable so we just set the
        # executable bit on everything just in case.
        os.chmod(result, 0700)
        self.__temp_files_for_mem[filename] = result
    return result

  def read(self, artifact):
    filename = artifact.filename
    if filename in self.__temp_files_for_mem:
      file = open(self.__temp_files_for_mem[filename], "rU")
      result = file.read()
      file.close()
      return result
    else:
      return self.__working_dir.read(filename)

  def write(self, artifact, content):
    filename = artifact.filename
    if filename in self.__temp_files_for_mem:
      file = open(self.__temp_files_for_mem[filename], "wb")
      file.write(content)
      file.close()
    else:
      self.__working_dir.write(filename, content)

  def getenv(self, env_name):
    if env_name in os.environ:
      return os.environ[env_name]
    else:
      return None

  def subprocess(self, args, **kwargs):
    if self.__verbose:
      self.__verbose_text.append("\n  ")
      self.__verbose_text.append(" ".join(args))
      self.__pending_message.update(self.__original_text + self.__verbose_text)
    if "stdin" in kwargs and isinstance(kwargs["stdin"], str):
      stdin_str = kwargs["stdin"]
      kwargs["stdin"] = subprocess.PIPE
    else:
      stdin_str = None
    proc = subprocess.Popen(args, **kwargs)

    self.__lock.release()
    try:
      stdout_str, stderr_str = proc.communicate(stdin_str)
      return (proc.returncode, stdout_str, stderr_str)
    except:
      # Kill the process if it is still running.
      # Only available on python 2.6 and later.
      if "kill" in proc.__dict__:
        try:
          proc.kill()
        except:
          pass
      raise
    finally:
      self.__lock.acquire()

  def status(self, text):
    self.__original_text.append(" ")
    self.__original_text.append(ColoredText(ColoredText.BLUE, text))
    self.__pending_message.update(self.__original_text + self.__verbose_text)

  def resolve_mem_files(self):
    for (filename, diskfile) in self.__temp_files_for_mem.items():
      file = open(diskfile, "rb")
      self.__working_dir.write(filename, file, os.path.getmtime(diskfile))
      file.close()
      os.remove(diskfile)
    self.__temp_files_for_mem = {}

class SubprocessRunner(ActionRunner):
  """An ActionRunner which actually executes the commands."""

  def __init__(self, working_dir, console, verbose = False):
    super(SubprocessRunner, self).__init__()

    self.__env = os.environ.copy()
    self.__working_dir = working_dir
    self.__console = console
    self.__temp_files_for_mem = {}
    self.__verbose = verbose

    # TODO(kenton):  We should *add* src to the existing PYTHONPATH instead of
    #   overwrite, but there is one problem:  The SEBS Python archive may be
    #   in PYTHONPATH, and we do NOT want programs that we run to be able to
    #   take advantage of that to import SEBS implementation modules.
    self.__env["PYTHONPATH"] = "src"

  def run(self, action, inputs, outputs, test_result, lock):
    typecheck(action, Action)

    pending_message = self.__console.add_pending([
        ColoredText(ColoredText.BLUE, action.verb + ": "), action.name])

    # Make sure the output directories exist.
    # TODO(kenton):  Also delete output files from previous runs?
    for output in outputs:
      self.__working_dir.mkdir(os.path.dirname(output.filename))

    context = _CommandContextImpl(
        self.__working_dir, pending_message, self.__verbose, lock)
    try:
      log = cStringIO.StringIO()
      result = action.command.run(context, log)
      context.resolve_mem_files()

      final_text = [pending_message.text]
      log_text = log.getvalue()
      if log_text != "":
        final_text.append("\n  ")
        final_text.append(log_text.strip().replace("\n", "\n  "))

      if not result:
        # Set modification time of all outputs to zero to make sure they are
        # rebuilt on the next run.
        self.__reset_mtime(outputs)

        pending_message.finish(
            [ColoredText(ColoredText.RED, "ERROR: ")] + final_text)

        return False
    except:
      # Like above.
      context.resolve_mem_files()
      self.__reset_mtime(outputs)
      raise

    if test_result is not None:
      if context.read(test_result) == "true":
        passfail = ColoredText(ColoredText.GREEN, "PASS: ")
      else:
        passfail = ColoredText(ColoredText.RED, "FAIL: ")
      final_text = [passfail] + final_text
    pending_message.finish(final_text)

    return True

  def __reset_mtime(self, artifacts):
    for artifact in artifacts:
      try:
        self.__working_dir.touch(artifact.filename, 0)
      except Exception:
        pass

# TODO(kenton):  ActionRunner which checks if the inputs have actually changed
#   (e.g. by hashing them) and skips the action if not (just touches the
#   outputs).
