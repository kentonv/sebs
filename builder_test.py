#! /usr/bin/python
# Scalable Extensible Build System
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

# TODO(kenton): Test DryRunner and SubprocessRunner.

import unittest

from sebs.core import Artifact, Action, Rule, Context, DefinitionError
from sebs.filesystem import VirtualDirectory
from sebs.builder import Builder, ActionRunner

class MockRunner(ActionRunner):
  def __init__(self):
    self.actions = []
  
  def run(self, action):
    self.actions.append(action)
    return True

class MockContext(Context):
  def __init__(self, filename, full_filename):
    super(MockContext, self).__init__()
    self.filename = filename
    self.full_filename = full_filename

DUMMY_RULE = Rule(MockContext("mock.sebs", "src/mock.sebs"))

class BuilderTest(unittest.TestCase):
  def setUp(self):
    self.dir = VirtualDirectory()
  
  def doBuild(self, *artifacts):
    builder = Builder(self.dir)
    runner = MockRunner()
    for artifact in artifacts:
      builder.add_artifact(artifact)
    builder.build(runner)
    return runner.actions

  def testNoAciton(self):
    input = Artifact("input", None)
    
    self.assertRaises(DefinitionError, self.doBuild, input)
    self.dir.add("input", 2, "")
    self.assertEqual([], self.doBuild(input))

  def testSimpleAction(self):
    input = Artifact("input", None)
    action = Action(DUMMY_RULE, [input], "")
    output = Artifact("output", action)
    
    # output doesn't exist.
    self.dir.add("input", 2, "")
    self.assertEqual([action], self.doBuild(output))
    
    # output exists but is older than input.
    self.dir.add("output", 1, "")
    self.assertEqual([action], self.doBuild(output))

    # output exists and is newer than input.
    self.dir.add("output", 4, "")
    self.assertEqual([], self.doBuild(output))

  def testMultipleInputsAndOutputs(self):
    in1 = Artifact("in1", None)
    in2 = Artifact("in2", None)
    action = Action(DUMMY_RULE, [in1, in2], "")
    out1 = Artifact("out1", action)
    out2 = Artifact("out2", action)
    
    # outputs don't exist.
    self.dir.add("in1", 2, "")
    self.dir.add("in2", 4, "")
    self.assertEqual([action], self.doBuild(out1, out2))
    
    # only one output exists
    self.dir.add("out1", 5, "")
    self.assertEqual([action], self.doBuild(out1, out2))
    self.assertEqual([], self.doBuild(out1))
    
    # both outputs exist, one is outdated
    self.dir.add("out2", 1, "")
    self.assertEqual([action], self.doBuild(out1, out2))
    self.assertEqual([], self.doBuild(out1))

    # both outputs exist, one is older than *one* of the inputs
    self.dir.add("out2", 3, "")
    self.assertEqual([action], self.doBuild(out1, out2))
    self.assertEqual([], self.doBuild(out1))

    # both outputs exist and are up-to-date.
    self.dir.add("out2", 5, "")
    self.assertEqual([], self.doBuild(out1, out2))

  def testActionWithDependency(self):
    input = Artifact("input", None)
    action1 = Action(DUMMY_RULE, [input], "")
    temp = Artifact("temp", action1)
    action2 = Action(DUMMY_RULE, [temp], "")
    output = Artifact("output", action2)
    
    # outputs don't exist.
    self.dir.add("input", 2, "")
    self.assertEqual([action1, action2], self.doBuild(output))
    self.assertEqual([action1], self.doBuild(temp))

    # temp exists but is outdated.
    self.dir.add("temp", 1, "")
    self.assertEqual([action1, action2], self.doBuild(output))
    self.assertEqual([action1], self.doBuild(temp))

    # temp exists and is up-to-date.
    self.dir.add("temp", 3, "")
    self.assertEqual([action2], self.doBuild(output))
    self.assertEqual([], self.doBuild(temp))

    # output exists but is outdated.
    self.dir.add("output", 1, "")
    self.assertEqual([action2], self.doBuild(output))
    self.assertEqual([], self.doBuild(temp))

    # output exists and is up-to-date.
    self.dir.add("output", 4, "")
    self.assertEqual([], self.doBuild(output))
    self.assertEqual([], self.doBuild(temp))

    # temp is outdated but output is up-to-date.
    self.dir.add("temp", 1, "")
    self.assertEqual([action1, action2], self.doBuild(output))
    self.assertEqual([action1], self.doBuild(temp))

  def testDiamondDependency(self):
    input = Artifact("input", None)
    action1 = Action(DUMMY_RULE, [input], "")
    temp1 = Artifact("temp1", action1)
    action2 = Action(DUMMY_RULE, [input], "")
    temp2 = Artifact("temp2", action2)
    action3 = Action(DUMMY_RULE, [temp1, temp2], "")
    output = Artifact("output", action3)
    
    # outputs don't exist.
    self.dir.add("input", 2, "")
    self.assertEqual([action1, action2, action3], self.doBuild(output))
    self.assertEqual([action1], self.doBuild(temp1))
    self.assertEqual([action2], self.doBuild(temp2))

    # one side is up-to-date, other isn't.
    self.dir.add("temp1", 3, "")
    self.dir.add("output", 4, "")
    self.assertEqual([action2, action3], self.doBuild(output))
    self.assertEqual([], self.doBuild(temp1))
    self.assertEqual([action2], self.doBuild(temp2))

    # everything up-to-date.
    self.dir.add("temp2", 3, "")
    self.assertEqual([], self.doBuild(output))
    self.assertEqual([], self.doBuild(temp1))
    self.assertEqual([], self.doBuild(temp2))

    # original input too new.
    self.dir.add("input", 6, "")
    self.assertEqual([action1, action2, action3], self.doBuild(output))
    self.assertEqual([action1], self.doBuild(temp1))
    self.assertEqual([action2], self.doBuild(temp2))

if __name__ == "__main__":
  unittest.main()
