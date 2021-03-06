#! /usr/bin/python
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

    self.assertEqual(123, typecheck(123, [int, float, str]))
    self.assertEqual(1.5, typecheck(1.5, [int, float, str]))
    self.assertEqual("foo", typecheck("foo", [int, float, str]))
    self.assertRaises(TypeError, typecheck, [12], [int, float, str])

if __name__ == "__main__":
  unittest.main()
