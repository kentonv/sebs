# Scalable Extensible Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.

import collections
import os
import subprocess

from sebs.core import Rule, Action, Artifact, ContentToken, DefinitionError
from sebs.filesystem import Directory
from sebs.helpers import typecheck

class CommandFailedError(Exception):
  pass

class ActionRunner(object):
  """Abstract interface for an object which can execute actions."""
  
  def __init__(self):
    pass
  
  def run(self, action):
    raise NotImplementedError

class DryRunner(ActionRunner):
  """An ActionRunner which simply prints each command that would be run."""
  
  def __init__(self, output):
    super(DryRunner, self).__init__()
    self.__output = output
  
  def run(self, action):
    typecheck(action, Action)

    self.__output.write(action.message() + "\n")

    if action.stdout is None:
      suffix = []
    else:
      suffix = [">", action.stdout.filename]

    for command in action.commands:
      formatted = list(self.__format_command(command))
      print " ", " ".join(formatted + suffix)
  
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
  
  def __init__(self):
    super(SubprocessRunner, self).__init__()
  
  def run(self, action):
    typecheck(action, Action)
    print action.message()
    
    # Make sure the output directories exist.
    for output in action.outputs:
      dirname = os.path.dirname(output.filename)
      # If the path exists and is a directory, we don't have to create anything,
      # but makedirs() will raise an error if we call it.  If the path exists
      # but is *not* a directory, we still call makedirs() so that it raises an
      # appropriate error.
      if not os.path.exists(dirname) or not os.path.isdir(dirname):
        os.makedirs(dirname)

    # Capture stdout if requested.
    # TODO(kenton):  Capture stdout/stderr even when not requested so that it
    #   can be printed all at once to avoid interleaving parallel commands.
    if action.stdout is None:
      stdout = None
      stderr = None
    else:
      stdout = open(action.stdout.filename, "wb")
      if action.merge_standard_outs:
        stderr = stdout
      else:
        stderr = None

    for command in action.commands:
      formatted_command = list(self.__format_command(command))
      proc = subprocess.Popen(formatted_command,
                              stdout = stdout, stderr = stderr)
      if proc.wait() != 0:
        # Clean outputs in case the command touched them before failing.
        for output in action.outputs:
          try:
            os.remove(output.filename)
          except Exception:
            pass
        raise CommandFailedError(" ".join(formatted_command))

  def __format_command(self, command, split_content=True):
    for arg in command:
      if isinstance(arg, basestring):
        yield arg
      elif isinstance(arg, Artifact):
        yield arg.filename
      elif isinstance(arg, ContentToken):
        file = open(arg.artifact.filename, "rU")
        content = file.read()
        file.close()
        if split_content:
          for part in content.split():
            yield part
        else:
          yield content
      elif isinstance(arg, list):
        yield "".join(self.__format_command(arg, split_content = False))
      else:
        raise AssertionError("Invalid argument.")

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
        if input_state.is_dirty or self.timestamp < input_state.timestamp:
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
    
    # Actions which are ready but haven't been started.
    self.__action_queue = collections.deque()
    self.__state_map = _StateMap(root_dir)
    
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
    
    for artifact in rule.outputs:
      self.add_artifact(artifact)
  
  def build(self, action_runner):
    typecheck(action_runner, ActionRunner)
    
    while len(self.__action_queue) > 0:
      action = self.__action_queue.popleft()
      action_runner.run(action)
      
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
