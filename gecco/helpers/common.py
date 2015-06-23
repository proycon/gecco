
def stripsourceextensions(filename):
    #strip some common source extensions
    return filename.replace('.txt','').replace('.bz2','').replace('.gz','').replace('.tok','')
