##!/usr/bin/env python3
import unittest
import sys
import os
from pynlpl.formats import folia

TESTDIR = "./"

class FoLiAUpdate(unittest.TestCase):
    def setUp(self):
        self.doc = folia.Document(TESTDIR)

    def test001_declaration(self):
        """Checking for presence of corrections declaration"""
        self.assertTrue( self.doc.declared(folia.Correction,"https://raw.githubusercontent.com/proycon/folia/master/setdefinitions/spellingcorrection.foliaset.xml") )

if __name__ == '__main__':
    try:
        TESTDIR = sys.argv[1]
        if not os.path.isdir(TESTDIR):
            print("Test directory does not exist",file=sys.stderr)
            sys.exit(2)
    except:
        print("Expected one argument: test directory",file=sys.stderr)
        sys.exit(2)


