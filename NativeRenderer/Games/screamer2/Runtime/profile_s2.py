"""Exact Screamer2 3dfx profile; original two-tick timing, no guest patches."""
import collections,hashlib,struct
from le_image import parse_le,map_file,require,u32
EXE_SHA256='e6c24c84650938f2baee5f4b571baa45bb09a93ba12dd24e3e1d2cefd9b6f3ec'
OVL_SHA256='6981a7bd77445be7b360ca367af1e527927db396546db15b69803b16a67676a9'
RAM_SIZE=16*1024*1024
WAIT_LINK=0x519B4
PENDING_LINK=0x519EA
LINKS={'rows':0x133710,'models':0x154760,'scene':0x13DEB4,'camera':0x8383C,
       'view_cameras':0x1396CC,'textures':0x154DA4,'libraries':0x1547F0,
       'animation_clock':0x154770,'dispatch':0x7B310,'environment':0xAC0D8,
       'smoothed_dt':0x153D88,'raw_dt':0x153D8C,'pending_ticks':PENDING_LINK}

def executable_profile(data):
 require(hashlib.sha256(data).hexdigest()==EXE_SHA256,'Original S2_3DFX executable hash mismatch')
 objects,fixups,page_size,data_start=parse_le(data)
 off=map_file(objects,page_size,data_start,WAIT_LINK)
 require(data[off:off+13]==bytes.fromhex('50a1ea19030083f8027cf658c3'),'Original two-tick S2 helper differs')
 return objects,fixups,page_size,data_start

def resolve(memory,objects,fixups):
 require(len(memory)==RAM_SIZE,'S2 capture must contain exactly16MiB RAM')
 matches=[];start=0;tail=bytes.fromhex('83f8027cf658c3')
 while True:
  at=memory.find(tail,start)
  if at<0:break
  start=at+1;helper=at-6
  if helper>=0 and memory[helper:helper+2]==b'\x50\xa1'and u32(memory,helper+2)==helper+0x36:matches.append(helper)
 require(len(matches)==1,f'Expected one relocated S2 two-tick wait helper,found{matches}')
 code=matches[0]-(WAIT_LINK-0x20000);bases={2:code};evidence={}
 for obj in objects:
  votes=collections.Counter();refs=collections.defaultdict(list)
  for fix in fixups:
   if fix['source_object']!=2 or fix['target_object']!=obj['index']:continue
   address=code+fix['source_offset']
   if not 0<=address<=len(memory)-4:continue
   candidate=u32(memory,address)-fix['target_offset']
   if candidate>=0 and candidate+obj['virtual_size']<=len(memory)and candidate%16==0:
    votes[candidate]+=1;refs[candidate].append({'operand_physical':address,'target_offset':fix['target_offset']})
  if votes:
   winner,count=votes.most_common(1)[0]
   require(obj['index']!=2 or winner==code,'Code fixups contradict wait-derived mapping')
   if count>=2 or obj['index']==2:
    bases[obj['index']]=winner;evidence[str(obj['index'])]={'matching_fixups':count,'candidate_count':len(votes),'examples':refs[winner][:5]}
 require(6 in bases,'No independently relocated S2 data object')
 loaded=[{'index':o['index'],'link_base':o['link_base'],'physical_base':bases[o['index']],'virtual_size':o['virtual_size']}for o in objects if o['index']in bases]
 for field in ('link_base','physical_base'):
  ordered=sorted(loaded,key=lambda o:o[field]);require(all(a[field]+a['virtual_size']<=b[field]for a,b in zip(ordered,ordered[1:])),'Overlapping LE object mapping')
 def physical(link,size=4):
  for o in loaded:
   delta=link-o['link_base']
   if 0<=delta and size<=o['virtual_size']-delta:return o['physical_base']+delta
  raise ValueError(f'Unknown S2 link range{link:#x}+{size}')
 markers={name:{'link_address':va,'physical_address':physical(va),'u32':u32(memory,physical(va))}for name,va in LINKS.items()}
 return loaded,evidence,markers,physical
