#! /usr/bin/python
# Scalable Extensible Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.

import unittest

from sebs.core import DefinitionError
from sebs.filesystem import VirtualDirectory
from sebs.loader import Loader

class LoaderTest(unittest.TestCase):
  def setUp(self):
    self.dir = VirtualDirectory()
    self.loader = Loader(self.dir)
    
  def testBasics(self):
    self.dir.add("src/foo.sebs", 0, """
x = 123
_private = "hi"
a_rule = Rule()
nested_rule = [Rule()]
""")
    file = self.loader.load("foo.sebs")
    
    self.assertTrue("sebs_import" not in file.__dict__)
    self.assertTrue("Rule" not in file.__dict__)
    self.assertTrue("_private" not in file.__dict__)
    self.assertEqual(123, file.x)
    self.assertEqual("a_rule", file.a_rule.label)
    self.assertTrue(file.nested_rule[0].label is None)
    self.assertEqual(4, file.a_rule.line)
    self.assertEqual(5, file.nested_rule[0].line)
    self.assertEqual("foo.sebs:a_rule", file.a_rule.name)
    self.assertEqual("foo.sebs:5", file.nested_rule[0].name)

  def testImport(self):
    self.dir.add("src/foo.sebs", 0, """bar = sebs_import("bar.sebs")""")
    self.dir.add("src/bar.sebs", 0, """x = 123""")
    file = self.loader.load("foo.sebs")
    self.assertTrue(file.bar is self.loader.load("bar.sebs"))
    self.assertEqual(123, file.bar.x)
    
  def testCycle(self):
    self.dir.add("src/foo.sebs", 0, """sebs_import("foo.sebs")""")
    self.assertRaises(DefinitionError, self.loader.load, "foo.sebs")

class ContextImplTest(unittest.TestCase):
  def setUp(self):
    self.dir = VirtualDirectory()
    self.dir.add("src/foo/bar.sebs", 0, """
mock_rule = Rule()
return_context = mock_rule.context
""")

    self.loader = Loader(self.dir)
    self.file = self.loader.load("foo/bar.sebs")
    self.context = self.file.return_context
    
  def testBasics(self):
    self.assertEqual("foo/bar.sebs", self.context.filename)
    self.assertEqual("src/foo/bar.sebs", self.context.full_filename)
    
  def testSourceArtifact(self):
    artifact1 = self.context.source_artifact("qux")
    artifact2 = self.context.source_artifact("corge")
    self.assertTrue(artifact1 is self.context.source_artifact("qux"))
    self.assertEqual("src/foo/qux", artifact1.filename)
    self.assertTrue(artifact1.action is None)
    self.assertFalse(artifact2 is artifact1)
    
    # Trying to create an artifact outside the directory fails.
    self.assertRaises(DefinitionError,
        self.context.source_artifact, "../parent")

  def testAction(self):
    artifact = self.loader.source_artifact("blah")
    action = self.context.action(self.file.mock_rule, [artifact], "run", "foo")
    
    self.assertEqual("run", action.verb)
    self.assertEqual("foo", action.name)
    
    self.assertEqual(1, len(action.inputs))
    self.assertTrue(action.inputs[0] is artifact)

    action2 = self.context.action(self.file.mock_rule, [], verb = "test")
    self.assertEqual("test", action2.verb)
    
    self.assertEqual("run: foo", action.message())
    self.assertEqual("test: foo/bar.sebs:mock_rule", action2.message())
    
  def testDerivedArtifact(self):
    action = self.context.action(self.file.mock_rule, [])
    
    tmp_artifact = self.context.intermediate_artifact("grault", action)
    self.assertEqual("tmp/foo/grault", tmp_artifact.filename)
    self.assertTrue(tmp_artifact.action is action)
    
    bin_artifact = self.context.output_artifact("bin", "garply", action)
    self.assertEqual("bin/garply", bin_artifact.filename)
    self.assertTrue(bin_artifact.action is action)
    
    # Derived artifacts are added to the creating action.
    self.assertEqual(2, len(action.outputs))
    self.assertTrue(action.outputs[0] is tmp_artifact)
    self.assertTrue(action.outputs[1] is bin_artifact)
    
    # Creating the same temporary artifact twice fails.
    self.assertRaises(DefinitionError,
        self.context.intermediate_artifact, "grault", action)
    
    # Trying to create an artifact outside the directory fails.
    self.assertRaises(DefinitionError,
        self.context.intermediate_artifact, "../parent", action)
    self.assertRaises(DefinitionError,
        self.context.intermediate_artifact, "/root", action)

    # Creating the same output artifact twice fails.
    self.assertRaises(DefinitionError,
        self.context.output_artifact, "bin", "garply", action)

    # Only certain directories are allowable for output artifact.s
    self.assertRaises(DefinitionError,
        self.context.output_artifact, "baddir", "waldo", action)

if __name__ == "__main__":
  unittest.main()
