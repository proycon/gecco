from pynlpl.formats import folia

nonumbers = staticmethod(lambda word: not isinstance(word, folia.Word) or (isinstance(word,folia.Word) and word.cls not in ('NUMBER','DATE','NUMBER-YEAR','CURRENCY','FRACNUMBER')))
hasalpha = staticmethod(lambda word: any( ( c.isalpha() for c in str(word) ) ))
