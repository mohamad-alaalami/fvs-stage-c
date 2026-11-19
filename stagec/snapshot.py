"""Reader for complete StageC1 binary continuation states (little-endian)."""
import struct

def decode(data):
    pos=0
    def scalar(fmt):
        nonlocal pos
        size=struct.calcsize(fmt);value=struct.unpack_from(fmt,data,pos)[0];pos+=size;return value
    def string():
        nonlocal pos
        n=scalar('<Q');assert pos+n<=len(data);value=data[pos:pos+n].decode();pos+=n;return value
    def vector(kind):
        nonlocal pos
        n=scalar('<Q');assert n<=len(data)
        if kind in ('int','bool'):
            fmt='i' if kind=='int' else '?';width=4 if kind=='int' else 1
            values=struct.unpack_from('<'+str(n)+fmt,data,pos);pos+=n*width;return values
        return [string() if kind=='string' else vector(kind[0]) for _ in range(n)]
    result={'magic':string(),'variant':string()};assert result['magic']=='STAGEC1'
    for field in ['depth','phase','pivot','root','N','M','deleted']:result[field]=scalar('<i')
    result['changeInU']=scalar('<?')
    for field,kind in [('neighbours',['int']),('neighDouble',['bool']),('doubleNum','int'),('posAtNeigh',['int']),('status','int'),('oldNumbers','int'),('X','int'),('selfLoops','int'),('deg2ToReduce','int'),('vis','int'),('ccNr','int'),('ccVertices',['int']),('fuRepr','int'),('fuWeight','int'),('stageNames','string')]:result[field]=vector(kind)
    result['solFound']=scalar('<?');result['branching_hints']=vector('int');result['sol']=vector('int');result['isSub']=scalar('<?')
    result['solver_depth']=scalar('<i');result['size_cap']=scalar('<i');result['stageHint']=scalar('<?')
    if result['variant']=='8':result['br2']=scalar('<i')
    if result['variant']=='LP':result['kernelize_switch']=scalar('<?')
    assert pos==len(data),(pos,len(data))
    n=result['N'];assert len(result['status'])==len(result['neighbours'])==len(result['stageNames'])==n
    assert 0<=result['pivot']<n
    for neighbors,doubles,positions in zip(result['neighbours'],result['neighDouble'],result['posAtNeigh']):
        assert len(neighbors)==len(doubles)==len(positions)
        assert all(0<=v<n for v in neighbors)
    return result

if __name__=='__main__':
    import sys,json
    with open(sys.argv[1],'rb') as f:f.seek(int(sys.argv[2]));state=decode(f.read(int(sys.argv[3])))
    print(json.dumps(state,indent=2))
