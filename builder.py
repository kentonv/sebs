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

from sebs.core import Rule, Test, Action, Artifact, ContentToken, \
                      DefinitionError
from sebs.filesystem import Directory
from sebs.helpers import typecheck
from sebs.command import CommandContext, Command, SubprocessCommand, \
                         ArtifactEnumerator
from sebs.console import ColoredText

# TODO(kenton):  ActionRunner and implementations belong in a separate module.

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

# ====================================================================

class _ArtifactEnumeratorImpl(ArtifactEnumerator):
  def __init__(self, state_map, root_dir):
    typecheck(state_map, _StateMap)
    typecheck(root_dir, Directory)

    self.__state_map = state_map
    self.__root_dir = root_dir
    self.inputs = []
    self.outputs = []

  def add_input(self, artifact):
    self.inputs.append(artifact)

  def add_output(self, artifact):
    self.outputs.append(artifact)

  def read(self, artifact):
    self.inputs.append(artifact)
    if self.__state_map.artifact_state(artifact).is_dirty:
      return None
    else:
      return self.__root_dir.read(artifact.filename)

  def getenv(self, env_name):
    if env_name in os.environ:
      return os.environ[env_name]
    else:
      return None

class _ArtifactState(object):
  def __init__(self, artifact, root_dir, state_map):
    typecheck(artifact, Artifact)
    typecheck(root_dir, Directory)
    typecheck(state_map, _StateMap)

    self.artifact = artifact

    try:
      self.timestamp = root_dir.getmtime(artifact.filename)
    except os.error:
      if artifact.action is not None:
        # Derived artifact doesn't exist yet.
        self.timestamp = -1
        self.is_dirty = True
        return
      elif root_dir.exists(artifact.filename):
        raise DefinitionError(
          "The required source file '%s' does not exist." % artifact.filename)
      else:
        raise DefinitionError(
          "The required source file '%s' is not accessible." %
          artifact.filename)

    self.is_dirty = False

    if artifact.action is not None:
      action_state = state_map.action_state(artifact.action)
      if action_state.is_ready:
        if artifact not in action_state.outputs:
          self.is_dirty = True
        else:
          for input in action_state.inputs:
            input_state = state_map.artifact_state(input)
            # We assume that if the mtimes are within one second of each other
            # then both artifacts must have been built as part of the same
            # build.  Even if the input's timestamp is actually newer than this
            # artifact, we assume that this artifact was actually built
            # afterwards but some sort of rounding error lead to the difference.
            # (For example, the disk filesystem may round timestamps to the
            # nearest second while the mem filesystem keeps exact times.)
            if input_state.is_dirty or \
               self.timestamp + 1 < input_state.timestamp:
              self.is_dirty = True
      else:
        self.is_dirty = True

      # Also mark dirty if the build definition file has changed.
      if self.timestamp < artifact.action.rule.context.timestamp:
        self.is_dirty = True

class _ActionState(object):
  def __init__(self, action, root_dir, state_map):
    typecheck(action, Action)
    typecheck(root_dir, Directory)
    typecheck(state_map, _StateMap)

    self.action = action

    # If this is a test action, |test| is the test rule.
    self.test = None

    # Has the Builder decided that this action needs to be built?
    self.is_pending = False
    # Is this action ready to be built now?  (I.e. inputs are not dirty.)
    self.is_ready = False

    # Once is_ready is true, |inputs| and |outputs| will be lists of input
    # and output artifacts of this action.  When is_ready is false, we don't
    # yet know the full list.
    self.inputs = None
    self.outputs = None

    # Actions which must be completed before this one can be.  Updated by
    # update_readiness().
    self.blocking = None

    # As other actions discover that they are blocked by this, they add
    # themselves to this set.
    self.blocked = set()

    self.update_readiness(state_map, root_dir)

  def update_readiness(self, state_map, root_dir):
    """Update self.is_ready based on input.  If no inputs are dirty, is_ready
    is set true, otherwise it is set false.  This method returns true if
    is_ready was modified (from false to true), or false if it kept its previous
    value."""

    typecheck(state_map, _StateMap)
    typecheck(root_dir, Directory)

    if self.is_ready:
      # Already ready.  No change is possible.
      return False

    enumerator = _ArtifactEnumeratorImpl(state_map, root_dir)
    self.action.command.enumerate_artifacts(enumerator)

    self.blocking = set()
    for input in enumerator.inputs:
      if state_map.artifact_state(input).is_dirty:
        # Input is dirty, therefore it must have an action.
        blocking_state = state_map.action_state(input.action)
        if blocking_state.is_ready and input not in blocking_state.outputs:
          raise DefinitionError(
              "%s is needed, but %s didn't generate it." %
              (input, input.action))
        blocking_state.blocked.add(self.action)
        self.blocking.add(input.action)

    if len(self.blocking) > 0:
      # At least one input is still dirty.
      return False

    self.is_ready = True
    self.inputs = enumerator.inputs
    self.outputs = enumerator.outputs
    return True

class _StateMap(object):
  def __init__(self, root_dir):
    typecheck(root_dir, Directory)

    self.__artifacts = {}
    self.__actions = {}
    self.__root_dir = root_dir

  def artifact_state(self, artifact):
    typecheck(artifact, Artifact)

    if artifact in self.__artifacts:
      return self.__artifacts[artifact]
    else:
      result = _ArtifactState(artifact, self.__root_dir, self)
      self.__artifacts[artifact] = result
      return result

  def action_state(self, action):
    typecheck(action, Action)

    if action in self.__actions:
      return self.__actions[action]
    else:
      result = _ActionState(action, self.__root_dir, self)
      self.__actions[action] = result
      return result

class Builder(object):
  def __init__(self, root_dir, console):
    typecheck(root_dir, Directory)

    self.__state_map = _StateMap(root_dir)
    self.__root_dir = root_dir
    self.__console = console
    self.__lock = threading.Lock()
    self.__num_pending = 0

    # Actions which are ready but haven't been started.
    self.__action_queue = collections.deque()

    self.__tests = []

    self.failed = False

  def add_action(self, action):
    typecheck(action, Action)

    action_state = self.__state_map.action_state(action)
    if action_state.is_pending:
      # Already pending.
      return

    action_state.is_pending = True
    self.__num_pending = self.__num_pending + 1
    if action_state.is_ready:
      self.__action_queue.append(action)
    else:
      for blocker in action_state.blocking:
        self.add_action(blocker)

  def add_artifact(self, artifact):
    typecheck(artifact, Artifact)

    artifact_state = self.__state_map.artifact_state(artifact)
    if not artifact_state.is_dirty:
      return   # Source file; nothing to do.

    # The artifact is dirty, therefore it must have an action.
    self.add_action(artifact.action)

  def add_rule(self, rule):
    typecheck(rule, Rule)

    rule.expand_once()

    for artifact in rule.outputs:
      self.add_artifact(artifact)

  def add_test(self, test):
    typecheck(test, Test)

    test.expand_once()

    self.add_artifact(test.test_result_artifact)
    self.add_artifact(test.test_output_artifact)

    action_state = self.__state_map.action_state(
        test.test_result_artifact.action)
    action_state.test = test

    cached = not self.__state_map.artifact_state(
        test.test_result_artifact).is_dirty
    self.__tests.append((test.name, test, cached))

  def build(self, action_runner):
    self.__lock.acquire()
    try:
      typecheck(action_runner, ActionRunner)

      while self.__num_pending > 0 and not self.failed:
        if len(self.__action_queue) == 0:
          # wait for actions
          # TODO(kenton):  Use a semaphore or something?
          self.__lock.release()
          time.sleep(1)
          self.__lock.acquire()
          continue

        action = self.__action_queue.popleft()
        action_state = self.__state_map.action_state(action)
        test_result = None
        if action_state.test is not None:
          test_result = action_state.test.test_result_artifact
        self.__num_pending = self.__num_pending - 1
        if not action_runner.run(action, action_state.inputs,
                                         action_state.outputs,
                                         test_result,
                                         self.__lock):
          if not self.failed:
            self.__console.write(ColoredText(ColoredText.RED, "BUILD FAILED"))
            self.failed = True
          return

        newly_ready = []

        for output in action_state.outputs:
          self.__state_map.artifact_state(output).is_dirty = False

        for dependent in action_state.blocked:
          dependent_state = self.__state_map.action_state(dependent)
          became_ready = dependent_state.update_readiness(self.__state_map,
                                                          self.__root_dir)
          if dependent_state.is_pending:
            if became_ready:
              newly_ready.append(dependent)
            else:
              # This action is still blocked on something else.  It's possible
              # that completion of the current action caused this dependent to
              # realize that it needs some other inputs that it didn't know
              # about before.  Thus its blocking list may now contain actions
              # that didn't previously know we needed to build.  We must scan
              # through the list and add any such actions to the pending list.
              for blocker in dependent_state.blocking:
                if not self.__state_map.action_state(blocker).is_pending:
                  self.add_action(blocker)

        # Stick newly-ready stuff at the beginning of the queue so that local
        # work tends to be grouped together.  For example, if we're building
        # C++ libraries A and B, we'd like to compile the sources of A, then
        # link A, then compile the sources of B, then link B.  If we added
        # newly-ready stuff to the end of the queue, we'd end up compiling all
        # sources of both libraries before linking either one.
        newly_ready.reverse()
        self.__action_queue.extendleft(newly_ready)
    finally:
      self.__lock.release()

  def print_test_results(self):
    self.__tests.sort()

    print "\nTest results:"

    had_failure = False
    for name, test, cached in self.__tests:
      result = self.__root_dir.read(test.test_result_artifact.filename)

      suffix = ""
      if cached:
        suffix = " (cached)"

      if result == "true":
        indicator = ColoredText(ColoredText.GREEN, "PASSED" + suffix)
      else:
        indicator = ColoredText(ColoredText.RED, "FAILED" + suffix)
        had_failure = True

      message = ["  %-70s " % name, indicator]
      if result == "false":
        message.extend(["\n    ", test.test_output_artifact.filename])
      self.__console.write(message)

    return not had_failure
