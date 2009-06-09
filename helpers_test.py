#! /usr/bin/python
# Scalable Extensible Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.

import unittest

from sebs.helpers import typecheck

class HelpersTest(unittest.TestCase):
  def testTypecheck(self):
    self.assertEqual(123, typecheck(123, int))
    self.assertRaises(TypeError, typecheck, "foo", int)
    self.assertTrue(typecheck(None, int) is None)
    self.assertEqual([123, 456], typecheck([123, 456], list, int))
    self.assertRaises(TypeError, typecheck, ["foo", "bar"], list, int)
    self.assertRaises(TypeError, typecheck, [123, "bar"], list, int)

if __name__ == "__main__":
  unittest.main()
