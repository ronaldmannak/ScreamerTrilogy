"""Exact original S1 profile. No timing, renderer or game-code patches."""
from collections import Counter,defaultdict
import hashlib
from le_image import parse_le,map_file,require,u32

EXE_SHA256='1246afc95463f96598d5fee764fc99c847b6d3e0bf8ca2268bd362c664bb28a3'
RAM_SIZE=16*1024*1024
WAIT_LINK=0x1fc40
PENDING_LINK=0x107f9
LINKS={'rows':0x102fa4,'models':0x121540,'camera':0x8a7ac,'main_camera':0x1109a0,
       'scene_list':0x106350,'materials':0x121544,'animation_clock':0x12153c,
       'smoothed_dt':0x118e04,'raw_dt':0x118e08,'elapsed':0x118e10,'pending':PENDING_LINK,
       'world_name':0x12154c}


def executable_profile(data):
    require(hashlib.sha256(data).hexdigest()==EXE_SHA256,'Original STARTH.EXE hash mismatch')
    objects,fixups,page_size,data_start=parse_le(data)
    off=map_file(objects,page_size,data_start,WAIT_LINK)
    require(data[off:off+11]==bytes.fromhex('8b15f907000083fa0272f5'),'Original S1 two-tick helper differs')
    return objects,fixups,page_size,data_start


def resolve(memory,objects,fixups):
    require(len(memory)==RAM_SIZE,'S1 capture must be exactly16MiB')
    found=[];start=0
    while True:
        at=memory.find(bytes.fromhex('83fa0272f5'),start)
        if at<0:break
        start=at+1;helper=at-6
        if helper>=0 and memory[helper:helper+2]==b'\x8b\x15' and u32(memory,helper+2)==helper-(WAIT_LINK-PENDING_LINK):
            found.append(helper)
    require(len(found)==1,f'Expected one S1 wait helper, found {found}')
    code=found[0]-(WAIT_LINK-0x10000);bases={1:code};evidence={}
    for obj in objects:
        votes=Counter();refs=defaultdict(list)
        for f in fixups:
            if f['source_object']!=1 or f['target_object']!=obj['index']:continue
            at=code+f['source_offset']
            if not 0<=at<=len(memory)-4:continue
            candidate=u32(memory,at)-f['target_offset']
            if 0<=candidate and candidate%16==0 and candidate+obj['virtual_size']<=len(memory):
                votes[candidate]+=1;refs[candidate].append({'operand_physical':at,'target_offset':f['target_offset']})
        if votes:
            winner,n=votes.most_common(1)[0]
            require(obj['index']!=1 or winner==code,'Code mapping contradicted by fixups')
            require(n>=2,'Insufficient independent relocation evidence')
            bases[obj['index']]=winner;evidence[str(obj['index'])]={'matching_fixups':n,'candidate_count':len(votes),'examples':refs[winner][:5]}
    require(set(bases)=={1,2,3},'Not all S1 objects resolved')
    loaded=[dict(index=o['index'],link_base=o['link_base'],physical_base=bases[o['index']],virtual_size=o['virtual_size']) for o in objects]
    for field in ('link_base','physical_base'):
        values=sorted(loaded,key=lambda o:o[field])
        require(all(a[field]+a['virtual_size']<=b[field] for a,b in zip(values,values[1:])),'Overlapping S1 LE objects')
    def physical(link,size=4):
        for obj in loaded:
            delta=link-obj['link_base']
            if 0<=delta and size<=obj['virtual_size']-delta:return obj['physical_base']+delta
        raise ValueError(f'Unknown S1 link range {link:#x}+{size}')
    markers={name:{'link_address':va,'physical_address':physical(va),'u32':u32(memory,physical(va))} for name,va in LINKS.items()}
    return loaded,evidence,markers,physical
