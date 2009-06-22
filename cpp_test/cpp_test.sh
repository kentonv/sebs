#! /bin/bash
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

export PYTHONPATH=src
SEBS='python -m sebs.main'

set -e

function expect_contains() {
  if ! grep -q "$2" $1; then
    echo "Missing expected output: $2" >&2
    exit 1
  fi
}

function expect_success() {
  if ! eval $1; then
    echo "Command was expected to fail: $1" >&2
    exit 1
  fi
}

function expect_failure() {
  if eval $1; then
    echo "Command was expected to fail: $1" >&2
    exit 1
  fi
}

# TODO(kenton):  Use a separate directory for output.
echo "Cleaning..."

rm -rf tmp/sebs/cpp_test/*.o tmp/sebs/cpp_test/*.a bin/sebs_cpp_test
mkdir -p tmp/sebs/cpp_test

echo "Building test binary..."

OUTPUT=tmp/sebs/cpp_test/output

expect_success "$SEBS build sebs/cpp_test/cpp_test.sebs:prog &> $OUTPUT"

expect_contains $OUTPUT '^compile: src/sebs/cpp_test/main.cc$'
expect_contains $OUTPUT '^compile: src/sebs/cpp_test/bar.cc$'
expect_contains $OUTPUT '^link: sebs/cpp_test/cpp_test.sebs:bar$'
expect_contains $OUTPUT '^compile: src/sebs/cpp_test/foo.cc$'
expect_contains $OUTPUT '^link: sebs/cpp_test/cpp_test.sebs:foo$'
expect_contains $OUTPUT '^link: sebs/cpp_test/cpp_test.sebs:prog$'

echo "Running test binary..."

expect_success './bin/sebs_cpp_test &> $OUTPUT'

expect_contains $OUTPUT '^FooFunction(foo) BarFunction(bar) FooFunction(bar) $'

echo "Running passing test..."

expect_success "$SEBS test sebs/cpp_test/cpp_test.sebs:passing_test &> $OUTPUT"

# TODO(kenton):  When SEBS is fixed to only use color when outputting to a
#   terminal, we can make these matches more precise.  (Below, too.)
expect_contains $OUTPUT 'PASS:.* sebs/cpp_test/cpp_test.sebs:passing_test$'

expect_contains tmp/sebs/cpp_test/passing_test_output.txt \
  '^BarFunction(test) FooFunction(test) $'

echo "Running failing test..."

expect_failure "$SEBS test sebs/cpp_test/cpp_test.sebs:failing_test &> $OUTPUT"

expect_contains $OUTPUT 'FAIL:.* sebs/cpp_test/cpp_test.sebs:failing_test$'

expect_contains tmp/sebs/cpp_test/failing_test_output.txt \
  '^FooFunction(fail) $'

echo "PASS"
