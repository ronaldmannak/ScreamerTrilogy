#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Original S1 scene-list actors, split into independently animated part meshes."""
import argparse,hashlib,json,math,struct,shutil,uuid
from pathlib import Path
from export_scene import Scene,rotation,transform,require,u32,EXE_SHA
from s1_sky import export_sky
from profile_s1 import executable_profile,resolve,LINKS,RAM_SIZE


def actor_pointer(raw):
    """Decode original bit30 skip/bit31 disabled tags, never an active sign bit."""
    require(0<=raw<=0xffffffff and raw not in (0,0xffffffff),'Actor slot has no pointer')
    require(raw&0xc0000000!=0x80000000,'Unrecognized active actor pointer flag')
    return raw&0x3fffffff


def actor_slots(table):
    """Original collector skips -1 holes and ends at zero; preserve slot IDs."""
    require(len(table)%4==0,'Incomplete actor table')
    for index in range(min(512,len(table)//4)):
        raw=u32(table,4*index)
        if not raw:return
        if raw==0xffffffff:continue
        yield index,raw,actor_pointer(raw)
    raise ValueError('Unterminated actor list')


def actors(ram,physical):
    table=u32(ram,physical(LINKS['models']));model_bases=[]
    for i in range(4096):
        pointer=u32(ram,table+4*i)
        if pointer==0xffffffff:break
        require(0<=pointer<=len(ram)-0x330,'Unbounded actor model pointer')
        model_bases.append(pointer)
    else:raise ValueError('Unterminated model table')
    result=[]
    start=physical(LINKS['scene_list'])
    require(0<=start<=len(ram)-512*4,'Actor table exceeds captured RAM')
    for index,raw,pointer in actor_slots(memoryview(ram)[start:start+512*4]):
        require(0x1000<=pointer<=len(ram)-0x40,'Invalid original actor pointer')
        model=u32(ram,pointer);require(model<len(model_bases),'Invalid actor model')
        count=u32(ram,model_bases[model]+0x14)
        require(0<count<=65 and pointer+0x40+count*0x20<=len(ram),'Invalid actor part extent')
        result.append({'id':f'list:{index}','guest_address':pointer,'list_index':index,'model':model,'parts':count,
            'skipped':bool(raw&0x40000000),'flags':u32(ram,pointer+4),
            'position':list(struct.unpack_from('<3i',ram,pointer+8)),
            'angles':list(struct.unpack_from('<3i',ram,pointer+0x14)),
            'animation':struct.unpack_from('<i',ram,pointer+0x20)[0],
            'reflection_phase':u32(ram,pointer+0x3c)})
    return model_bases,result


def reflection_scroll(ram,actor):
    # Original C2434..C2479 FISTs these float32 actor accumulators using
    # FNINIT's nearest/ties-even mode, then keeps the low byte of X and Z.
    values=struct.unpack_from('<3f',ram,actor['guest_address']+0x30)
    result=[]
    for value in (values[0],values[2]):
        rounded=round(value) if math.isfinite(value) else -0x80000000
        if not -0x80000000<=rounded<=0x7fffffff:rounded=-0x80000000
        result.append((rounded&255)/256)
    return result


def part_pose(ram,actor,slot):
    at=actor['guest_address']+0x40+0x20*slot
    angles=struct.unpack_from('<3i',ram,at+8);position=struct.unpack_from('<3i',ram,at+0x14)
    root=rotation(actor['angles']);part=rotation(angles)
    combined=[[sum(root[row][k]*part[k][col] for k in range(3)) for col in range(3)] for row in range(3)]
    phase=u32(ram,actor['guest_address']+0x3c)
    return {'id':actor['id']+f':part:{slot}','model':actor['model'],'name':actor['id']+f':part:{slot}',
        'position':transform(root,actor['position'],position),'rotation':[v for row in combined for v in row],
        'angles':list(angles),'original_root':actor['id'],'part_slot':slot,
        'reflection_scroll':reflection_scroll(ram,actor),
        # Non-reflective actors may leave this field unused. The original A0
        # material binding separately validates real reflection phases.
        'reflection_phase':phase if phase<65536 else 0}


class DynamicScene(Scene):
    def __init__(self,game,track,output,ram,physical):
        super().__init__(game,track,output)
        self.bank=ram;self.model_bases,self.actors=actors(ram,physical);self.model_count=len(self.model_bases)
        self.dynamic=[]
        for actor in self.actors:
            for slot in range(actor['parts']):
                self.dynamic.append(part_pose(ram,actor,slot))
        require(0<len(self.dynamic)<=256,'Dynamic instance budget exceeds256')

    def objects(self):
        for actor in self.actors:
            for slot in range(actor['parts']):
                yield {'id':actor['id']+f':part:{slot}','dynamic_instance_id':actor['id']+f':part:{slot}',
                    'model':actor['model'],'flags':0,'position':[0,0,0],'angles':[0,0,0],
                    'animation':actor['animation'],'reflection_phase':actor['reflection_phase'],
                    'slots':[slot],'listing':1,'cell':None}

    def placement(self,model,slot):
        return [[1,0,0],[0,1,0],[0,0,1]],[0,0,0]

    def export(self):
        scene=super().export()
        active={b['instance_id'] for b in scene['batches']}
        scene['dynamic_instances']=[v for v in self.dynamic if v['id'] in active]
        scrolls={v['id']:v['reflection_scroll'] for v in self.dynamic}
        phases={v['id']:v['reflection_phase'] for v in self.dynamic}
        for batch in scene['batches']:
            if batch.get('texgen')=='s1-reflection':
                batch['reflection_scroll']=scrolls.get(batch.get('instance_id'),[0.,0.])
                batch['reflection_phase']=phases.get(batch.get('instance_id'),0)
        scene['coordinates']['vertices']='original per-part local; each batch instance_id chooses original animated world transform'
        scene['title']=f'Screamer original track{self.track}: independently animated actor parts'
        scene['statistics'].update(actor_roots=len(self.actors),dynamic_part_instances=len(scene['dynamic_instances']))
        scene['limitations']=['Original actor and part geometry, materials and captured world transforms; live bridge must update matching id+model poses.',
            'A0 opaque reflections retain authored per-vertex normals and original live actor reflection scroll; the renderer implements s1-reflection texgen.',
            'C0/E0 palette-effect material families remain explicitly omitted; see unsupported triangle counts.',
            'Texture damage/animation frame selection is frozen at this capture; independent part transforms are live-capable.',
            'Sky and original overlays require separate composition.']
        (self.output/'scene.json').write_text(json.dumps(scene,indent=2)+'\n')
        return scene


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('ram','metadata','game-root','output'):p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();require(not a.output.exists(),'Use a fresh dynamic scene folder')
    ram=a.ram.read_bytes();meta=json.loads(a.metadata.read_text())
    require(len(ram)==RAM_SIZE and hashlib.sha256(ram).hexdigest()==meta['ram_sha256'],'RAM capture hash mismatch')
    require(meta['executable_sha256']==EXE_SHA,'Unrecognized captured original')
    objects,fixups,_,_=executable_profile((a.game_root/'STARTH.EXE').read_bytes());loaded,_,_,physical=resolve(ram,objects,fixups)
    require(loaded==meta['objects'],'Captured object mapping mismatch')
    name=ram[physical(LINKS['world_name']):physical(LINKS['world_name'])+16].split(b'\0')[0].decode('ascii')
    require(name.upper() in {f'MAP{i}' for i in range(1,7)},'Unknown original track')
    a.output.parent.mkdir(parents=True,exist_ok=True);staging=a.output.with_name('.'+a.output.name+'.exporting-'+uuid.uuid4().hex)
    try:
        exporter=DynamicScene(a.game_root,int(name[-1]),staging,ram,physical)
        exporter.provenance['snapshot_ram_sha256']=meta['ram_sha256']
        scene=exporter.export();export_sky(a.game_root,int(name[-1]),staging/'sky');staging.rename(a.output)
    finally:
        if staging.exists():shutil.rmtree(staging)
    print(json.dumps({'scene':str(a.output/'scene.json'),'statistics':scene['statistics']},indent=2))


if __name__=='__main__':main()
