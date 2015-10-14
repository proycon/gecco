
nonumbers = staticmethod(lambda word: word.cls not in ('NUMBER','DATE','NUMBER-YEAR','CURRENCY','FRACNUMBER'))
hasalpha = staticmethod(lambda word: any( ( c.isalpha() for c in str(word) ) ))
