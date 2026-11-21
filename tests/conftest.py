import os,tempfile
# Tests use an isolated state tree and never alter the user's real research.
os.environ['THERAPY_DATA_HOME']=tempfile.mkdtemp(prefix='therapy-test-')+'/data'
