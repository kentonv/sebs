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
import threading
import time

from sebs.core import Rule, Test, Action, Artifact, DefinitionError
from sebs.filesystem import Directory
from sebs.helpers import typecheck
from sebs.command import ArtifactEnumerator
from sebs.console import ColoredText
from sebs.runner import ActionRunner

class _ArtifactEnumeratorImpl(ArtifactEnumerator):
  # WARNING:  If you modify this class, see also _DiskInputCollector in
  #   runner.py.  TODO(kenton):  Share code better or something.

  def __init__(self, state_map, root_dir, action):
    typecheck(state_map, _StateMap)
    typecheck(root_dir, Directory)
    typecheck(action, Action)

    self.__state_map = state_map
    self.__root_dir = root_dir
    self.__action = action
    self.inputs = []
    self.outputs = []
    self.disk_inputs = []

  def add_input(self, artifact):
    self.inputs.append(artifact)

  def add_output(self, artifact):
    self.outputs.append(artifact)

  def add_disk_input(self, filename):
    self.disk_inputs.append(filename)

  def read(self, artifact):
    self.inputs.append(artifact)
    if self.__state_map.artifact_state(artifact).is_dirty:
      return None
    else:
      return self.__root_dir.read(artifact.filename)

  def read_previous_output(self, artifact):
    if artifact.action is not self.__action:
      raise DefinitionError("%s is not an output of %s." %
                            (artifact, self.__action))

    if self.__root_dir.exists(artifact.filename):
      return self.__root_dir.read(artifact.filename)
    else:
      return None

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
              break

          if not self.is_dirty:
            # Check disk inputs, too.
            for disk_input in action_state.disk_inputs:
              disk_timestamp = os.path.getmtime(disk_input)
              if self.timestamp + 1 < disk_timestamp:
                self.is_dirty = True
                break
      else:
        self.is_dirty = True

      # Also mark dirty if the build definition file has changed.
      if self.timestamp < artifact.action.rule.context.timestamp:
        self.is_dirty = True

  def __decide_if_dirty(self):
    action_state = state_map.action_state(self.artifact.action)

    # If the creating action is not ready, then some of its inputs are dirty,
    # which in turn means this artifact is dirty.
    if not action_state.is_ready:
      return True

    if self.artifact not in action_state.outputs:
      # The action that normally builds this artifact is not planning to
      # do so.  This is not necessarily an error -- this artifact may be
      # a conditional output of said action which is not built under the
      # current configuration.  Hopefully this artifact will not actually
      # be used.  We mark it dirty to prevent any actions that depend on it
      # from running.
      # TODO(kenton):  If the code gets here, does that mean the artifact is
      #   definitely going to be used?  If so, we could throw an error.
      return True

    # Check if any inputs are newer than this artifact.
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
        return True

    # Check disk inputs, too.
    for disk_input in action_state.disk_inputs:
      if not os.path.exists(disk_input):
        return True
      disk_timestamp = os.path.getmtime(disk_input)
      # See above comment about rounding error.
      if self.timestamp + 1 < disk_timestamp:
        return True

    # Also mark dirty if the build definition file has changed.  (Since build
    # def files cannot be derived files we don't need to worry about rounding
    # error on this one.)
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

    enumerator = _ArtifactEnumeratorImpl(state_map, root_dir, self.action)
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
    self.disk_inputs = enumerator.disk_inputs
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
                                         action_state.disk_inputs,
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
    except KeyboardInterrupt:
      if not self.failed:
        self.__console.write(ColoredText(ColoredText.RED, "INTERRUPTED"))
      self.failed = True
    except:
      self.failed = True
      raise
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
