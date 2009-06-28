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

import collections
import os
import subprocess
import sys
import tempfile

from sebs.core import Rule, Test, Action, Artifact, ContentToken, \
                      DefinitionError
from sebs.filesystem import Directory
from sebs.helpers import typecheck

class ActionRunner(object):
  """Abstract interface for an object which can execute actions."""

  def __init__(self):
    pass

  def run(self, action):
    """Executes the given action.  Returns true if the command succeeds, false
    if it fails."""
    raise NotImplementedError

class DryRunner(ActionRunner):
  """An ActionRunner which simply prints each command that would be run."""

  def __init__(self, output):
    super(DryRunner, self).__init__()
    self.__output = output

  def run(self, action):
    typecheck(action, Action)

    self.__output.write("%s: %s\n" % (action.verb, action.name))

    if action.stdout is None:
      suffix = []
    else:
      suffix = [">", action.stdout.filename]

    for command in action.commands:
      formatted = list(self.__format_command(command))
      print " ", " ".join(formatted + suffix)

    return True

  def __format_command(self, command):
    for arg in command:
      if isinstance(arg, basestring):
        yield arg
      elif isinstance(arg, Artifact):
        yield arg.filename
      elif isinstance(arg, ContentToken):
        yield "`cat %s`" % arg.artifact.filename
      elif isinstance(arg, list):
        yield "".join(self.__format_command(arg))
      else:
        raise AssertionError("Invalid argument.")

class SubprocessRunner(ActionRunner):
  """An ActionRunner which actually executes the commands."""

  def __init__(self, working_dir, stdout):
    super(SubprocessRunner, self).__init__()

    self.__env = os.environ.copy()
    self.__working_dir = working_dir
    self.__stdout = stdout
    self.__use_color = self.__stdout.isatty()
    self.__temp_files_for_mem = {}

    # TODO(kenton):  We should *add* src to the existing PYTHONPATH instead of
    #   overwrite, but there is one problem:  The SEBS Python archive may be
    #   in PYTHONPATH, and we do NOT want programs that we run to be able to
    #   take advantage of that to import SEBS implementation modules.
    self.__env["PYTHONPATH"] = "src"

  def run(self, action):
    typecheck(action, Action)
    if self.__use_color:
      self.__stdout.write(
          "\033[34m%s:\033[0m %s\n" % (action.verb, action.name))
    else:
      self.__stdout.write("%s: %s\n" % (action.verb, action.name))

    # Make sure the output directories exist.
    # TODO(kenton):  Also delete output files from previous runs?
    for output in action.outputs:
      self.__working_dir.mkdir(os.path.dirname(output.filename))

    # Capture stdout if requested.
    # TODO(kenton):  Capture stdout/stderr even when not requested so that it
    #   can be printed all at once to avoid interleaving parallel commands.
    if action.stdout is None:
      stdout = None
      stderr = None
    else:
      disk_path = self.__get_disk_path(action.stdout.filename)
      if disk_path is None:
        stdout = subprocess.PIPE
      else:
        stdout = open(disk_path, "wb")
      if action.merge_standard_outs:
        stderr = subprocess.STDOUT
      else:
        stderr = None

    try:
      for command in action.commands:
        formatted_command = list(self.__format_command(command))
        proc = subprocess.Popen(formatted_command,
                                stdout = stdout, stderr = stderr,
                                env = self.__env)

        (output, _) = proc.communicate()

        if stdout is subprocess.PIPE:
          assert output is not None
          self.__working_dir.write(action.stdout.filename, output)
        elif stdout is not None:
          stdout.close()

        if proc.returncode != 0:
          self.__resolve_mem_files()
          # Set modification time of all outputs to zero to make sure they are
          # rebuilt on the next run.
          for output in action.outputs:
            try:
              self.__working_dir.touch(output.filename, 0)
            except Exception:
              pass
          return False
    finally:
      self.__resolve_mem_files()

    return True

  def __format_command(self, command, split_content=True):
    for arg in command:
      if isinstance(arg, basestring):
        yield arg
      elif isinstance(arg, Artifact):
        yield self.__get_disk_path(arg.filename)
      elif isinstance(arg, ContentToken):
        content = self.__read_file(arg.filename)
        if split_content:
          for part in content.split():
            yield part
        else:
          yield content
      elif isinstance(arg, list):
        yield "".join(self.__format_command(arg, split_content = False))
      else:
        raise AssertionError("Invalid argument.")

  def __get_disk_path(self, filename):
    """Get a suitable on-disk path for the given filename.  Returns the file's
    actual on-disk path if it has one, otherwise returns a temporary file.
    __resolve_mem_files() must be called later to read the contents of the
    temporary files back into memory."""
    result = self.__working_dir.get_disk_path(filename)
    if result is None:
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

  def __read_file(self, filename):
    """Equivalent to self.__working_dir.read(filename) except that if a call
    to self.__get_disk_path() created a temporary file representing this file,
    then the temporary file is read instead."""
    if filename in self.__temp_files_for_mem:
      file = open(self.__temp_files_for_mem[filename], "rU")
      result = file.read()
      file.close()
      return result
    else:
      return self.__working_dir.read(filename)

  def __resolve_mem_files(self):
    """See __get_disk_path()."""
    for (filename, diskfile) in self.__temp_files_for_mem.items():
      file = open(diskfile, "rb")
      self.__working_dir.write(filename, file, os.path.getmtime(diskfile))
      file.close()
      os.remove(diskfile)
    self.__temp_files_for_mem = {}

# TODO(kenton):  ActionRunner which checks if the inputs have actually changed
#   (e.g. by hashing them) and skips the action if not (just touches the
#   outputs).

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
      elif root_dir.exists(artifact.filename):
        raise DefinitionError(
          "The required source file '%s' does not exist." % artifact.filename)
      else:
        raise DefinitionError(
          "The required source file '%s' is not accessible." %
          artifact.filename)

    self.is_dirty = False

    if artifact.action is not None:
      for input in artifact.action.inputs:
        input_state = state_map.artifact_state(input)
        # TODO(kenton):  Should we round these timestamps to the nearest
        #   integer since disk filesystems often do that?  Otherwise, when
        #   comparing a disk file to a mem file we might get false positives.
        #   However, I haven't yet seen this happen in practice.
        if input_state.is_dirty or self.timestamp < input_state.timestamp:
          self.is_dirty = True
      if self.timestamp < artifact.action.rule.context.timestamp:
        self.is_dirty = True

class _ActionState(object):
  def __init__(self, action, root_dir, state_map):
    typecheck(action, Action)
    typecheck(root_dir, Directory)
    typecheck(state_map, _StateMap)

    self.action = action

    # Has the Builder decided that this action needs to be built?
    self.is_pending = False
    # Is this action ready to be built now?  (I.e. inputs are not dirty.)
    self.is_ready = False

    self.update_readiness(state_map)

  def update_readiness(self, state_map):
    """Update self.is_ready based on input.  If no inputs are dirty, is_ready
    is set true, otherwise it is set false.  This method returns true if
    is_ready was modified (from false to true), or false if it kept its previous
    value."""

    typecheck(state_map, _StateMap)

    if self.is_ready:
      # Already ready.  No change is possible.
      return False

    for input in self.action.inputs:
      if state_map.artifact_state(input).is_dirty:
        return False

    self.is_ready = True
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
  def __init__(self, root_dir):
    typecheck(root_dir, Directory)

    self.__state_map = _StateMap(root_dir)

    # Actions which are ready but haven't been started.
    self.__action_queue = collections.deque()

    self.__test_queue = collections.deque()
    self.__test_results = []

  def add_artifact(self, artifact):
    typecheck(artifact, Artifact)

    artifact_state = self.__state_map.artifact_state(artifact)
    if not artifact_state.is_dirty:
      return   # Source file; nothing to do.

    # The artifact is dirty, therefore it must have an action.
    action = artifact.action
    action_state = self.__state_map.action_state(action)
    if action_state.is_pending:
      return   # Action is already pending.

    action_state.is_pending = True
    if action_state.is_ready:
      self.__action_queue.append(artifact.action)

    for input in action.inputs:
      self.add_artifact(input)

  def add_rule(self, rule):
    typecheck(rule, Rule)

    rule.expand_once()

    for artifact in rule.outputs:
      self.add_artifact(artifact)

  def add_test(self, test):
    typecheck(test, Test)

    test.expand_once()

    if test.test_action.stdout is None:
      raise DefinitionError(
        "Test actions must capture stdout.  Offending rule: %s" % test.name)

    for input in test.test_action.inputs:
      self.add_artifact(input)

    if self.__state_map.artifact_state(test.test_action.stdout).is_dirty:
      self.__test_queue.append(test)
    else:
      self.__test_results.append((test.name, test, True))

  def build(self, action_runner):
    typecheck(action_runner, ActionRunner)

    while len(self.__action_queue) > 0:
      action = self.__action_queue.popleft()
      if not action_runner.run(action):
        print "BUILD FAILED"
        return False

      newly_ready = []

      for output in action.outputs:
        self.__state_map.artifact_state(output).is_dirty = False

        for dependent in output.dependents:
          dependent_state = self.__state_map.action_state(dependent)
          if dependent_state.is_pending and \
             dependent_state.update_readiness(self.__state_map):
            newly_ready.append(dependent)

      # Stick newly-ready stuff at the beginning of the queue so that local
      # work tends to be grouped together.  For example, if we're building
      # C++ libraries A and B, we'd like to compile the sources of A, then
      # link A, then compile the sources of B, then link B.  If we added
      # newly-ready stuff to the end of the queue, we'd end up compiling all
      # sources of both libraries before linking either one.
      newly_ready.reverse()
      self.__action_queue.extendleft(newly_ready)

    return True

  def test(self, action_runner):
    if not self.build(action_runner):
      return False

    if sys.stdout.isatty():
      passmsg, failmsg = ("\033[32mPASS:\033[0m", "\033[31mFAIL:\033[0m")
      passed, failed = ("\033[32mPASSED\033[0m", "\033[31mFAILED\033[0m")
    else:
      passmsg, failmsg = ("PASS:", "FAIL:")
      passed, failed = ("PASSED", "FAILED")

    while len(self.__test_queue) > 0:
      test = self.__test_queue.popleft()

      result = action_runner.run(test.test_action)
      if result:
        print passmsg, test.name
      else:
        print failmsg, test.name
        print " ", test.test_action.stdout.filename

      self.__test_results.append((test.name, test, result))

    self.__test_results.sort()

    print "\nTest results:"

    had_failure = False
    for name, test, result in self.__test_results:
      if result:
        indicator = passed
      else:
        indicator = failed
        had_failure = True

      print "  %-70s %s" % (name, indicator)

      if not result:
        print "   ", test.test_action.stdout.filename

    return not had_failure
