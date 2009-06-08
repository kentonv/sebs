#! /usr/bin/python
# Scalable Extensible Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.

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
