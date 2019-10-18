import folia.main as folia

def stripsourceextensions(filename):
    #strip some common source extensions
    return filename.replace('.txt','').replace('.bz2','').replace('.gz','').replace('.tok','')


def makencname(name):
    ncname = ""
    for i, c in enumerate(name):
        if i == 0:
            if not c.isalpha() and c != '_':
                ncname += "I"
        if c.isalnum() or c in ('-','_','.'):
            ncname += c
    if not ncname:
        raise ValueError("Unable to convert '" + str(name) + "' to a valid XML NCName")
    return ncname

def folia2json(doc):
    data = []
    for correction in doc.data[0].select(folia.Correction):
        suggestions = []
        for suggestion in correction.suggestions():
            suggestions.append( {'suggestion': suggestion.text(), 'confidence': suggestion.confidence } )

        ancestor = correction.ancestor(folia.AbstractStructureElement)
        index = None
        if isinstance(ancestor, folia.Sentence):
            text = correction.current().text()
            index = 0
            for i, item in enumerate(ancestor):
                if isinstance(item, folia.Word):
                    index += 1
                if item is correction:
                    break
        elif isinstance(ancestor, folia.Word):
            text = ancestor.text()
            sentence = ancestor.ancestor(folia.Sentence)
            for i, word in enumerate(sentence.words()):
                if word is ancestor:
                    index = i
                    break
        if index is None:
            raise Exception("index not found")

        data.append( {'index': index, 'text': text, 'suggestions': suggestions, 'annotator': correction.annotator  } )
    return data
