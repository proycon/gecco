##!/usr/bin/env python3
import unittest
import sys
import os
import folia.main as folia

TESTDIR = "./"


def findcorrectionbyannotator(test, elementid, annotator):
    for c in test.doc[elementid].select(folia.Correction):
        if c.annotator == annotator:
            return c
    return None

class FoLiAOutput(unittest.TestCase):
    def setUp(self):
        self.doc = folia.Document(file=TESTDIR + "/test.folia.xml")

    def test001_declaration(self):
        """Checking for presence of corrections declaration"""
        self.assertTrue( self.doc.declared(folia.Correction,"https://raw.githubusercontent.com/proycon/folia/master/setdefinitions/spellingcorrection.foliaset.xml") )

    def test002_errorlist(self):
        """Checking errorlist output"""
        correction = findcorrectionbyannotator(self,'untitled.p.1.s.1.w.3','errorlist')
        self.assertTrue(correction, "Checking presence of suggestion for correction for errorlist" )
        self.assertEqual(correction.cls,'nonworderror',"Checking class")
        self.assertEqual(correction.suggestions(0).text() , "apparently", "Checking for correct suggestion" )

    def test003_aspell(self):
        """Checking aspell output"""
        correction = findcorrectionbyannotator(self,'untitled.p.1.s.1.w.3','aspell')
        self.assertTrue(correction, "Checking presence of suggestion for correction for aspell" )
        self.assertEqual(correction.cls,'nonworderror',"Checking class")
        self.assertTrue( any( s.text() == "apparently" for s in correction.suggestions() ),"Checking for correct suggestion" )

    def test004_lexicon(self):
        """Checking lexicon output"""
        correction = findcorrectionbyannotator(self,'untitled.p.1.s.1.w.6','lexicon')
        self.assertTrue(correction, "Checking presence of suggestion for correction for lexicon" )
        self.assertEqual(correction.cls,'nonworderror',"Checking class")
        self.assertTrue( any( s.text() == "conscious" for s in correction.suggestions() ),"Checking for correct suggestion" )

    def test005_confusible(self):
        """Checking confusible output"""
        correction = findcorrectionbyannotator(self,'untitled.p.1.s.2.w.10','conf_thenthan')
        self.assertTrue(correction, "Checking presence of suggestion for correction for confusible" )
        self.assertEqual(correction.cls,'confusible',"Checking class")
        self.assertEqual( correction.suggestions(0).text(), 'than' ,"Checking for correct suggestion" )
        self.assertEqual( correction.suggestions(0).confidence, 0.75 ,"Checking for confidence" )

    def test006_split(self):
        """Checking split output"""
        correction = self.doc['untitled.p.2.s.1.w.12'].next(folia.Correction)
        self.assertEqual( len(correction.current()), 2)
        self.assertEqual(correction.cls,'spliterror',"Checking class")
        self.assertEqual( correction.current().text(), 'mis takes')
        self.assertEqual( correction.suggestions(0).text(), 'mistakes')


if __name__ == '__main__':
    try:
        TESTDIR = sys.argv[1]
        if not os.path.isdir(TESTDIR):
            print("Test directory does not exist",file=sys.stderr)
            sys.exit(2)
    except IndexError:
        print("Expected one argument: test directory",file=sys.stderr)
        sys.exit(2)

    del sys.argv[1]

    unittest.main()


