"""Independent bigint controls for int32 dense and wide dot bounds."""
import hashlib
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
from integer_oracle import nearest

I32_MIN,I32_MAX=-(1<<31),(1<<31)-1
I64_MAX=(1<<63)-1
OK,INVALID,EXHAUSTED=0,2,9


def main():
    rng=random.Random(20261015);source=[];expected=[]
    def add(args,status,value=0):
        source.append(struct.pack("<8Q",*(v&((1<<64)-1) for v in args)))
        expected.append(struct.pack("<Iq",status,value if status==OK else 0))
    for _ in range(16000):
        count=rng.choice([0,1,2,640,(1<<31)-1,(1<<32)-1,rng.getrandbits(32)])
        ia=rng.choice([0,1,32768,(1<<31)-1,1<<31,(1<<31)+1,rng.getrandbits(32)])
        wa=rng.choice([0,1,127,128,129,rng.randrange(256)])
        bias=rng.choice([0,1,I64_MAX-1,I64_MAX,1<<63,(1<<64)-1,rng.getrandbits(64)])
        mul=rng.choice([0,1,2,(1<<32)-1,rng.getrandbits(32)]);shift=rng.choice([0,1,31,63,64])
        bound=count*ia*wa+bias
        status=INVALID if mul==0 or shift>63 or ia>1<<31 or wa>128 else EXHAUSTED if bound>I64_MAX or bound*mul>I64_MAX else OK
        add([0,count,ia,wa,bias,mul,shift,0],status,bound)
    for _ in range(16000):
        x=[rng.choice([I32_MIN,I32_MAX,-32769,32768,-3,-1,0,1,3,rng.randint(I32_MIN,I32_MAX)]) for _ in range(2)]
        w=[rng.choice([-128,-1,0,1,127]) for _ in range(2)]
        bias=rng.choice([-(1<<63),-I64_MAX,I64_MAX,0,rng.randint(-100000,100000)])
        mul=rng.choice([0,1,2,(1<<32)-1]);shift=rng.choice([0,1,16,31,63,64])
        bound=2*max(map(abs,x))*max(map(abs,w))+abs(bias)
        if mul==0 or shift>63:status,value=INVALID,0
        elif bound>I64_MAX or bound*mul>I64_MAX:status,value=EXHAUSTED,0
        else:
            value=nearest((bias+sum(a*b for a,b in zip(x,w)))*mul,1<<shift)
            status=OK if I32_MIN<=value<=I32_MAX else EXHAUSTED
        add([1,*x,*w,bias,mul,shift],status,value)
    want=b"".join(expected)
    with tempfile.TemporaryDirectory(prefix="duoforge-wide-oracle-") as temp:
        inp=Path(temp)/"vectors.bin";out=Path(temp)/"results.bin";inp.write_bytes(b"".join(source))
        subprocess.run([sys.argv[1],"--wide",str(inp),str(out)],check=True)
        got=out.read_bytes()
    if got!=want:
        index=next((i//12 for i,(a,b) in enumerate(zip(got,want)) if a!=b),min(len(got),len(want))//12)
        raise AssertionError(f"wide arithmetic vector {index}; sizes {len(got)}/{len(want)}")
    print(f"wide arithmetic: {len(source)} exact independent vectors; SHA256={hashlib.sha256(got).hexdigest()}")


if __name__=="__main__":main()
