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

"""
Commands define exactly what an Action does.
"""

import cStringIO
import os
import subprocess

from sebs.core import Artifact, Action, DefinitionError, ContentToken, \
                      CommandBase
from sebs.helpers import typecheck

class CommandContext(object):
  def get_disk_path(self, artifact, use_temporary=True):
    """Get the on-disk file name of the given artifact.  If the artifact is not
    on-disk already and use_temporary is true, a temporary file representing
    the artifact will be created.  If use_temporary is false, then this method
    returns None if the file does not have a disk path."""
    raise NotImplementedError

  def read(self, artifact):
    """Read an artifact's contents, returning them as a string."""
    raise NotImplementedError

  def write(self, artifact, content):
    """Replace the artifact's contents with the given string."""
    raise NotImplementedError

  def getenv(self, env_name):
    """Returns the value of the given environment variable, or None if not
    set."""
    raise NotImplementedError

  def subprocess(self, args, **kwargs):
    """Runs a subprocess.  The parameters are the same as those to the Popen
    function in the standard subprocess module.  Additionally, the "stdin"
    argument is allowed to be a string, in which case it will be fed into the
    process via a pipe.  Returns a triplet:  (exit_code, stdout, stderr).
    stdout and stderr are the values returned by the communicate() method of
    the Popen object -- i.e. strings if you passed subprocess.PIPE for the
    corresponding parameters, or None otherwise."""
    raise NotImplementedError

  def message(self, text):
    """Provides a message to be printed to the console reporting the result
    of this action."""
    raise NotImplementedError

class ArtifactEnumerator(object):
  def add_input(self, artifact):
    """Report that the given artifact is an input to the command."""
    raise NotImplementedError

  def add_output(self, artifact):
    """Report that the given artifact is an output to the command."""
    raise NotImplementedError

  def read(self, artifact):
    """If the given artifact exists and is up-to-date, returns its contents as
    a string.  Otherwise, returns None.  Calling this also implies that the
    artifact is an input, as if add_input() were called."""
    raise NotImplementedError

  def getenv(self, env_name):
    """Returns the value of the given environment variable, or None if not
    set.  When the command is run, CommandContext.getenv() must return the
    same value."""
    raise NotImplementedError

class Command(CommandBase):
  """Represents something which an Action does, e.g. executing a shell command.
  Command implementations are not allowed to create new Actions or Artifacts --
  they can only use the ones passed to their constructors.  In general, they
  should not have any side effects except for those explicitly allowed."""

  def enumerate_artifacts(self, artifact_enumerator):
    """Calls the ArtifactEnumerator's add_input() and add_output() commands for
    all inputs and outputs that the command is known to have.  This method is
    allowed to call artifact_enumerator.read() and make decisions based on it.
    If read() returns None, then the caller must assume that the list of
    inputs and outputs is incomplete, and in order to get a complete list it
    will need to re-run enumerate_artifacts with the read artifact available."""
    raise NotImplementedError

  def run(self, context, log):
    """Run the command.  Returns True if the command succeeded or False if some
    error occurred -- error details should already have been written to |log|,
    which is a file-like object."""
    raise NotImplementedError

  def print_(self, output):
    """Print a human-readable representation of what the command does.  The
    text should be written to the given output stream."""
    raise NotImplementedError

class EchoCommand(Command):
  """Command which simply writes a string into an artifact."""

  def __init__(self, content, output_artifact):
    typecheck(content, str)
    typecheck(output_artifact, Artifact)
    self.__content = content
    self.__output_artifact = output_artifact

  def enumerate_artifacts(self, artifact_enumerator):
    typecheck(artifact_enumerator, ArtifactEnumerator)
    artifact_enumerator.add_output(self.__output_artifact)

  def run(self, context, log):
    typecheck(context, CommandContext)
    context.write(self.__output_artifact, self.__content)
    return True

  def print_(self, output):
    output.write("echo '%s' > %s\n" %
        (self.__content, self.__output_artifact.filename))

class EnvironmentCommand(Command):
  """Command which reads an environment variable and writes the contents into
  an artifact.  If the environment variable is unset, a default value is used.
  The default value may be a simple string or it may be another artifact -- in
  the latter case, the artifact's contents are copied into the output."""

  def __init__(self, env_name, output_artifact, default=None,
               output_message=False):
    typecheck(env_name, str)
    typecheck(output_artifact, Artifact)
    typecheck(default, [str, Artifact])
    self.__env_name = env_name
    self.__output_artifact = output_artifact
    self.__default = default
    self.__output_message = output_message

  def enumerate_artifacts(self, artifact_enumerator):
    typecheck(artifact_enumerator, ArtifactEnumerator)
    if self.__default is not None and \
       isinstance(self.__default, Artifact) and \
       artifact_enumerator.getenv(self.__env_name) is None:
      artifact_enumerator.add_input(self.__default)
    artifact_enumerator.add_output(self.__output_artifact)

  def run(self, context, log):
    typecheck(context, CommandContext)
    value = context.getenv(self.__env_name)
    if value is None:
      if self.__default is None:
        log.write("Environment variable not set: %s\n" % self.__env_name)
        return False
      elif isinstance(self.__default, Artifact):
        value = context.read(self.__default)
      else:
        value = self.__default
    context.write(self.__output_artifact, value)
    if self.__output_message:
      context.message(value)
    return True

  def print_(self, output):
    if self.__default is None:
      output.write("echo $%s > %s\n" %
          (self.__env_name, self.__output_artifact.filename))
    else:
      output.write("echo ${%s:%s} > %s\n" %
          (self.__env_name, self.__default.filename,
           self.__output_artifact.filename))

class DoAllCommand(Command):
  """Command which simply executes some list of commands in order."""

  def __init__(self, subcommands):
    typecheck(subcommands, list, Command)
    self.__subcommands = subcommands

  def enumerate_artifacts(self, artifact_enumerator):
    typecheck(artifact_enumerator, ArtifactEnumerator)
    for command in self.__subcommands:
      command.enumerate_artifacts(artifact_enumerator)

  def run(self, context, log):
    typecheck(context, CommandContext)
    for command in self.__subcommands:
      if not command.run(context, log):
        return False
    return True

  def print_(self, output):
    for command in self.__subcommands:
      command.print_(output)

class ConditionalCommand(Command):
  """Command which first checks if the contents of some artifact.  The contents
  are expected to be either "true" or "false".  If "true", then true_command
  is executed.  A false_command may optionally be given which is executed if
  the value was false."""

  def __init__(self, condition_artifact, true_command, false_command = None):
    typecheck(condition_artifact, Artifact)
    typecheck(true_command, Command)
    typecheck(false_command, Command)
    self.__condition_artifact = condition_artifact
    self.__true_command = true_command
    self.__false_command = false_command

  def enumerate_artifacts(self, artifact_enumerator):
    typecheck(artifact_enumerator, ArtifactEnumerator)
    value = artifact_enumerator.read(self.__condition_artifact)
    if value == "true":
      self.__true_command.enumerate_artifacts(artifact_enumerator)
    elif value == "false" and self.__false_command is not None:
      self.__false_command.enumerate_artifacts(artifact_enumerator)

  def run(self, context, log):
    typecheck(context, CommandContext)
    value = context.read(self.__condition_artifact)
    if value == "true":
      return self.__true_command.run(context, log)
    elif value == "false":
      if self.__false_command is not None:
        return self.__false_command.run(context, log)
      else:
        return True
    else:
      log.write("Condition artifact was not true or false: %s\n" %
                self.__condition_artifact)
      return False

  def print_(self, output):
    output.write("if %s {\n" % self.__condition_artifact.filename)
    sub_output = cStringIO.StringIO()
    self.__true_command.print_(sub_output)
    output.write(self.__indent(sub_output.getvalue()))
    if self.__false_command is not None:
      output.write("} else {\n")
      sub_output = cStringIO.StringIO()
      self.__false_command.print_(sub_output)
      output.write(self.__indent(sub_output.getvalue()))
    output.write("}\n")

  def __indent(self, text):
    lines = text.split("\n")
    if lines[-1] == "":
      lines.pop()
    return "  %s\n" % "\n  ".join(lines)

class SubprocessCommand(Command):
  """Command which launches a separate process."""

  def __init__(self, action, args, implicit = [],
               capture_stdout=None, capture_stderr=None,
               capture_exit_status=None):
    typecheck(action, Action)
    typecheck(args, list)
    typecheck(implicit, list, Artifact)
    typecheck(capture_stdout, Artifact)
    typecheck(capture_stderr, Artifact)
    typecheck(capture_exit_status, Artifact)

    self.__verify_args(args)

    self.__args = args
    self.__implicit_artifacts = implicit
    self.__action = action
    self.__capture_stdout = capture_stdout
    self.__capture_stderr = capture_stderr
    self.__capture_exit_status = capture_exit_status

  def enumerate_artifacts(self, artifact_enumerator):
    if self.__capture_stdout is not None:
      artifact_enumerator.add_output(self.__capture_stdout)
    if self.__capture_stderr is not None:
      artifact_enumerator.add_output(self.__capture_stderr)
    if self.__capture_exit_status is not None:
      artifact_enumerator.add_output(self.__capture_exit_status)

    # All other inputs and outputs are listed in the arguments, or in
    # __implicit_artifacts.  We can identify outputs as the artifacts which are
    # generated by the action which runs this command.  The rest are inputs.
    class DummyContext(CommandContext):
      def __init__(self):
        self.artifacts = set()
      def get_disk_path(self, artifact):
        self.artifacts.add(artifact)
        return ""
      def read(self, artifact):
        self.artifacts.add(artifact)
        return ""

    context = DummyContext()
    context.artifacts.update(self.__implicit_artifacts)
    for dummy in self.__format_args(self.__args, context):
      # We must actually iterate through the results because __format_args()
      # is a generator function.
      pass

    for artifact in context.artifacts:
      if self.__action is not None and artifact.action is self.__action:
        artifact_enumerator.add_output(artifact)
      else:
        artifact_enumerator.add_input(artifact)

  def run(self, context, log):
    formatted_args = list(self.__format_args(self.__args, context))

    # Capture stdout/stderr if requested.
    if self.__capture_stdout is None:
      # TODO(kenton):  This should be "stdout = log" but this seems to cause
      #   the output to simply be lost.  Investigate.
      stdout = None
    else:
      disk_path = context.get_disk_path(self.__capture_stdout,
                                        use_temporary = False)
      if disk_path is None:
        stdout = subprocess.PIPE
      else:
        stdout = open(disk_path, "wb")

    if self.__capture_stderr is self.__capture_stdout:
      stderr = subprocess.STDOUT
    elif self.__capture_stderr is None:
      stderr = log
    else:
      disk_path = context.get_disk_path(self.__capture_stderr,
                                        use_temporary = False)
      if disk_path is None:
        stderr = subprocess.PIPE
      else:
        stderr = open(disk_path, "wb")

    env = os.environ.copy()
    # TODO(kenton):  We should *add* src to the existing PYTHONPATH instead of
    #   overwrite, but there is one problem:  The SEBS Python archive may be
    #   in PYTHONPATH, and we do NOT want programs that we run to be able to
    #   take advantage of that to import SEBS implementation modules.
    env["PYTHONPATH"] = "src"

    exit_code, stdout_text, stderr_text = \
        context.subprocess(formatted_args,
                           stdout = stdout, stderr = stderr,
                           env = env)

    if stdout == subprocess.PIPE:
      context.write(self.__capture_stdout, stdout_text)
    if stderr == subprocess.PIPE:
      context.write(self.__capture_stderr, stderr_text)

    if self.__capture_exit_status is not None:
      if exit_code == 0:
        context.write(self.__capture_exit_status, "true")
      else:
        context.write(self.__capture_exit_status, "false")
      return True
    else:
      if exit_code == 0:
        return True
      else:
        log.write("Command failed with exit code %d: %s\n" %
            (exit_code, " ".join(formatted_args)))
        return False

  def print_(self, output):
    class DummyContext(CommandContext):
      def get_disk_path(self, artifact):
        return artifact.filename
      def read(self, artifact):
        return "$(%s)" % artifact.filename

    output.write(" ".join(self.__format_args(self.__args, DummyContext())))

    if self.__capture_stdout is not None:
      output.write(" > %s" % self.__capture_stdout.filename)
    if self.__capture_stderr is not None:
      if self.__capture_stderr is self.__capture_stdout:
        output.write(" 2>&1")
      else:
        output.write(" 2> %s" % self.__capture_stderr.filename)
    if self.__capture_exit_status is not None:
      output.write(" && echo true > %s || echo false > %s" %
          (self.__capture_exit_status.filename,
           self.__capture_exit_status.filename))
    output.write("\n")

  def __verify_args(self, args):
    for arg in args:
      if isinstance(arg, list):
        self.__verify_args(arg)
      elif not isinstance(arg, basestring) and \
           not isinstance(arg, Artifact) and \
           not isinstance(arg, ContentToken):
        raise TypeError("Invalid argument: %s" % arg)

  def __format_args(self, args, context, split_content=True):
    for arg in args:
      if isinstance(arg, basestring):
        yield arg
      elif isinstance(arg, Artifact):
        yield context.get_disk_path(arg)
      elif isinstance(arg, ContentToken):
        content = context.read(arg.artifact)
        if split_content:
          for part in content.split():
            yield part
        else:
          yield content
      elif isinstance(arg, list):
        yield "".join(self.__format_args(
            arg, context, split_content = False))
      else:
        raise AssertionError("Invalid argument.")
