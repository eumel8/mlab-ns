#!/usr/bin/env python
#
# Copyright 2010 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

try:
  from .pipeline import *
except ImportError as e:
  import logging
  logging.warning(
      'Could not load Pipeline API. Will fix path for testing. %s: %s',
      e.__class__.__name__, str(e))
  from . import testutil
  testutil.fix_path()
  del logging
  from .pipeline import *
