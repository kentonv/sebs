#! /usr/bin/python
# Scalable Extendable Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.
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

import traceback
import unittest

from sebs.core import Context, Rule, Artifact, Action, DefinitionError

class MockContext(Context):
  def __init__(self, filename, full_filename):
    super(MockContext, self).__init__()
    self.filename = filename
    self.full_filename = full_filename

class MockRule(Rule):
  def __init__(self, context):
    super(MockRule, self).__init__(context)

class CoreTest(unittest.TestCase):
  # There's really not that much that we can test here.
  
  def testCurrentContext(self):
    this_file, line, _, _ = traceback.extract_stack(limit = 1)[0]
    context = MockContext("foo.sebs", this_file)
    rule = context.run(Rule)
    self.assertTrue(Context.current() is None)
    self.assertTrue(rule.context is context)
    self.assertEqual(rule.line, line + 2)
    
    self.assertEqual("foo.sebs:%d" % (line + 2), rule.name)
    rule.label = "foo"
    self.assertEqual("foo.sebs:foo", rule.name)
  
  def testAddCommand(self):
    artifact = Artifact("foo", None)
    other_artifact = Artifact("bar", None)
    rule = MockRule(MockContext("foo.sebs", "src/foo.sebs"))
    action = Action(rule, [artifact])
    
    # Should work.
    command = ["foo", artifact, artifact.contents(),
                ["bar", artifact, artifact.contents()]]
    action.add_command(command)
    self.assertEqual(command, action.commands[0])
    
    # Should not work.
    self.assertRaises(TypeError, action.add_command, "foo")
    self.assertRaises(TypeError, action.add_command, ["foo", 123])
    self.assertRaises(TypeError, action.add_command, [[123, "bar"]])
    self.assertRaises(DefinitionError, action.add_command, [other_artifact])
    self.assertRaises(DefinitionError, action.add_command,
                      [other_artifact.contents()])

if __name__ == "__main__":
  unittest.main()
