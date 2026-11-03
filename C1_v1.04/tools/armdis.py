"""Annotated ARM disassembly: dis.py app.bin start end. Tracks reg constants, resolves strings."""
import sys,struct,re
from capstone import *
from capstone.arm import *
B=0x10000
d=open(sys.argv[1],'rb').read()
st,en=int(sys.argv[2],16),int(sys.argv[3],16)
md=Cs(CS_ARCH_ARM,CS_MODE_ARM); md.detail=True; md.skipdata=True
def s_at(v):
    o=v-B
    if 0<=o<len(d):
        e=d.find(b'\0',o,o+120)
        if e>o+2:
            t=d[o:e]
            if all(32<=c<127 or c in (9,10,13,27) for c in t): return t.decode('latin1').replace('\x1b[1;31m','').replace('\n','\\n')
    return None
regs={}
for ins in md.disasm(d[st-B:en-B],st):
    note=''
    if ins.id==0:
        print(f"{ins.address:08x}: .word"); continue
    ops=ins.operands
    try:
        m=ins.mnemonic
        if m.startswith('movw') and len(ops)==2: regs[ops[0].reg]=ops[1].imm&0xffff
        elif m.startswith('movt') and ops[0].reg in regs: regs[ops[0].reg]=(regs[ops[0].reg]&0xffff)|((ops[1].imm&0xffff)<<16)
        elif m.split('.')[0] in ('add','sub','adr') and len(ops)>=2 and (ops[1].type==ARM_OP_IMM or (len(ops)==3 and ops[1].type==ARM_OP_REG and ops[1].reg==ARM_REG_PC and ops[2].type==ARM_OP_IMM)):
            imm=ops[-1].imm
            regs[ops[0].reg]=ins.address+8+(-imm if m.startswith('sub') else imm) if m!='adr' else imm
        elif m=='add' and len(ops)==3 and ops[2].type==ARM_OP_REG and ops[1].reg==ARM_REG_PC and ops[2].reg in regs:
            regs[ops[0].reg]=(ins.address+8+regs[ops[2].reg])&0xffffffff
        elif m=='add' and len(ops)==3 and ops[1].type==ARM_OP_REG and ops[2].type==ARM_OP_REG and ops[2].reg==ARM_REG_PC and ops[1].reg in regs:
            regs[ops[0].reg]=(ins.address+8+regs[ops[1].reg])&0xffffffff
        elif m.startswith('add') and len(ops)==3 and ops[2].type==ARM_OP_IMM and ops[1].reg in regs:
            regs[ops[0].reg]=regs[ops[1].reg]+ops[2].imm
        elif m.startswith('ldr') and len(ops)==2 and ops[1].type==ARM_OP_MEM and ops[1].mem.base==ARM_REG_PC:
            a=ins.address+8+ops[1].mem.disp; regs[ops[0].reg]=struct.unpack_from('<I',d,a-B)[0]
        elif m=='mov' and len(ops)==2 and ops[1].type==ARM_OP_REG and ops[1].reg in regs: regs[ops[0].reg]=regs[ops[1].reg]
        elif m in ('mov','mvn') and len(ops)==2 and ops[1].type==ARM_OP_IMM: regs[ops[0].reg]=ops[1].imm&0xffffffff
        elif ops and ops[0].type==ARM_OP_REG and m not in ('cmp','tst','str','strb','strh','push','stm','cmn') and not m.startswith('b'):
            regs.pop(ops[0].reg,None)
        if ops and ops[0].type==ARM_OP_REG and ops[0].reg in regs and m.split('.')[0] in ('movw','movt','add','ldr','mov','mvn','adr','sub'):
            v=regs[ops[0].reg]; s=s_at(v)
            note=f'  ; =0x{v:x}'+(f' "{s[:70]}"' if s else '')
        if m in ('bl','blx') or m=='pop': regs={k:v for k,v in regs.items() if k not in (ARM_REG_R0,ARM_REG_R1,ARM_REG_R2,ARM_REG_R3,ARM_REG_R12)}
    except Exception as e: note=' ; ?'
    print(f'{ins.address:08x}: {ins.mnemonic:8s} {ins.op_str}{note}')
