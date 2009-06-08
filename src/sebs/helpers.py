# Scalable Extensible Build System
# Copyright (c) 2009 Kenton Varda.  All rights reserved.

def typecheck(value, type, element_type=None):
  if value is not None:
    if not isinstance(value, type):
      raise TypeError("Expected %s, got: %s" % (type, value))
    if element_type is not None:
      for element in value:
        typecheck(element, element_type)
  # So typecheck can be used within an expression.
  return value
